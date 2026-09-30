from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"\[[^]]*]\(([^)]+)\)")
MARKDOWN_FILES = [PROJECT_ROOT / "README.md", *sorted((PROJECT_ROOT / "docs").rglob("*.md"))]


@pytest.mark.parametrize("document", MARKDOWN_FILES, ids=lambda path: str(path.relative_to(PROJECT_ROOT)))
def test_local_documentation_links_exist(document: Path) -> None:
    missing: list[str] = []
    for target in MARKDOWN_LINK.findall(document.read_text(encoding="utf-8")):
        path_text = unquote(target.split("#", 1)[0]).strip()
        if not path_text or "://" in path_text or path_text.startswith("mailto:"):
            continue
        if not (document.parent / path_text).resolve().exists():
            missing.append(target)

    assert not missing, f"Broken local links in {document.relative_to(PROJECT_ROOT)}: {missing}"
