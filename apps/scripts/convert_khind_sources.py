"""Convert text-based KHIND source documents into Markdown for RAG ingestion."""

from __future__ import annotations

from pathlib import Path
import re

import fitz


SOURCE_DIR = Path("data_source/drive-download-20260911T203045Z-1-001")
OUTPUT_DIR = Path("data_source/rag/drive-download")


def _markdown_name(path: Path) -> str:
    relative = path.relative_to(SOURCE_DIR).with_suffix("")
    return "__".join(relative.parts) + ".md"


def _title(path: Path) -> str:
    return path.stem.replace("_", " ")


def _clean_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n\n".join(line for line in lines if line)


def _extract_pdf(path: Path) -> str:
    document = fitz.open(path)
    try:
        return "\n".join(page.get_text() for page in document)
    finally:
        document.close()


def _write_markdown(source: Path, text: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    content = (
        f"# {_title(source)}\n\n"
        f"**Source file:** `{source.name}`\n\n"
        "## Extracted Content\n\n"
        f"{_clean_text(text) or 'No selectable text was found in this document.'}\n"
    )
    (OUTPUT_DIR / _markdown_name(source)).write_text(content, encoding="utf-8")


def main() -> None:
    for source in sorted(SOURCE_DIR.rglob("*.pdf")):
        _write_markdown(source, _extract_pdf(source))

    for source in sorted(SOURCE_DIR.rglob("*.txt")):
        _write_markdown(source, source.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()