"""Heading-aware chunker that turns a Markdown, HTML or PDF source into passage entries for manual completion.

    python -m smartagri.retrieval.ingest <file.md|.html|.htm|.pdf> --document-id X [--out new_passages.yaml]

The text is split at headings; inside a section, paragraphs are packed into passages of about
MAX_TOKENS tokens with OVERLAP tokens carried over from the previous passage of the same section
(see docs/architecture.md). A Markdown table is kept whole in one passage, never split or overlapped, so
its units stay with its numbers. Tokens are whitespace-separated words, an approximation of model
tokens that is good enough for sizing.

Every entry is written with `verify: true`, its `heading_path`, and an empty `meta` that the corpus
administrator completes from config/vocab.yaml before the passage is added to corpus/passages.yaml.
An entry with empty meta would be unrestricted for pi, so the output is never merged automatically.

HTML is converted to Markdown with the standard library parser: h1-h4 become Markdown headings,
tables become Markdown tables (first row, or the row of <th> cells, as the header), scripts and
styles are dropped. PDF text is extracted per page with pypdf (optional extra `ingest`); a page is
split into paragraphs at blank lines and packed like a Markdown section, and every entry carries its
page in `source_ref`. PDF extraction does not recognise tables or headings: check those passages
against the page.

Values that exist only in figures are typed by hand into `corpus/transcribed/<document id>.md`; when
that file exists, its passages are appended with `transcribed: true` and
`source_ref: transcribed/<document id>.md`.
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

MAX_TOKENS = 350
OVERLAP = 40
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def slug(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "dj"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40] or "section"


def n_tokens(text: str) -> int:
    return len(text.split())


def sections(markdown: str) -> List[Tuple[List[str], List[Tuple[str, str]]]]:
    """[(heading path, blocks)], block = (kind, text) with kind 'text' or 'table'."""
    out: List[Tuple[List[str], List[Tuple[str, str]]]] = []
    path: List[str] = []
    blocks: List[Tuple[str, str]] = []
    buf: List[str] = []
    kind = "text"

    def flush_block():
        nonlocal buf
        text = "\n".join(buf).strip() if kind == "table" else " ".join(line.strip() for line in buf).strip()
        if text:
            blocks.append((kind, text))
        buf = []

    def flush_section():
        nonlocal blocks
        flush_block()
        if blocks:
            out.append((list(path), blocks))
        blocks = []

    for line in markdown.splitlines():
        m = HEADING.match(line)
        if m:
            flush_section()
            level = len(m.group(1))
            path = path[:level - 1] + [""] * max(0, level - 1 - len(path)) + [m.group(2)]
            path = [p for p in path if p]
            continue
        is_table = line.lstrip().startswith("|")
        if not line.strip() or (is_table and kind != "table") or (not is_table and kind == "table"):
            flush_block()
            kind = "table" if is_table else "text"
            if not line.strip():
                continue
        buf.append(line)
    flush_section()
    return out


def _split_long(text: str, max_tokens: int) -> List[str]:
    """Split an over-long paragraph at sentence ends, then at word boundaries if needed."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    parts: List[str] = []
    cur: List[str] = []
    for s in sentences:
        words = s.split()
        while len(words) > max_tokens:
            if cur:
                parts.append(" ".join(cur))
                cur = []
            parts.append(" ".join(words[:max_tokens]))
            words = words[max_tokens:]
        if cur and len(cur) + len(words) > max_tokens:
            parts.append(" ".join(cur))
            cur = []
        cur += words
    if cur:
        parts.append(" ".join(cur))
    return parts


def chunk_section(blocks: List[Tuple[str, str]], max_tokens: int = MAX_TOKENS, overlap: int = OVERLAP) -> List[str]:
    pieces: List[Tuple[str, str]] = []
    for kind, text in blocks:
        if kind == "table" or n_tokens(text) <= max_tokens:
            pieces.append((kind, text))
        else:
            pieces += [("text", p) for p in _split_long(text, max_tokens - overlap)]
    chunks: List[str] = []
    cur: List[str] = []
    cur_tokens = 0
    for kind, text in pieces:
        size = n_tokens(text)
        if kind == "table":
            if cur:
                chunks.append("\n\n".join(cur))
            chunks.append(text)
            cur, cur_tokens = [], 0
            continue
        if cur and cur_tokens + size > max_tokens:
            chunks.append("\n\n".join(cur))
            prev_words = " ".join(cur).split()
            tail = " ".join(prev_words[-overlap:]) if overlap else ""
            cur, cur_tokens = ([tail] if tail else []), n_tokens(tail)
        cur.append(text)
        cur_tokens += size
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def _next_id(base: str, used: Set[str]) -> str:
    n = 1
    while "%s-%d" % (base, n) in used:
        n += 1
    used.add("%s-%d" % (base, n))
    return "%s-%d" % (base, n)


