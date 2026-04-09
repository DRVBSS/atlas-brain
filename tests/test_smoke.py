"""Smoke coverage for Atlas Brain's critical paths and edge cases."""

import asyncio
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from atlas_brain.cli import app
from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection, init_schema, reset_connection
from atlas_brain.ingest.pipeline import ingest_file
from atlas_brain.knowledge.contradictions import detect_contradictions
from atlas_brain.knowledge.facts import promote_candidate
from atlas_brain.models import Fact, SearchResult
from atlas_brain.search.unified import search as unified_search
from atlas_brain.server.mcp_server import call_tool
from atlas_brain.server.rest_api import api
from atlas_brain.wiki.compiler import compile_topic


class AtlasSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_connection()
        self.runner = CliRunner()
        self.client = TestClient(api)

    def tearDown(self) -> None:
        reset_connection()

    @contextmanager
    def pushd(self, path: Path):
        old_cwd = Path.cwd()
        os.chdir(path)
        reset_connection()
        try:
            yield
        finally:
            reset_connection()
            os.chdir(old_cwd)

    def create_initialized_root(self) -> tuple[Path, AtlasConfig]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        config = AtlasConfig(root=root)
        for directory in config.all_dirs():
            directory.mkdir(parents=True, exist_ok=True)
        config.atlas_md_path.write_text("# Atlas Brain\n")
        init_schema(config.db_path)
        reset_connection()
        return root, config

    def insert_source_chunk(
        self,
        config: AtlasConfig,
        *,
        source_id: str = "src_test",
        chunk_id: str = "chk_test",
        title: str = "Test Topic",
        content: str = "Test Topic helps Atlas Brain stay organized.",
    ) -> None:
        original_path = config.sources_dir / "articles" / f"{source_id}_article.txt"
        processed_path = config.processed_dir / f"{source_id}.md"
        original_path.parent.mkdir(parents=True, exist_ok=True)
        original_path.write_text(content)
        processed_path.write_text(content)

        conn = get_connection(config.db_path)
        now = "2026-04-09T12:00:00+00:00"
        conn.execute(
            """INSERT INTO sources
               (source_id, original_path, processed_path, source_type, content_hash,
                title, author, created_date, ingested_at, word_count, language, metadata)
               VALUES (?, ?, ?, 'article', ?, ?, NULL, NULL, ?, ?, 'en', NULL)""",
            (
                source_id,
                str(original_path),
                str(processed_path),
                f"hash_{source_id}",
                title,
                now,
                len(content.split()),
            ),
        )
        conn.execute(
            """INSERT INTO chunks
               (chunk_id, source_id, chunk_index, content, section_heading, speaker, token_count)
               VALUES (?, ?, 0, ?, ?, '', ?)""",
            (chunk_id, source_id, content, title, len(content.split())),
        )
        rowid = conn.execute(
            "SELECT rowid FROM chunks WHERE chunk_id = ?",
            (chunk_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO chunks_fts(rowid, content, section_heading, speaker) VALUES (?, ?, ?, '')",
            (rowid, content, title),
        )
        conn.commit()

    def insert_fact(
        self,
        config: AtlasConfig,
        *,
        fact_id: str,
        subject: str,
        predicate: str,
        obj: str,
        source_ids: list[str],
        confidence: str = "TENTATIVE",
    ) -> None:
        conn = get_connection(config.db_path)
        conn.execute(
            """INSERT INTO facts
               (fact_id, subject, predicate, object, confidence, valid_from, valid_to,
                source_ids, extracted_by, extracted_at, verified_at, verified_by, superseded_by, notes)
               VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, 'test', '2026-04-09T12:00:00+00:00',
                       NULL, NULL, NULL, NULL)""",
            (fact_id, subject, predicate, obj, confidence, json.dumps(source_ids)),
        )
        conn.commit()

    def insert_candidate(
        self,
        config: AtlasConfig,
        *,
        candidate_id: str = "cand_test",
        source_id: str = "src_test",
        subject: str = "Test Topic",
        predicate: str = "status",
        obj: str = "ready",
    ) -> None:
        conn = get_connection(config.db_path)
        conn.execute(
            """INSERT INTO fact_candidates
               (candidate_id, source_id, subject, predicate, object, valid_from, valid_to,
                extraction_model, extracted_at, promoted, rejected)
               VALUES (?, ?, ?, ?, ?, NULL, NULL, 'test-model',
                       '2026-04-09T12:00:00+00:00', 0, 0)""",
            (candidate_id, source_id, subject, predicate, obj),
        )
        conn.commit()

    def test_status_requires_initialization(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        with self.pushd(Path(temp_dir.name)):
            result = self.runner.invoke(app, ["status"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Atlas Brain not initialized", result.stdout)

    def test_invalid_search_mode_returns_friendly_error(self) -> None:
        root, _ = self.create_initialized_root()
        with self.pushd(root):
            result = self.runner.invoke(app, ["search", "atlas", "--mode", "bogus"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Unknown search mode", result.stdout)

    def test_fts_keyword_injection_no_longer_crashes_search(self) -> None:
        _, config = self.create_initialized_root()
        self.insert_source_chunk(config, content="Atlas Brain search safety matters.")
        results = unified_search("' OR 1=1 --", config, modes=["lexical"])
        self.assertIsInstance(results, list)

    def test_ingest_skip_embed_avoids_embedding_work(self) -> None:
        root, config = self.create_initialized_root()
        source_file = root / "article.txt"
        source_file.write_text("# Test Topic\n\nAtlas Brain keeps information organized.")

        with patch(
            "atlas_brain.ingest.embedder.generate_embeddings",
            side_effect=AssertionError("embedding generation should be skipped"),
        ), patch(
            "atlas_brain.ingest.fact_extractor.extract_facts",
            return_value=[],
        ):
            result = ingest_file(source_file, config, skip_embeddings=True)

        self.assertEqual(result.status, "success")
        self.assertIn("embed_skipped", result.steps_completed)
        conn = get_connection(config.db_path)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)

    def test_fact_promotion_smoke(self) -> None:
        _, config = self.create_initialized_root()
        self.insert_source_chunk(config)
        self.insert_candidate(config)

        fact = promote_candidate("cand_test", config)

        self.assertEqual(fact.confidence, "VERIFIED")
        conn = get_connection(config.db_path)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0], 1)
        self.assertEqual(
            conn.execute(
                "SELECT promoted FROM fact_candidates WHERE candidate_id = 'cand_test'"
            ).fetchone()[0],
            1,
        )

    def test_contradiction_detection_smoke(self) -> None:
        _, config = self.create_initialized_root()
        self.insert_fact(
            config,
            fact_id="fct_one",
            subject="Atlas Brain",
            predicate="status",
            obj="alpha",
            source_ids=["src_alpha"],
        )
        self.insert_fact(
            config,
            fact_id="fct_two",
            subject="Atlas Brain",
            predicate="status",
            obj="beta",
            source_ids=["src_beta"],
        )

        contradictions = detect_contradictions(config)

        self.assertEqual(len(contradictions), 1)
        self.assertEqual(contradictions[0]["subject"], "Atlas Brain")

    def test_contradiction_source_filter_requires_exact_source_id_match(self) -> None:
        _, config = self.create_initialized_root()
        self.insert_fact(
            config,
            fact_id="fct_prefix_a",
            subject="Atlas Brain",
            predicate="region",
            obj="east",
            source_ids=["src_abcd"],
        )
        self.insert_fact(
            config,
            fact_id="fct_prefix_b",
            subject="Atlas Brain",
            predicate="region",
            obj="west",
            source_ids=["src_abcde"],
        )

        contradictions = detect_contradictions(config, source_id="src_abc")

        self.assertEqual(contradictions, [])

    def test_rest_ingest_rejects_paths_outside_root(self) -> None:
        root, _ = self.create_initialized_root()
        with self.pushd(root):
            response = self.client.post("/ingest", json={"path": "/etc/passwd"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Atlas root", response.text)

    def test_rest_topic_rejects_invalid_slug(self) -> None:
        root, _ = self.create_initialized_root()
        with self.pushd(root):
            response = self.client.get("/topic/%2E%2E")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid topic slug", response.text)

    def test_rest_promote_invalid_id_returns_400(self) -> None:
        root, _ = self.create_initialized_root()
        with self.pushd(root):
            response = self.client.post("/promote", json={"id": "missing"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("not found", response.text)

    def test_mcp_promote_invalid_id_returns_error_payload(self) -> None:
        root, _ = self.create_initialized_root()
        with self.pushd(root):
            result = asyncio.run(call_tool("atlas_promote", {"candidate_id": "missing"}))
        self.assertEqual(len(result), 1)
        self.assertIn("not found", result[0].text)

    def test_wiki_compile_preserves_change_log_and_searches_by_title(self) -> None:
        _, config = self.create_initialized_root()
        self.insert_source_chunk(
            config,
            title="Test Topic",
            content="Test Topic is the canonical name for this wiki page.",
        )
        self.insert_fact(
            config,
            fact_id="fct_topic",
            subject="Test Topic",
            predicate="kind",
            obj="concept",
            confidence="VERIFIED",
            source_ids=["src_test"],
        )

        existing_path = config.wiki_dir / "test_topic.md"
        existing_path.write_text(
            "# Test Topic\n\n## Change Log\n\n- 2026-04-08: Initial compilation from 1 sources\n"
        )

        fake_results = [
            SearchResult(
                chunk_id="chk_test",
                content="Test Topic is the canonical name for this wiki page.",
                source_id="src_test",
                source_type="article",
                source_title="Test Topic",
                section_heading="Test Topic",
                relevance_score=1.0,
                citation="[src:src_test]",
            )
        ]

        with patch("atlas_brain.wiki.compiler.search", return_value=fake_results) as search_mock, patch(
            "atlas_brain.wiki.compiler._generate_with_llm",
            return_value=None,
        ):
            path = compile_topic("test_topic", config, force=True)

        self.assertIn("Test Topic", search_mock.call_args.args[0])
        self.assertIn("test_topic", search_mock.call_args.args[0])

        content = path.read_text()
        self.assertIn("- 2026-04-08: Initial compilation from 1 sources", content)
        self.assertIn("- 2026-04-09: Recompiled with 1 sources", content)


if __name__ == "__main__":
    unittest.main()
