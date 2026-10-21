"""Spec 003 T017: heading chunker for Markdown, HTML and PDF sources, and transcribed values."""
import pytest
import yaml

from smartagri.retrieval import ingest
from smartagri.retrieval.ingest import chunk_section, n_tokens

DOC = """# Navodnjavanje kukuruza

Uvodni pasus o potrebama za vodom.

## Faza svilanja

Kukuruz je najosetljiviji na sušu u fazi svilanja.

| Faza | Kc |
|---|---|
| svilanje | 1,2 |

Posle tabele sledi tekst.

### Đubrenje i voda

Kratak tekst.

# Drugi deo

Završni pasus.
"""


def test_sections_follow_the_heading_path_and_keep_tables_whole():
    entries = ingest.ingest(DOC, "src")
    paths = [e["heading_path"] for e in entries]
    assert paths[0] == ["Navodnjavanje kukuruza"]
    assert ["Navodnjavanje kukuruza", "Faza svilanja"] in paths
    assert ["Navodnjavanje kukuruza", "Faza svilanja", "Đubrenje i voda"] in paths
    assert paths[-1] == ["Drugi deo"]
    tables = [e["text"] for e in entries if e["text"].startswith("|")]
    assert tables == ["| Faza | Kc |\n|---|---|\n| svilanje | 1,2 |"]
    assert all(e["meta"] == {} and e["verify"] is True and e["document_id"] == "src" for e in entries)
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)) and "src-djubrenje-i-voda-1" in ids


def test_long_sections_are_packed_to_the_token_budget_with_overlap():
    paragraphs = [("text", " ".join("p%dw%d" % (i, j) for j in range(100))) for i in range(10)]   # 1000 tokens
    chunks = chunk_section(paragraphs, max_tokens=350, overlap=40)
    assert len(chunks) >= 3 and all(n_tokens(c) <= 350 for c in chunks)
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.split()[:40] == prev.split()[-40:]            # 40-token overlap
    words = " ".join(t for _, t in paragraphs).split()
    assert set(words) == set(" ".join(chunks).split())         # nothing lost


def test_a_single_overlong_paragraph_is_split_at_sentences():
    para = " ".join("Recenica broj %d ima nekoliko reci." % i for i in range(120))   # 720 tokens
    chunks = chunk_section([("text", para)], max_tokens=350, overlap=40)
    assert len(chunks) >= 3 and all(n_tokens(c) <= 350 for c in chunks)
    assert chunks[0].endswith(".")


def test_tables_are_not_split_or_overlapped():
    table = "\n".join(["| a | b |", "|---|---|"] + ["| %d mm | %d m3/ha |" % (i, i * 10) for i in range(200)])
    chunks = chunk_section([("text", "uvod"), ("table", table), ("text", "kraj")], max_tokens=50, overlap=10)
    assert chunks == ["uvod", table, "kraj"]


def test_cli_writes_yaml_for_manual_completion(tmp_path, capsys):
    src = tmp_path / "izvor.md"
    src.write_text(DOC, encoding="utf-8")
    out = tmp_path / "new.yaml"
    assert ingest.main([str(src), "--document-id", "src", "--out", str(out)]) == 0
    entries = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert entries[0]["id"] == "src-navodnjavanje-kukuruza-1" and entries[0]["meta"] == {}
    assert ingest.main([str(src), "--document-id", "src", "--out", str(out)]) == 1     # no overwrite


# ------------------------------------------------------------------ HTML, PDF, transcribed values

HTML = """<!doctype html><html><head><title>Ignored</title><style>p {color: red}</style></head>
<body><nav><a href="/">Početna</a></nav>
<h1>Navodnjavanje kukuruza</h1>
<p>Uvodni   pasus o <b>potrebama</b> za vodom &amp; zemljištem.</p>
<script>var x = "<p>ne</p>";</script>
<h2>Faza svilanja</h2>
<p>Kukuruz je najosetljiviji na sušu u fazi svilanja.</p>
<table>
  <thead><tr><th>Faza</th><th>Kc (-)</th></tr></thead>
  <tbody><tr><td>svilanje</td><td>1,2</td></tr><tr><td>zrenje</td><td>0,6</td></tr></tbody>
</table>
<h3>Đubrenje i voda</h3><ul><li>Prva stavka.</li><li>Druga stavka.</li></ul>
<h5>Napomena</h5><p>Završni pasus.</p>
</body></html>"""


def test_html_keeps_headings_and_tables_as_markdown():
    md = ingest.html_to_markdown(HTML)
    assert "# Navodnjavanje kukuruza" in md.splitlines() and "## Faza svilanja" in md.splitlines()
    assert "### Đubrenje i voda" in md.splitlines()
    assert "| Faza | Kc (-) |\n|---|---|\n| svilanje | 1,2 |\n| zrenje | 0,6 |" in md
    assert "Ignored" not in md and "color" not in md and "var x" not in md
    assert "Uvodni pasus o potrebama za vodom & zemljištem." in md
    entries = ingest.ingest(md, "src")
    tables = [e for e in entries if e["text"].startswith("|")]
    assert len(tables) == 1 and tables[0]["heading_path"] == ["Navodnjavanje kukuruza", "Faza svilanja"]
    assert any(e["heading_path"][-1:] == ["Đubrenje i voda"] and "- Prva stavka." in e["text"] for e in entries)