def ingest(markdown: str, document_id: str, max_tokens: int = MAX_TOKENS, overlap: int = OVERLAP,
           used: Optional[Set[str]] = None, id_prefix: Optional[str] = None) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    used = set() if used is None else used
    prefix = id_prefix or document_id
    for path, blocks in sections(markdown):
        base = "%s-%s" % (prefix, slug(path[-1]) if path else "uvod")
        for text in chunk_section(blocks, max_tokens, overlap):
            entries.append({"id": _next_id(base, used), "document_id": document_id, "verify": True,
                            "heading_path": list(path), "text": text, "meta": {}})
    return entries


# ------------------------------------------------------------------ HTML

_SKIP = {"script", "style", "noscript", "template", "head", "svg"}
_BLOCK = {"p", "div", "section", "article", "main", "header", "footer", "aside", "nav", "blockquote", "pre",
          "ul", "ol", "li", "dl", "dt", "dd", "br", "hr", "h5", "h6", "figure", "figcaption", "form", "address"}


class _HtmlToMarkdown(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []           # Markdown blocks
        self.buf: List[str] = []           # running paragraph text
        self.skip = 0
        self.heading: Optional[int] = None
        self.table_depth = 0
        self.rows: List[Tuple[List[str], bool]] = []
        self.row: Optional[List[str]] = None
        self.row_header = False
        self.cell: Optional[List[str]] = None

    def _flush(self):
        text = " ".join("".join(self.buf).split())
        self.buf = []
        if not text:
            return
        if self.heading:
            self.out.append("%s %s" % ("#" * self.heading, text))
        else:
            self.out.append(text.lstrip("#|").strip() or text)   # never let a paragraph read as heading/table

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "table":
            self.table_depth += 1
            if self.table_depth == 1:
                self._flush()
                self.rows = []
            return
        if self.table_depth > 1:              # nested table: its text stays in the outer cell
            return
        if self.table_depth == 1:
            if tag == "tr":
                self.row, self.row_header = [], False
            elif tag in ("td", "th"):
                if self.row is None:
                    self.row, self.row_header = [], False
                self.cell = []
                self.row_header = self.row_header or tag == "th"
            elif tag == "br" and self.cell is not None:
                self.cell.append(" ")
            return
        if tag in ("h1", "h2", "h3", "h4"):
            self._flush()
            self.heading = int(tag[1])
        elif tag in _BLOCK:
            self._flush()
            if tag == "li":
                self.buf.append("- ")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "table":
            self.table_depth = max(0, self.table_depth - 1)
            if self.table_depth == 0:
                self._end_row()
                self.out.append(_markdown_table(self.rows))
                self.rows = []
            return
        if self.table_depth > 1:
            return
        if self.table_depth == 1:
            if tag in ("td", "th"):
                self._end_cell()
            elif tag == "tr":
                self._end_row()
            return
        if tag in ("h1", "h2", "h3", "h4"):
            self._flush()
            self.heading = None
        elif tag in _BLOCK:
            self._flush()

    def _end_cell(self):
        if self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
        self.cell = None

    def _end_row(self):
        self._end_cell()
        if self.row:
            self.rows.append((self.row, self.row_header))
        self.row = None

    def handle_data(self, data):
        if self.skip:
            return
        if self.table_depth:
            if self.cell is not None:
                self.cell.append(data)
            return
        self.buf.append(data)

    def close(self):
        super().close()
        self._flush()


def _markdown_table(rows: List[Tuple[List[str], bool]]) -> str:
    rows = [(r, h) for r, h in rows if any(c for c in r)]
    if not rows:
        return ""
    header_at = next((i for i, (_, h) in enumerate(rows) if h), 0)
    ordered = [rows[header_at][0]] + [r for i, (r, _) in enumerate(rows) if i != header_at]
    width = max(len(r) for r in ordered)

    def line(cells):
        cells = [c.replace("|", "\\|") for c in cells] + [""] * (width - len(cells))
        return "| " + " | ".join(cells) + " |"
    return "\n".join([line(ordered[0]), "|" + "---|" * width] + [line(r) for r in ordered[1:]])


def html_to_markdown(html: str) -> str:
    parser = _HtmlToMarkdown()
    parser.feed(html)
    parser.close()
    return "\n\n".join(b for b in parser.out if b) + "\n"


# ------------------------------------------------------------------ PDF

def pdf_pages(path: Path) -> List[str]:
    """Text of every page (pypdf, layout mode so blank lines between paragraphs survive)."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:                # optional dependency
        raise RuntimeError("PDF ingestion needs pypdf: pip install 'smartagri[ingest]'") from exc
    pages = []
    for page in PdfReader(str(path)).pages:
        try:
            text = page.extract_text(extraction_mode="layout")
        except Exception:                     # layout mode fails on some fonts; plain mode still gives text
            text = page.extract_text()
        pages.append(text or "")
    return pages


def ingest_pdf_pages(pages: List[str], document_id: str, max_tokens: int = MAX_TOKENS, overlap: int = OVERLAP,
                     used: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    """One section per page: paragraphs at blank lines, packed to the token budget; page in `source_ref`."""
    entries: List[Dict[str, Any]] = []
    used = set() if used is None else used
    for number, text in enumerate(pages, start=1):
        paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
        blocks = [("text", p) for p in paragraphs if p]
        for chunk in chunk_section(blocks, max_tokens, overlap):
            entries.append({"id": _next_id("%s-p%d" % (document_id, number), used), "document_id": document_id,
                            "verify": True, "heading_path": [], "source_ref": "p. %d" % number,
                            "text": chunk, "meta": {}})
    return entries


# ------------------------------------------------------------------ transcribed values

def transcribed_entries(document_id: str, corpus: Path, max_tokens: int = MAX_TOKENS, overlap: int = OVERLAP,
                        used: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    """Passages of corpus/transcribed/<document_id>.md (values read off figures), or [] if there is none."""
    path = corpus / "transcribed" / ("%s.md" % document_id)
    if not path.is_file():
        return []
    entries = ingest(path.read_text(encoding="utf-8"), document_id, max_tokens, overlap, used=used,
                     id_prefix="%s-transkript" % document_id)
    for e in entries:
        e["transcribed"] = True
        e["source_ref"] = "transcribed/%s.md" % document_id
    return entries


def ingest_file(path: Path, document_id: str, max_tokens: int = MAX_TOKENS, overlap: int = OVERLAP,
                corpus: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Entries for a .md/.markdown, .html/.htm or .pdf source, plus its transcribed passages if any."""
    used: Set[str] = set()
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm"):
        entries = ingest(html_to_markdown(path.read_text(encoding="utf-8", errors="replace")), document_id,
                         max_tokens, overlap, used=used)
    elif suffix == ".pdf":
        entries = ingest_pdf_pages(pdf_pages(path), document_id, max_tokens, overlap, used=used)
    elif suffix in (".md", ".markdown", ".txt"):
        entries = ingest(path.read_text(encoding="utf-8"), document_id, max_tokens, overlap, used=used)
    else:
        raise ValueError("Unsupported source type %s (expected .md, .html, .htm or .pdf)" % suffix)
    if corpus is None:
        from .corpus import corpus_dir
        corpus = corpus_dir()
    return entries + transcribed_entries(document_id, corpus, max_tokens, overlap, used=used)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m smartagri.retrieval.ingest", description=__doc__.split("\n")[0])
    ap.add_argument("source", type=Path, help="Markdown, HTML (.html/.htm) or PDF file")
    ap.add_argument("--document-id", required=True, help="manifest id of the source document")
    ap.add_argument("--out", type=Path, help="write the YAML here (refuses to overwrite); default stdout")
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    ap.add_argument("--overlap", type=int, default=OVERLAP)
    ap.add_argument("--corpus-dir", type=Path, help="where transcribed/<id>.md is looked up; default SMARTAGRI_CORPUS_DIR or backend/corpus")
    args = ap.parse_args(argv)
    if args.overlap >= args.max_tokens:
        ap.error("--overlap must be smaller than --max-tokens")
    try:
        entries = ingest_file(args.source, args.document_id, args.max_tokens, args.overlap, args.corpus_dir)
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    text = ("# Generated by smartagri.retrieval.ingest from %s. Complete every `meta` from config/vocab.yaml,\n"
            "# check the text against the source, then move the entries into corpus/passages.yaml.\n"
            % args.source.name) + yaml.safe_dump(entries, allow_unicode=True, sort_keys=False, width=110)
    if args.out:
        if args.out.exists():
            print("Refusing to overwrite %s" % args.out, file=sys.stderr)
            return 1
        args.out.write_text(text, encoding="utf-8")
        print("%d passages written to %s" % (len(entries), args.out))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
