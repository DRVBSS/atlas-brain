"""Code file extraction with language detection and structure analysis."""

import ast
import re
from pathlib import Path

from atlas_brain.models import ProcessedDocument

LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".swift": "swift",
    ".kt": "kotlin",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
}


def _extract_python_structure(text: str) -> dict:
    """Use AST to extract Python structure."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}

    functions = []
    classes = []
    docstrings = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions.append(node.name)
            ds = ast.get_docstring(node)
            if ds:
                docstrings.append(f"{node.name}: {ds}")
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
            ds = ast.get_docstring(node)
            if ds:
                docstrings.append(f"{node.name}: {ds}")

    module_doc = ast.get_docstring(tree)
    if module_doc:
        docstrings.insert(0, f"Module: {module_doc}")

    return {
        "functions": functions,
        "classes": classes,
        "docstrings": docstrings,
    }


def _extract_generic_structure(text: str) -> dict:
    """Regex-based extraction for non-Python languages."""
    functions = re.findall(
        r'(?:function|func|def|fn|pub fn|async fn)\s+(\w+)', text
    )
    classes = re.findall(r'(?:class|struct|interface|enum|type)\s+(\w+)', text)
    comments = re.findall(r'(?://|#)\s*(.+)', text)

    return {
        "functions": functions,
        "classes": classes,
        "comments": comments[:20],
    }


def extract(file_path: Path) -> ProcessedDocument:
    """Extract from code files with structure analysis."""
    text = file_path.read_text(errors="replace")
    ext = file_path.suffix.lower()
    language = LANGUAGE_MAP.get(ext, "unknown")

    # Build structured representation
    if language == "python":
        structure = _extract_python_structure(text)
    else:
        structure = _extract_generic_structure(text)

    # Build a readable summary
    parts = [f"# {file_path.name}", f"Language: {language}", ""]

    if structure.get("classes"):
        parts.append(f"Classes: {', '.join(structure['classes'])}")
    if structure.get("functions"):
        parts.append(f"Functions: {', '.join(structure['functions'])}")
    if structure.get("docstrings"):
        parts.append("\n## Documentation")
        for ds in structure["docstrings"]:
            parts.append(f"- {ds}")

    parts.append("\n## Source Code")
    parts.append(f"```{language}")
    parts.append(text)
    parts.append("```")

    full_text = "\n".join(parts)

    sections = []
    if structure.get("classes"):
        sections.extend(f"class {c}" for c in structure["classes"])
    if structure.get("functions"):
        sections.extend(f"func {f}" for f in structure["functions"])

    return ProcessedDocument(
        text=full_text,
        title=file_path.name,
        author=None,
        created_date=None,
        word_count=len(text.split()),
        sections=sections,
        metadata={"language": language, **structure},
    )