def test_html_table_without_th_uses_the_first_row_as_header_and_is_never_split(tmp_path):
    rows = "".join("<tr><td>red %d</td><td>%s</td></tr>" % (i, " ".join(["vrednost"] * 10)) for i in range(60))
    page = "<h2>Tabela</h2><table><tr><td>Naziv</td><td>Opis</td></tr>%s</table><p>%s</p>" % (
        rows, " ".join("rec%d" % i for i in range(500)))
    src = tmp_path / "doc.html"
    src.write_text(page, encoding="utf-8")
    entries = ingest.ingest_file(src, "src", corpus=tmp_path)
    tables = [e["text"] for e in entries if e["text"].startswith("|")]
    assert len(tables) == 1 and n_tokens(tables[0]) > 350                 # whole, even above the budget
    assert tables[0].splitlines()[:2] == ["| Naziv | Opis |", "|---|---|"] and len(tables[0].splitlines()) == 62
    assert all(n_tokens(e["text"]) <= 350 for e in entries if not e["text"].startswith("|"))


def _make_pdf(pages):
    """Tiny text PDF built with pypdf alone (Helvetica, one text line per entry, '' = blank line)."""
    import io
    pypdf = pytest.importorskip("pypdf", reason="pypdf not installed (optional extra `ingest`)")
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    w = pypdf.PdfWriter()
    font = w._add_object(DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                           NameObject("/Subtype"): NameObject("/Type1"),
                                           NameObject("/BaseFont"): NameObject("/Helvetica")}))
    for lines in pages:
        page = w.add_blank_page(612, 792)
        ops = ["BT", "/F1 11 Tf", "14 TL", "72 720 Td"] + ["(%s) Tj T*" % ln if ln else "T*" for ln in lines] + ["ET"]
        stream = DecodedStreamObject()
        stream.set_data("\n".join(ops).encode("latin-1"))
        page[NameObject("/Contents")] = w._add_object(stream)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_pdf_is_split_per_page_into_paragraph_passages_with_page_numbers(tmp_path):
    long_par = ["Recenica broj %d ima nekoliko reci o vodi." % i for i in range(60)]     # ~480 tokens
    data = _make_pdf([["Prvi pasus prvi red", "nastavak prvog pasusa.", "", "Drugi pasus na prvoj strani."],
                      long_par])
    src = tmp_path / "doc.pdf"
    src.write_bytes(data)
    entries = ingest.ingest_file(src, "src", corpus=tmp_path)
    first = [e for e in entries if e["source_ref"] == "p. 1"]
    second = [e for e in entries if e["source_ref"] == "p. 2"]
    assert first and second and len(first) + len(second) == len(entries)
    assert first[0]["text"] == "Prvi pasus prvi red nastavak prvog pasusa.\n\nDrugi pasus na prvoj strani."
    assert len(second) >= 2 and all(n_tokens(e["text"]) <= 350 for e in second)
    assert [e["id"] for e in first] == ["src-p1-1"] and second[0]["id"] == "src-p2-1"
    assert all(e["verify"] is True and e["meta"] == {} for e in entries)


def test_transcribed_values_are_appended_and_marked(tmp_path):
    (tmp_path / "transcribed").mkdir()
    (tmp_path / "transcribed" / "src.md").write_text(
        "## Slika 3: Kc kukuruza\n\n| Faza | Kc |\n|---|---|\n| svilanje | 1,2 |\n", encoding="utf-8")
    src = tmp_path / "doc.md"
    src.write_text(DOC, encoding="utf-8")
    entries = ingest.ingest_file(src, "src", corpus=tmp_path)
    marked = [e for e in entries if e.get("transcribed")]
    assert len(marked) == 1 and entries[-1] is marked[0]
    assert marked[0]["source_ref"] == "transcribed/src.md" and marked[0]["text"].startswith("| Faza | Kc |")
    assert marked[0]["id"] == "src-transkript-slika-3-kc-kukuruza-1" and marked[0]["document_id"] == "src"
    assert len({e["id"] for e in entries}) == len(entries)
    assert not any(e.get("transcribed") for e in ingest.ingest_file(src, "other", corpus=tmp_path))


def test_cli_accepts_html_and_rejects_unknown_types(tmp_path, capsys):
    src = tmp_path / "doc.html"
    src.write_text(HTML, encoding="utf-8")
    assert ingest.main([str(src), "--document-id", "src", "--corpus-dir", str(tmp_path)]) == 0
    out = yaml.safe_load(capsys.readouterr().out)
    assert any(e["text"].startswith("| Faza |") for e in out)
    bad = tmp_path / "doc.docx"
    bad.write_text("x", encoding="utf-8")
    assert ingest.main([str(bad), "--document-id", "src", "--corpus-dir", str(tmp_path)]) == 2
