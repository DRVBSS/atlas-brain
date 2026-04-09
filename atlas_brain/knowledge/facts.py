"""Fact CRUD, promotion, querying."""

import json
import sqlite3
from datetime import datetime, timezone

from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection
from atlas_brain.knowledge.trust import apply_confidence_transition
from atlas_brain.models import Fact, FactCandidate
from atlas_brain.utils.ids import generate_id


def _row_to_fact(row) -> Fact:
    """Convert a SQLite row into a Fact dataclass."""
    return Fact(
        fact_id=row["fact_id"],
        subject=row["subject"],
        predicate=row["predicate"],
        object=row["object"],
        confidence=row["confidence"],
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        source_ids=json.loads(row["source_ids"]) if row["source_ids"] else [],
        extracted_by=row["extracted_by"],
        extracted_at=row["extracted_at"],
        verified_at=row["verified_at"],
        verified_by=row["verified_by"],
        superseded_by=row["superseded_by"],
        notes=row["notes"],
    )


def _get_active_fact(conn, subject: str, predicate: str, obj: str):
    """Fetch the active canonical fact for a triple, if present."""
    return conn.execute(
        """SELECT * FROM facts
           WHERE subject = ? AND predicate = ? AND object = ?
             AND superseded_by IS NULL""",
        (subject, predicate, obj),
    ).fetchone()


def _merge_source_ids(existing_source_ids: str | None, new_source_ids: list[str]) -> tuple[list[str], bool]:
    """Merge source provenance lists while preserving order."""
    merged = json.loads(existing_source_ids) if existing_source_ids else []
    changed = False
    for source_id in new_source_ids:
        if source_id not in merged:
            merged.append(source_id)
            changed = True
    return merged, changed


def _corroborated_confidence_target(old_confidence: str, source_count: int) -> str:
    """Return the allowed confidence target after provenance corroboration."""
    if source_count < 2:
        return old_confidence
    if old_confidence in {"TENTATIVE", "STALE"}:
        return "DERIVED"
    return old_confidence


def _merge_duplicate_fact(
    conn,
    existing,
    source_ids: list[str],
    confidence: str,
    now: str,
    reason: str,
) -> Fact:
    """Merge provenance into an existing canonical fact instead of duplicating it."""
    merged_source_ids, source_changed = _merge_source_ids(existing["source_ids"], source_ids)
    if source_changed:
        conn.execute(
            "UPDATE facts SET source_ids = ? WHERE fact_id = ?",
            (json.dumps(merged_source_ids), existing["fact_id"]),
        )

    old_confidence = existing["confidence"]
    if confidence == "VERIFIED" and old_confidence != "VERIFIED":
        conn.execute(
            "UPDATE facts SET verified_at = ?, verified_by = 'human' WHERE fact_id = ?",
            (now, existing["fact_id"]),
        )
        apply_confidence_transition(
            conn,
            "fact",
            existing["fact_id"],
            "VERIFIED",
            reason,
            source_id=source_ids[0] if source_ids else None,
            event_type="verified_human",
        )
    elif source_changed:
        _log_trust_event(
            conn,
            "fact",
            existing["fact_id"],
            "corroborated",
            old_confidence,
            old_confidence,
            reason,
            source_ids[0] if source_ids else None,
        )

    row = conn.execute("SELECT * FROM facts WHERE fact_id = ?", (existing["fact_id"],)).fetchone()
    return _row_to_fact(row)


