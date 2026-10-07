"""Download the RAG benchmark corpus and check every hash.

    uv run python -m evals.rag.fetch_corpus [--dir .cache/rag-corpus]

Stops on the first mismatch: a changed document silently invalidates every label in
evals/rag/questions.yaml.
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

import httpx2
import yaml

ROOT = Path(__file__).resolve().parents[2]
CORPUS = Path(__file__).with_name("corpus.yaml")
DEFAULT_DIR = ROOT / ".cache" / "rag-corpus"


def markdown_to_docx(markdown: str, target: Path) -> None:
    """Headings and paragraphs only; enough to exercise the DOCX parser."""
    from docx import Document

    doc = Document()
    for block in re.split(r"\n\s*\n", markdown):
        text = block.strip()
        if not text or text.startswith("{*"):
            continue
        heading = re.match(r"^(#{1,6})\s+(.*?)(\s*\{.*\})?$", text)
        if heading:
            doc.add_heading(heading.group(2), level=len(heading.group(1)))
        else:
            doc.add_paragraph(" ".join(text.split()))
    doc.save(str(target))


def fetch(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    entries = yaml.safe_load(CORPUS.read_text())["documents"]
    paths: list[Path] = []
    with httpx2.Client(follow_redirects=True, timeout=60) as client:
        for entry in entries:
            target = directory / entry["name"]
            response = client.get(entry["url"])
            response.raise_for_status()
            digest = hashlib.sha256(response.content).hexdigest()
            if digest != entry["sha256"]:
                sys.exit(f"{entry['name']}: sha256 {digest} != {entry['sha256']}")
            if entry.get("convert") == "docx":
                markdown_to_docx(response.text, target)
            else:
                target.write_bytes(response.content)
            print(f"ok  {entry['name']}")
            paths.append(target)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    fetch(parser.parse_args().dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
