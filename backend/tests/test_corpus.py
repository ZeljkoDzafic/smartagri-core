"""Spec 003 US1: corpus hash (T005) and vocabulary validation at load time (T007)."""
import shutil
from pathlib import Path

import pytest
import yaml

from smartagri import config
from smartagri.retrieval.corpus import corpus_dir, load_corpus, validate_corpus


@pytest.fixture
def corpus_copy(tmp_path):
    for name in ("manifest.yaml", "passages.yaml"):
        shutil.copy(corpus_dir() / name, tmp_path / name)
    return tmp_path


def _edit_passages(path: Path, fn):
    raw = yaml.safe_load((path / "passages.yaml").read_text(encoding="utf-8"))
    fn(raw)
    (path / "passages.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_development_corpus_loads_with_a_64_hex_hash():
    c = load_corpus()
    assert len(c.passages) == 22 and len(c.documents) == 4
    assert len(c.hash) == 64 and int(c.hash, 16) >= 0


def test_hash_is_stable_across_loads_and_yaml_formatting(corpus_copy):
    hashes = {load_corpus().hash for _ in range(10)}
    assert len(hashes) == 1
    _edit_passages(corpus_copy, lambda raw: None)               # re-serialised YAML, same content
    assert load_corpus(corpus_copy).hash == hashes.pop()


def test_hash_changes_with_text_and_with_meta(corpus_copy):
    base = load_corpus(corpus_copy).hash
    _edit_passages(corpus_copy, lambda raw: raw[0].update(text=raw[0]["text"] + " Dopuna."))
    edited_text = load_corpus(corpus_copy).hash
    assert edited_text != base
    _edit_passages(corpus_copy, lambda raw: raw[0]["meta"].update(bbch_max=60))
    assert load_corpus(corpus_copy).hash not in (base, edited_text)


def test_manifest_only_edit_does_not_change_the_hash(corpus_copy):
    base = load_corpus(corpus_copy).hash
    manifest = yaml.safe_load((corpus_copy / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["documents"][0]["url"] = "https://example.org/corrected"
    (corpus_copy / "manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    assert load_corpus(corpus_copy).hash == base


def test_unknown_document_id_raises(corpus_copy):
    _edit_passages(corpus_copy, lambda raw: raw[0].update(document_id="nepostojeci"))
    with pytest.raises(ValueError) as err:
        load_corpus(corpus_copy)
    assert "nepostojeci" in str(err.value)


# ---------------------------------------------------------------- vocabulary (T007)

def test_vocab_matches_the_values_the_code_uses():
    vocab = config.load("vocab")
    assert set(vocab["soil_textures"]) == set(config.load("rules")["soil"]["awc_by_texture_mm_m"])
    from smartagri.core.types import AdviceType
    assert set(vocab["advice_types"]) == {t.value for t in AdviceType} - {"out_of_scope"}
    assert vocab["phenophases"]["flowering_silking"] == {"bbch_min": 61, "bbch_max": 69}


def test_development_corpus_has_no_vocabulary_violations():
    c = load_corpus()
    raw = yaml.safe_load((corpus_dir() / "passages.yaml").read_text(encoding="utf-8"))
    assert validate_corpus(c.documents, raw) == []


@pytest.mark.parametrize("meta, fragment", [
    ({"region_scope": ["balkan"]}, "region_scope value 'balkan'"),
    ({"advice_types": ["pest_control"]}, "advice_types value 'pest_control'"),
    ({"crop": ["wheat"]}, "crop value 'wheat'"),
    ({"soil_scope": ["peat"]}, "soil_scope value 'peat'"),
    ({"source_type": "blog"}, "source_type 'blog'"),
    ({"bbch_min": 70, "bbch_max": 60}, "bbch_min is greater"),
    ({"bbch_max": 120}, "bbch_max must be an integer"),
    ({"rainfed": "yes"}, "rainfed must be true or false"),
    ({"valid_from": "2026-13-01"}, "valid_from is not an ISO date"),
    ({"valid_from": "2027-01-01", "valid_until": "2026-01-01"}, "valid_from is after valid_until"),
    ({"recommends": {"x": 1}}, "recommends must map"),
    ({"phase": "flowering"}, "unknown meta field(s) phase"),
])
def test_vocabulary_violations_stop_loading(corpus_copy, meta, fragment):
    _edit_passages(corpus_copy, lambda raw: raw[0]["meta"].update(meta))
    with pytest.raises(ValueError) as err:
        load_corpus(corpus_copy)
    assert fragment in str(err.value) and "vocab.yaml" in str(err.value)


def test_duplicate_ids_and_bad_document_source_type_are_reported(corpus_copy):
    _edit_passages(corpus_copy, lambda raw: raw.append(dict(raw[0])))
    manifest = yaml.safe_load((corpus_copy / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["documents"][0]["source_type"] = "forum"
    (corpus_copy / "manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError) as err:
        load_corpus(corpus_copy)
    assert "duplicate passage id" in str(err.value) and "source_type 'forum'" in str(err.value)


def test_new_meta_fields_are_accepted(corpus_copy):
    _edit_passages(corpus_copy, lambda raw: raw[0]["meta"].update(
        valid_from="2017-09-07", soil_scope=["loam", "clay_loam"], rainfed=False, claims_numeric=True))
    p = load_corpus(corpus_copy).passages[0]
    assert p.meta.soil_scope == ["loam", "clay_loam"] and p.meta.valid_from == "2017-09-07"