def add_fact(
    subject: str,
    predicate: str,
    obj: str,
    source_ids: list[str],
    config: AtlasConfig,
    confidence: str = "VERIFIED",
    extracted_by: str = "human",
) -> Fact:
    """Manually add a canonical fact."""
    conn = get_connection(config.db_path)
    now = datetime.now(timezone.utc).isoformat()
    reason = "Manual fact creation"

    existing = _get_active_fact(conn, subject, predicate, obj)
    if existing:
        fact = _merge_duplicate_fact(conn, existing, source_ids, confidence, now, reason)
        conn.commit()
        return fact

    fact = Fact(
        fact_id=generate_id("fct"),
        subject=subject,
        predicate=predicate,
        object=obj,
        confidence=confidence,
        source_ids=source_ids,
        extracted_by=extracted_by,
        extracted_at=now,
        verified_at=now if confidence == "VERIFIED" else None,
        verified_by="human" if confidence == "VERIFIED" else None,
    )

    try:
        conn.execute(
            """INSERT INTO facts
               (fact_id, subject, predicate, object, confidence,
                valid_from, valid_to, source_ids, extracted_by, extracted_at,
                verified_at, verified_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fact.fact_id, fact.subject, fact.predicate, fact.object, fact.confidence,
             fact.valid_from, fact.valid_to, json.dumps(fact.source_ids),
             fact.extracted_by, fact.extracted_at, fact.verified_at, fact.verified_by),
        )
    except sqlite3.IntegrityError:
        # Another writer won the race; merge into the canonical row instead of surfacing a raw DB error.
        conn.rollback()
        existing = _get_active_fact(conn, subject, predicate, obj)
        if existing:
            fact = _merge_duplicate_fact(conn, existing, source_ids, confidence, now, reason)
            conn.commit()
            return fact
        raise

    # Log trust event
    _log_trust_event(conn, "fact", fact.fact_id, "created", None, confidence,
                     reason, source_ids[0] if source_ids else None)
    conn.commit()
    return fact


def promote_candidate(candidate_id: str, config: AtlasConfig) -> Fact:
    """Promote a fact candidate to canonical fact with VERIFIED confidence.

    If the canonical triple already exists (e.g. from auto-promotion),
    upgrades it to VERIFIED and merges provenance instead of inserting a duplicate.
    """
    conn = get_connection(config.db_path)

    row = conn.execute(
        "SELECT * FROM fact_candidates WHERE candidate_id = ?", (candidate_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"Candidate {candidate_id} not found")
    if row["promoted"]:
        raise ValueError(f"Candidate {candidate_id} already promoted")
    if row["rejected"]:
        raise ValueError(f"Candidate {candidate_id} was rejected")

    now = datetime.now(timezone.utc).isoformat()

    # Check if canonical fact already exists — upgrade instead of insert
    existing = conn.execute(
        """SELECT fact_id, source_ids, confidence FROM facts
           WHERE subject = ? AND predicate = ? AND object = ?
             AND superseded_by IS NULL""",
        (row["subject"], row["predicate"], row["object"]),
    ).fetchone()

    if existing:
        # Upgrade existing fact to VERIFIED and merge provenance
        source_ids, source_changed = _merge_source_ids(existing["source_ids"], [row["source_id"]])
        old_conf = existing["confidence"]
        conn.execute(
            """UPDATE facts SET source_ids = ?, verified_at = ?,
               verified_by = 'human' WHERE fact_id = ?""",
            (json.dumps(source_ids), now, existing["fact_id"]),
        )
        if old_conf != "VERIFIED":
            apply_confidence_transition(
                conn,
                "fact",
                existing["fact_id"],
                "VERIFIED",
                f"Human-promoted from candidate {candidate_id}",
                source_id=row["source_id"],
                event_type="verified_human",
            )
        elif source_changed:
            _log_trust_event(conn, "fact", existing["fact_id"], "corroborated",
                             old_conf, old_conf,
                             f"Human-promoted candidate {candidate_id} added source provenance",
                             row["source_id"])
        fact = Fact(
            fact_id=existing["fact_id"],
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            confidence="VERIFIED",
            source_ids=source_ids,
            verified_at=now,
            verified_by="human",
        )
    else:
        # No existing fact — insert new VERIFIED fact
        fact = Fact(
            fact_id=generate_id("fct"),
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            confidence="VERIFIED",
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            source_ids=[row["source_id"]],
            extracted_by=row["extraction_model"],
            extracted_at=row["extracted_at"],
            verified_at=now,
            verified_by="human",
        )
        conn.execute(
            """INSERT INTO facts
               (fact_id, subject, predicate, object, confidence,
                valid_from, valid_to, source_ids, extracted_by, extracted_at,
                verified_at, verified_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fact.fact_id, fact.subject, fact.predicate, fact.object, fact.confidence,
             fact.valid_from, fact.valid_to, json.dumps(fact.source_ids),
             fact.extracted_by, fact.extracted_at, fact.verified_at, fact.verified_by),
        )
        _log_trust_event(conn, "fact", fact.fact_id, "verified_human", None, "VERIFIED",
                         f"Promoted from candidate {candidate_id}", row["source_id"])

    conn.execute(
        "UPDATE fact_candidates SET promoted = 1 WHERE candidate_id = ?",
        (candidate_id,),
    )
    conn.commit()
    return fact


