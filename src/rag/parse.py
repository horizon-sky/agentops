"""文档解析：支持纯文本、Markdown、PDF、DOCX。"""

from __future__ import annotations

from pathlib import Path


def parse_text(content: str) -> str:
    return content.replace("\r\n", "\n").strip()


def parse_file(path: str | Path) -> str:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        import docx

        document = docx.Document(str(file_path))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    return parse_text(file_path.read_text(encoding="utf-8", errors="ignore"))