def reject_candidate(candidate_id: str, config: AtlasConfig) -> None:
    """Reject a fact candidate."""
    conn = get_connection(config.db_path)

    row = conn.execute(
        "SELECT * FROM fact_candidates WHERE candidate_id = ?", (candidate_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"Candidate {candidate_id} not found")

    conn.execute(
        "UPDATE fact_candidates SET rejected = 1 WHERE candidate_id = ?",
        (candidate_id,),
    )
    conn.commit()


def auto_promote_corroborated(config: AtlasConfig, source_id: str | None = None) -> list[Fact]:
    """Auto-promote candidates corroborated by different sources.

    When source_id is provided, only considers candidates from that source
    (incremental). Otherwise scans all pending candidates.
    """
    conn = get_connection(config.db_path)

    # Find candidates with same subject+predicate+object from different sources
    if source_id:
        rows = conn.execute(
            """SELECT c1.candidate_id, c1.subject, c1.predicate, c1.object,
                      c1.source_id as src1, c2.source_id as src2,
                      c1.valid_from, c1.valid_to, c1.extraction_model, c1.extracted_at
               FROM fact_candidates c1
               JOIN fact_candidates c2
                 ON c1.subject = c2.subject
                 AND c1.predicate = c2.predicate
                 AND c1.object = c2.object
                 AND c1.source_id != c2.source_id
               WHERE c1.promoted = 0 AND c1.rejected = 0
                 AND c2.promoted = 0 AND c2.rejected = 0
                 AND (c1.source_id = ? OR c2.source_id = ?)
               GROUP BY c1.subject, c1.predicate, c1.object""",
            (source_id, source_id),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT c1.candidate_id, c1.subject, c1.predicate, c1.object,
                      c1.source_id as src1, c2.source_id as src2,
                      c1.valid_from, c1.valid_to, c1.extraction_model, c1.extracted_at
               FROM fact_candidates c1
               JOIN fact_candidates c2
                 ON c1.subject = c2.subject
                 AND c1.predicate = c2.predicate
                 AND c1.object = c2.object
                 AND c1.source_id != c2.source_id
               WHERE c1.promoted = 0 AND c1.rejected = 0
                 AND c2.promoted = 0 AND c2.rejected = 0
               GROUP BY c1.subject, c1.predicate, c1.object"""
        ).fetchall()

    promoted = []
    now = datetime.now(timezone.utc).isoformat()

    for row in rows:
        # Check if canonical fact already exists — merge sources if so
        existing = conn.execute(
            """SELECT fact_id, source_ids, confidence FROM facts
               WHERE subject = ? AND predicate = ? AND object = ?
                 AND superseded_by IS NULL""",
            (row["subject"], row["predicate"], row["object"]),
        ).fetchone()

        if existing:
            source_ids, changed = _merge_source_ids(existing["source_ids"], [row["src1"], row["src2"]])
            if changed:
                conn.execute(
                    "UPDATE facts SET source_ids = ? WHERE fact_id = ?",
                    (json.dumps(source_ids), existing["fact_id"]),
                )
                old_conf = existing["confidence"]
                new_conf = _corroborated_confidence_target(old_conf, len(source_ids))
                reason = f"Corroborated by sources {row['src1']}, {row['src2']}"
                if new_conf != old_conf:
                    apply_confidence_transition(
                        conn,
                        "fact",
                        existing["fact_id"],
                        new_conf,
                        reason,
                        source_id=row["src1"],
                        event_type="corroborated",
                    )
                else:
                    _log_trust_event(conn, "fact", existing["fact_id"], "corroborated",
                                     old_conf, old_conf, reason, row["src1"])
        else:
            fact = Fact(
                fact_id=generate_id("fct"),
                subject=row["subject"],
                predicate=row["predicate"],
                object=row["object"],
                confidence="DERIVED",
                valid_from=row["valid_from"],
                valid_to=row["valid_to"],
                source_ids=[row["src1"], row["src2"]],
                extracted_by=row["extraction_model"],
                extracted_at=row["extracted_at"],
            )

            conn.execute(
                """INSERT INTO facts
                   (fact_id, subject, predicate, object, confidence,
                    valid_from, valid_to, source_ids, extracted_by, extracted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (fact.fact_id, fact.subject, fact.predicate, fact.object, fact.confidence,
                 fact.valid_from, fact.valid_to, json.dumps(fact.source_ids),
                 fact.extracted_by, fact.extracted_at),
            )
            _log_trust_event(conn, "fact", fact.fact_id, "created", None, "DERIVED",
                             f"Auto-promoted: corroborated by sources {row['src1']}, {row['src2']}",
                             row["src1"])
            promoted.append(fact)

        # Mark candidates as promoted
        conn.execute(
            """UPDATE fact_candidates SET promoted = 1
               WHERE subject = ? AND predicate = ? AND object = ?
                 AND promoted = 0 AND rejected = 0""",
            (row["subject"], row["predicate"], row["object"]),
        )

    conn.commit()
    return promoted


def auto_promote_single_source(config: AtlasConfig, source_id: str | None = None) -> list[Fact]:
    """
    Auto-promote well-formed candidates from a single source.
    A candidate is well-formed if subject, predicate, and object are all
    non-trivial (>2 chars each). Promoted as TENTATIVE until corroboration
    or human review raises confidence.

    When source_id is provided, only processes candidates from that source.
    """
    conn = get_connection(config.db_path)
    now = datetime.now(timezone.utc).isoformat()

    if source_id:
        rows = conn.execute(
            """SELECT * FROM fact_candidates
               WHERE promoted = 0 AND rejected = 0
                 AND source_id = ?
                 AND length(subject) > 2
                 AND length(predicate) > 2
                 AND length(object) > 2""",
            (source_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM fact_candidates
               WHERE promoted = 0 AND rejected = 0
                 AND length(subject) > 2
                 AND length(predicate) > 2
                 AND length(object) > 2"""
        ).fetchall()

    promoted = []
    for row in rows:
        # Check if an identical canonical fact already exists
        existing = conn.execute(
            """SELECT fact_id, source_ids, confidence FROM facts
               WHERE subject = ? AND predicate = ? AND object = ?
                 AND superseded_by IS NULL""",
            (row["subject"], row["predicate"], row["object"]),
        ).fetchone()
        if existing:
            # Merge provenance — add this source to the existing fact, never downgrade
            source_ids, changed = _merge_source_ids(existing["source_ids"], [row["source_id"]])
            if changed:
                conn.execute(
                    "UPDATE facts SET source_ids = ? WHERE fact_id = ?",
                    (json.dumps(source_ids), existing["fact_id"]),
                )
                old_conf = existing["confidence"]
                new_confidence = _corroborated_confidence_target(old_conf, len(source_ids))
                reason = f"New source {row['source_id']} corroborates existing fact"
                if new_confidence != old_conf:
                    apply_confidence_transition(
                        conn,
                        "fact",
                        existing["fact_id"],
                        new_confidence,
                        reason,
                        source_id=row["source_id"],
                        event_type="corroborated",
                    )
                else:
                    _log_trust_event(conn, "fact", existing["fact_id"], "corroborated",
                                     old_conf, old_conf, reason, row["source_id"])
            conn.execute(
                "UPDATE fact_candidates SET promoted = 1 WHERE candidate_id = ?",
                (row["candidate_id"],),
            )
            continue

        fact = Fact(
            fact_id=generate_id("fct"),
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            confidence="TENTATIVE",
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            source_ids=[row["source_id"]],
            extracted_by=row["extraction_model"],
            extracted_at=row["extracted_at"],
        )

        conn.execute(
            """INSERT INTO facts
               (fact_id, subject, predicate, object, confidence,
                valid_from, valid_to, source_ids, extracted_by, extracted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fact.fact_id, fact.subject, fact.predicate, fact.object, fact.confidence,
             fact.valid_from, fact.valid_to, json.dumps(fact.source_ids),
             fact.extracted_by, fact.extracted_at),
        )

        conn.execute(
            "UPDATE fact_candidates SET promoted = 1 WHERE candidate_id = ?",
            (row["candidate_id"],),
        )

        _log_trust_event(conn, "fact", fact.fact_id, "created", None, "TENTATIVE",
                         "Auto-promoted: well-formed single-source extraction awaiting corroboration", row["source_id"])
        promoted.append(fact)

    conn.commit()
    return promoted


def query_facts(
    config: AtlasConfig,
    subject: str | None = None,
    predicate: str | None = None,
    current: bool = False,
    confidence: str | None = None,
) -> list[Fact]:
    """Query canonical facts with filters."""
    conn = get_connection(config.db_path)

    where_clauses = ["1=1"]
    params = []

    if subject:
        where_clauses.append("subject LIKE ?")
        params.append(f"%{subject}%")
    if predicate:
        where_clauses.append("predicate LIKE ?")
        params.append(f"%{predicate}%")
    if current:
        where_clauses.append("(valid_to IS NULL OR valid_to >= date('now'))")
    if confidence:
        where_clauses.append("confidence = ?")
        params.append(confidence)

    where_sql = " AND ".join(where_clauses)
    rows = conn.execute(
        f"SELECT * FROM facts WHERE {where_sql} ORDER BY extracted_at DESC",
        params,
    ).fetchall()

    return [
        _row_to_fact(r)
        for r in rows
    ]


def list_candidates(config: AtlasConfig, include_reviewed: bool = False) -> list[FactCandidate]:
    """List fact candidates."""
    conn = get_connection(config.db_path)

    if include_reviewed:
        rows = conn.execute("SELECT * FROM fact_candidates ORDER BY extracted_at DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM fact_candidates WHERE promoted = 0 AND rejected = 0 ORDER BY extracted_at DESC"
        ).fetchall()

    return [
        FactCandidate(
            candidate_id=r["candidate_id"],
            source_id=r["source_id"],
            subject=r["subject"],
            predicate=r["predicate"],
            object=r["object"],
            valid_from=r["valid_from"],
            valid_to=r["valid_to"],
            extraction_model=r["extraction_model"],
            extracted_at=r["extracted_at"],
            promoted=r["promoted"],
            rejected=r["rejected"],
        )
        for r in rows
    ]


def _log_trust_event(
    conn, target_type, target_id, event_type, old_conf, new_conf, reason, source_id
):
    """Log a trust event. Does NOT commit — caller manages the transaction."""
    conn.execute(
        """INSERT INTO trust_events
           (event_id, target_type, target_id, event_type,
            old_confidence, new_confidence, reason, source_id, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (generate_id("evt"), target_type, target_id, event_type,
         old_conf, new_conf, reason, source_id,
         datetime.now(timezone.utc).isoformat()),
    )
