"""Parcel features: the data contract, the causality rule, the geometry and producer hashes, the provider, the NDVI quality
rules and the stage-conflict rule of q, and the consumer side of the crop and field-marker checks (switched off).

Fixtures are synthetic documents of an "example-producer"; no real indicator and no scenario of the test set is used."""
import copy
import json
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from conftest import make_context
from smartagri.config import load_variants
from smartagri.core import parcel_features as pfm
from smartagri.core.applicability import applicability
from smartagri.core.decide import decide
from smartagri.core.quality import annotate_quality, observe_all
from smartagri.core.tools import ndvi_summary
from smartagri.core.types import (Applicability, AdviceType, Context, NdviObservation, Passage, PassageMeta,
                                  Reliability, SatelliteSummary)
from smartagri.pipeline.run import ablate_context
from smartagri.providers import parcel_features as provider
from smartagri.providers.base import ProviderUnavailable

SQUARE = {"type": "Polygon", "coordinates": [[[17.300, 44.900], [17.302, 44.900], [17.302, 44.902], [17.300, 44.902],
                                              [17.300, 44.900]]]}
AS_OF = "2026-07-12T06:00:00"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "parcel_features"


def doc(**over):
    """A valid document for the parcel 't' (make_context) at 2026-07-12 06:00, with a stage interval BBCH 60-69
    (the context's reported stage is BBCH 61, so the sources agree). Keyword arguments replace top-level blocks."""
    d = {
        "schema_version": 1, "parcel_id": "t", "geometry_sha256": pfm.geometry_sha256(SQUARE), "as_of": AS_OF,
        "computed_at": "2026-07-12T07:30:00", "source_obs_dates": ["2026-07-04", "2026-07-09"],
        "producer": {"name": "example-producer", "version": "1.0.0", "commit": "abc1234", "config_sha256": "a" * 64,
                     "model_sha256": None, "run_manifest_sha256": "b" * 64, "data_access": "stac-cog"},
        "ndvi_observations": [
            {"obs_date": "2026-07-04", "median": 0.71, "p10": 0.62, "p90": 0.80, "usable_share": 0.90,
             "n_px_total": 60, "n_px_interior": 44, "n_px_valid": 40, "interior_buffer_m": 10.0,
             "mixed_px_share": 0.27, "cloud_px_share": 0.05, "shadow_px_share": 0.02, "cloud_flag": False,
             "temporal_outlier": False, "mask_layers": ["scl", "dilation_2px"]},
            {"obs_date": "2026-07-09", "median": 0.74, "p10": 0.66, "p90": 0.81, "usable_share": 0.95,
             "n_px_total": 60, "n_px_interior": 44, "n_px_valid": 42, "interior_buffer_m": 10.0,
             "mixed_px_share": 0.27, "cloud_px_share": 0.0, "shadow_px_share": 0.0, "cloud_flag": False,
             "temporal_outlier": False, "mask_layers": ["scl", "dilation_2px"]}],
        "stage_estimate": {"method": "example_causal_v1", "status": "estimated", "bbch_min": 60, "bbch_max": 69,
                           "greenup_date": "2026-05-06", "greenup_date_ci_days": [-3, 4],
                           "last_clear_obs_date": "2026-07-09", "n_clear_obs": 9, "longest_gap_days": 10.0},
        "crop_plausibility": {"season_year": 2026, "cutoff_doy": 190, "p_maize": 0.93, "prediction_set": ["maize"],
                              "alpha": 0.1, "coverage_guarantee": False, "aoa_fraction": 0.97, "n_px_interior": 44,
                              "decision": "agreement", "transfer_validated": False, "training_overlap_m": 1200.0},
        "events": {"data_sufficiency": "s2", "bare_soil_now": False, "bare_soil_since": None, "harvest_detected": False,
                   "harvest_date": None, "harvest_evidence": "", "confidence": 0.7, "greenup_date": "2026-05-06"},
    }
    d.update(over)
    if d.get("ndvi_observations") is None:        # an absent block, never a null
        d.pop("ndvi_observations", None)
    return d


def no_ndvi(d):
    """The document without its NDVI observations: nothing is added to the NDVI series of the context."""
    d = dict(d)
    d.pop("ndvi_observations", None)
    return d


def ctx_with(features=None, **kw):
    c = make_context(**kw)
    d = c.to_dict()
    d["S"]["parcel_features"] = features
    return Context.from_dict(d)


def stage(lo, hi, **kw):
    s = dict(doc()["stage_estimate"], bbch_min=lo, bbch_max=hi)
    s.update(kw)
    return doc(stage_estimate=s)


@pytest.fixture
def cfg(monkeypatch):
    """The parcel_features config, editable per test: cfg(section, key=value, ...)."""
    data = copy.deepcopy(pfm.settings())
    monkeypatch.setattr(pfm, "settings", lambda: data)

    def set_(section, **values):
        data[section].update(values)
    return set_


def rel(ctx, name, aware=True):
    return annotate_quality(ctx, aware)[name].reliability


# ================================================================ the contract

def test_a_valid_document_passes_and_the_example_fixture_matches_it():
    assert pfm.validate(doc(), as_of=AS_OF, parcel_id="t", geometry=SQUARE) == []
    example = json.loads((FIXTURES / "example_producer_full.json").read_text(encoding="utf-8"))
    assert pfm.validate(example, as_of=AS_OF, parcel_id="t", geometry=SQUARE) == []
    assert example == doc()                      # the documented example is the test document


@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d.update(schema_version=2), "schema_version"),
    (lambda d: d.update(extra=1), "unknown field 'extra'"),
    (lambda d: d.pop("producer"), "missing required field 'producer'"),
    (lambda d: d["producer"].update(config_sha256="xyz"), "producer.config_sha256"),
    (lambda d: d["producer"].update(commit="NOTHEX"), "producer.commit"),
    (lambda d: d["producer"].update(data_access="ftp"), "producer.data_access"),
    (lambda d: d["ndvi_observations"][0].update(usable_share=1.2), "above 1"),
    (lambda d: d["ndvi_observations"][0].update(cloud_flag="yes"), "cloud_flag"),
    (lambda d: d["ndvi_observations"][0].update(median=True), "median"),
    (lambda d: d["ndvi_observations"][0].update(n_px_valid=99), "n_px_valid exceeds n_px_interior"),
    (lambda d: d["ndvi_observations"][0].update(p10=0.9), "p10 is above p90"),
    (lambda d: d["ndvi_observations"][0].update(obs_date="2026-07-01"), "not listed in source_obs_dates"),
    (lambda d: d["ndvi_observations"].append(dict(d["ndvi_observations"][0])), "appears twice"),
    (lambda d: d["stage_estimate"].update(bbch_min=70), "bbch_min is above bbch_max"),
    (lambda d: d["stage_estimate"].update(bbch_max=None), "bbch"),
    (lambda d: d["stage_estimate"].pop("bbch_min"), "bbch_min and bbch_max come together"),
    (lambda d: d["stage_estimate"].update(status="guess"), "stage_estimate.status"),
    (lambda d: d["stage_estimate"].pop("last_clear_obs_date"), "needs last_clear_obs_date"),
    (lambda d: d["stage_estimate"].update(greenup_date_ci_days=[4, -3]), "lower bound above upper bound"),
    (lambda d: d["crop_plausibility"].update(prediction_set=["maize", "maize"]), "unique"),
    (lambda d: d["crop_plausibility"].update(decision="maybe"), "crop_plausibility.decision"),
    (lambda d: d["events"].update(data_sufficiency="all"), "events.data_sufficiency"),
    (lambda d: (d["events"].update(harvest_detected=True), d["events"].pop("confidence")), "harvest_detected needs confidence"),
    (lambda d: d.update(as_of="yesterday"), "as_of"),
    (lambda d: d.update(source_obs_dates=["2026-13-40"]), "document"),
])
def test_a_document_that_breaks_the_contract_is_rejected_with_the_reason(mutate, fragment):
    d = copy.deepcopy(doc())
    mutate(d)
    errors = pfm.validate(d, as_of=AS_OF)
    assert errors and any(fragment in e for e in errors), errors
    with pytest.raises(pfm.ParcelFeaturesError):
        pfm.parse(d, as_of=AS_OF)


def test_blocks_are_optional_and_a_document_may_carry_only_the_required_part():
    minimal = {k: doc()[k] for k in ("schema_version", "parcel_id", "geometry_sha256", "as_of", "computed_at",
                                      "source_obs_dates", "producer")}
    pf = pfm.parse(minimal, as_of=AS_OF)
    assert pf.stage_estimate is None and pf.ndvi_observations == [] and pf.document_sha256
    assert pfm.validate(doc(stage_estimate=None, crop_plausibility=None, events=None), as_of=AS_OF) == []


def test_the_schema_in_code_is_a_json_schema_that_names_the_contract():
    schema = json.loads(json.dumps(pfm.SCHEMA))                   # plain JSON, as published in docs/parcel-features.md
    assert schema["properties"]["schema_version"] == {"const": 1}
    assert set(schema["required"]) == {"schema_version", "parcel_id", "geometry_sha256", "as_of", "computed_at",
                                       "source_obs_dates", "producer"}
    assert set(schema["properties"]) == set(doc())                # every block of a full document is described
    assert schema["additionalProperties"] is False
    # the typed record carries exactly the contract's fields (plus the document hash it computes)
    from smartagri.core.types import ParcelFeatures
    assert set(ParcelFeatures.__dataclass_fields__) - {"document_sha256"} == set(schema["properties"])


def test_the_published_schema_and_example_match_the_code():
    """docs/parcel-features.md exists in the open-core export (the overlay), not in the private working copy."""
    page = Path(__file__).resolve().parents[2] / "docs" / "parcel-features.md"
    if not page.is_file():
        pytest.skip("docs/parcel-features.md is part of the open-core export")
    text = page.read_text(encoding="utf-8")
    assert json.dumps(pfm.SCHEMA, indent=2, ensure_ascii=False) in text
    assert json.dumps(doc(), indent=2, ensure_ascii=False) in text


# ================================================================ units, intervals, sets

def test_uncertainty_is_carried_as_an_interval_a_set_and_sufficiency_not_as_a_point():
    pf = pfm.parse(doc(), as_of=AS_OF)
    se = pf.stage_estimate
    assert (se["bbch_min"], se["bbch_max"]) == (60, 69) and "bbch" not in se          # an interval, no point value
    assert pf.crop_plausibility["prediction_set"] == ["maize"] and pf.crop_plausibility["coverage_guarantee"] is False
    assert se["n_clear_obs"] == 9 and se["longest_gap_days"] == 10.0 and pf.events["data_sufficiency"] == "s2"
    assert pfm.validate(stage(0, 120), as_of=AS_OF)                                   # BBCH units: 0..99
    assert pfm.validate(doc(crop_plausibility=dict(doc()["crop_plausibility"], p_maize=1.5)), as_of=AS_OF)  # share
    assert pfm.validate(doc(crop_plausibility=dict(doc()["crop_plausibility"], alpha=0)), as_of=AS_OF)       # (0, 1]


# ================================================================ only what was observed before the decision

def test_an_observation_after_the_decision_moment_is_rejected_everywhere_it_can_appear():
    def bad(**kw):
        d = copy.deepcopy(doc())
        for path, value in kw.items():
            node = d
            *head, last = path.split("__")
            for k in head:
                node = node[int(k)] if k.isdigit() else node[k]
            node[last] = value
        return pfm.validate(d, as_of=AS_OF)
    assert any("source_obs_dates" in e for e in bad(source_obs_dates=["2026-07-04", "2026-07-13"]))
    assert any("source_obs_dates" in e and "after" in e for e in bad(source_obs_dates=["2026-07-04", "2026-07-12"]))  # a date alone: the whole day
    assert any("ndvi_observations[1].obs_date" in e for e in bad(ndvi_observations__1__obs_date="2026-07-13"))
    assert any("last_clear_obs_date" in e for e in bad(stage_estimate__last_clear_obs_date="2026-07-20"))
    assert any("greenup_date" in e for e in bad(stage_estimate__greenup_date="2026-07-15"))
    assert any("bare_soil_since" in e for e in bad(events__bare_soil_since="2026-07-13"))
    assert any("harvest_date" in e for e in bad(events__harvest_date="2026-08-01"))
    assert any("feature window" in e for e in bad(crop_plausibility__cutoff_doy=250))         # window ends after the decision
    assert not bad(crop_plausibility__cutoff_doy=190)                                           # DOY 190 = 9 July


def test_an_observation_on_the_decision_day_counts_only_with_a_time_at_or_before_the_decision_moment():
    same_day = ["2026-07-04", "2026-07-09", "2026-07-12"]
    assert pfm.validate(doc(source_obs_dates=same_day), as_of=AS_OF)                          # a date alone: end of day
    early = ["2026-07-04", "2026-07-09", "2026-07-12T05:30:00"]
    assert pfm.validate(doc(source_obs_dates=early, ndvi_observations=None), as_of=AS_OF) == []
    late = ["2026-07-04", "2026-07-09", "2026-07-12T10:30:00"]
    assert any("after" in e for e in pfm.validate(doc(source_obs_dates=late, ndvi_observations=None), as_of=AS_OF))
    assert pfm.moment("2026-07-11") < pfm.as_of_moment(AS_OF) and pfm.moment("2026-07-12") > pfm.as_of_moment(AS_OF)


def test_the_document_must_be_computed_for_the_same_day_at_or_before_the_decision_moment():
    assert any("as_of" in e for e in pfm.validate(doc(as_of="2026-07-12T09:00:00"), as_of=AS_OF))   # a later moment
    assert any("as_of" in e for e in pfm.validate(doc(as_of="2026-07-11T06:00:00"), as_of=AS_OF))   # another day
    assert pfm.validate(doc(as_of="2026-07-12T05:00:00"), as_of=AS_OF) == []                       # earlier, same day
    assert any("computed_at" in e for e in pfm.validate(doc(computed_at="2026-07-08T00:00:00"), as_of=AS_OF))
    # an offset in the document does not move the wall-clock comparison; a datetime object (YAML) works as a string
    assert pfm.validate(doc(as_of="2026-07-12T06:00:00+02:00"), as_of=datetime(2026, 7, 12, 6, 0)) == []
    assert pfm.validate(doc(as_of="2026-07-12T06:00:00Z", source_obs_dates=[date(2026, 7, 4), date(2026, 7, 9)],
                            ndvi_observations=None), as_of=AS_OF) == []


def test_a_scenario_file_with_a_late_observation_fails_loudly_not_silently():
    with pytest.raises(pfm.ParcelFeaturesError, match="after the decision moment"):
        ctx_with(doc(source_obs_dates=["2026-07-04", "2026-07-13"], ndvi_observations=None))


def test_a_context_assembled_by_hand_with_a_late_document_ignores_it_and_records_the_rejection():
    ctx = make_context()
    late = pfm.parse(doc(), as_of=AS_OF)
    late.source_obs_dates = ["2026-07-30"]                        # tampered after parsing
    ctx.S.parcel_features = late
    assert pfm.usable(ctx)[0] is None and pfm.usable(ctx)[1]
    assert annotate_quality(ctx)["phenophase"].detail is None      # no effect on q
    q = annotate_quality(ctx)
    assert pfm.provenance(ctx, q)["rejected"]


# ================================================================ hashes: geometry, producer, document

def test_the_geometry_hash_does_not_depend_on_how_the_ring_is_written():
    base = pfm.geometry_sha256(SQUARE)
    ring = SQUARE["coordinates"][0]
    rotated = {"type": "Polygon", "coordinates": [ring[2:-1] + ring[:2] + [ring[2]]]}
    reversed_ = {"type": "Polygon", "coordinates": [list(reversed(ring))]}
    unclosed = {"type": "Polygon", "coordinates": [ring[:-1]]}
    precise = {"type": "Polygon", "coordinates": [[[x + 1e-9, y - 1e-9] for x, y in ring]]}
    altitude = {"type": "Polygon", "coordinates": [[[x, y, 120.0] for x, y in ring]]}
    feature = {"type": "Feature", "properties": {"name": "x"}, "geometry": SQUARE}
    multi = {"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"]]}
    for g in (rotated, reversed_, unclosed, precise, altitude, feature, multi):
        assert pfm.geometry_sha256(g) == base
    moved = {"type": "Polygon", "coordinates": [[[x + 1e-5, y] for x, y in ring]]}
    assert pfm.geometry_sha256(moved) != base
    assert len(base) == 64 and set(base) <= set("0123456789abcdef")


def test_a_hole_changes_the_hash_and_a_bad_geometry_is_refused():
    hole = [[17.3005, 44.9005], [17.3005, 44.9010], [17.3010, 44.9010], [17.3010, 44.9005], [17.3005, 44.9005]]
    holed = {"type": "Polygon", "coordinates": SQUARE["coordinates"] + [hole]}
    assert pfm.geometry_sha256(holed) != pfm.geometry_sha256(SQUARE)
    with pytest.raises(ValueError):
        pfm.geometry_sha256({"type": "Point", "coordinates": [17.3, 44.9]})
    with pytest.raises(ValueError):
        pfm.geometry_sha256({"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 0]]]})


def test_a_document_for_another_geometry_or_parcel_is_rejected():
    other = {"type": "Polygon", "coordinates": [[[17.4, 44.9], [17.402, 44.9], [17.402, 44.902], [17.4, 44.9]]]}
    assert any("geometry_sha256" in e for e in pfm.validate(doc(), as_of=AS_OF, geometry=other))
    assert any("parcel_id" in e for e in pfm.validate(doc(), as_of=AS_OF, parcel_id="someone-else"))
    assert pfm.validate(doc(), as_of=AS_OF, parcel_id="t", geometry=SQUARE) == []


def test_the_document_hash_is_the_same_for_json_and_yaml_forms_and_changes_with_content():
    d = doc()
    yaml_form = yaml.safe_load(yaml.safe_dump(d, sort_keys=False).replace("'2026-07-04'", "2026-07-04"))
    assert isinstance(yaml_form["source_obs_dates"][0], date)     # YAML turned a quoted-less date into a date object
    assert pfm.document_sha256(yaml_form) == pfm.document_sha256(d)
    shuffled = dict(reversed(list(d.items())))
    assert pfm.document_sha256(shuffled) == pfm.document_sha256(d)
    changed = doc(stage_estimate=dict(d["stage_estimate"], bbch_max=70))
    assert pfm.document_sha256(changed) != pfm.document_sha256(d)
    assert pfm.parse(d, as_of=AS_OF).document_sha256 == pfm.document_sha256(d)
    assert pfm.parse(yaml_form, as_of=AS_OF).document_sha256 == pfm.document_sha256(d)


def test_producer_hashes_and_commit_travel_with_the_document_into_the_provenance():
    ctx = ctx_with(doc())
    block = pfm.provenance(ctx, annotate_quality(ctx))
    assert block["producer"] == doc()["producer"] and block["geometry_sha256"] == pfm.geometry_sha256(SQUARE)
    assert block["document_sha256"] == pfm.document_sha256(doc()) and block["schema_version"] == 1
    assert block["producer"]["config_sha256"] == "a" * 64 and block["producer"]["run_manifest_sha256"] == "b" * 64


# ================================================================ the features live inside S

def test_the_features_are_part_of_the_satellite_context_and_a_scenario_file_carries_them():
    ctx = ctx_with(doc())
    assert ctx.S.parcel_features is not None and ctx.S.parcel_features.parcel_id == "t"
    assert "parcel_features" in SatelliteSummary.__dataclass_fields__
    for name in ("P", "A", "W", "Q"):
        assert not hasattr(getattr(ctx, name), "parcel_features")
    assert [o.obs_date for o in ctx.S.ndvi_series] == ["2026-07-04", "2026-07-09"]       # merged from the document


def test_the_satellite_ablation_removes_the_features_and_everything_they_do():
    ctx = ctx_with(stage(10, 19))                                    # a conflict with the reported BBCH 61
    variants = load_variants()
    assert rel(ctx, "phenophase") == Reliability.LOW
    ablated = ablate_context(ctx, variants["V5-satellite"])
    assert ablated.S.parcel_features is None and ablated.S.ndvi_series == []
    assert rel(ablated, "phenophase") == Reliability.HIGH
    assert ablate_context(ctx, variants["V0"]).S.parcel_features is None           # below the dynamic context too
    assert pfm.provenance(ablated, annotate_quality(ablated)) is None
    assert ablate_context(ctx, variants["V5-weather"]).S.parcel_features is not None


def test_scenarios_without_the_block_are_unchanged():
    with_none = ctx_with(None)
    plain = make_context()
    assert with_none.S.parcel_features is None
    assert annotate_quality(with_none) == annotate_quality(plain)
    assert [o.reliability for o in annotate_quality(plain).values()]       # sanity


# ================================================================ the provider (offline file) and the profile

def _write(directory, parcel_id, as_of_day, document):
    path = provider.FileProvider(directory).path_for(parcel_id, datetime.fromisoformat(as_of_day))
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_the_file_provider_loads_a_checked_document(tmp_path):
    _write(tmp_path, "t", "2026-07-12", doc())
    prov = provider.FileProvider(tmp_path)
    got = provider.load("t", SQUARE, datetime.fromisoformat(AS_OF), prov)
    assert got is not None and got.producer["name"] == "example-producer"
    assert provider.load("t", SQUARE, datetime(2026, 7, 13, 6), prov) is None            # no file for that day
    assert provider.load("other", SQUARE, datetime.fromisoformat(AS_OF), prov) is None


def test_the_provider_rejects_a_document_that_cannot_be_used_and_says_why(tmp_path):
    prov = provider.FileProvider(tmp_path)
    when = datetime.fromisoformat(AS_OF)
    _write(tmp_path, "t", "2026-07-12", doc(source_obs_dates=["2026-07-04", "2026-07-14"], ndvi_observations=None))
    with pytest.raises(ProviderUnavailable, match="after the decision moment"):
        provider.load("t", SQUARE, when, prov)
    _write(tmp_path, "t", "2026-07-12", doc(geometry_sha256="0" * 64))
    with pytest.raises(ProviderUnavailable, match="geometry_sha256"):
        provider.load("t", SQUARE, when, prov)
    _write(tmp_path, "t", "2026-07-12", doc(schema_version=7))
    with pytest.raises(ProviderUnavailable, match="schema_version"):
        provider.load("t", SQUARE, when, prov)
    provider.FileProvider(tmp_path).path_for("t", when).write_text("{not json", encoding="utf-8")
    with pytest.raises(ProviderUnavailable, match="se ne može pročitati"):
        provider.load("t", SQUARE, when, prov)


def test_the_provider_is_configured_by_a_generic_environment_variable(monkeypatch, tmp_path):
    monkeypatch.delenv(provider.ENV_DIR, raising=False)
    assert provider.ENV_DIR == "SMARTAGRI_PARCEL_FEATURES_DIR" and not provider.configured()
    assert provider.load("t", SQUARE, datetime.fromisoformat(AS_OF)) is None
    monkeypatch.setenv(provider.ENV_DIR, str(tmp_path))
    _write(tmp_path, "t", "2026-07-12", doc())
    assert provider.configured() and provider.load("t", SQUARE, datetime.fromisoformat(AS_OF)) is not None


def _parcel():
    return {"id": "t", "area_ha": 2.1, "centroid": {"lat": 44.9, "lon": 17.3}, "region_class": "pannonian",
            "geometry": SQUARE, "agronomic": {"sowing_date": "2026-04-25", "bbch": 61, "bbch_reported_on": "2026-07-11"}}


def test_a_profile_stores_the_document_and_its_hashes_and_feeds_the_context(monkeypatch, tmp_path, store):
    from smartagri.pipeline.profile import build_profile, context_from, quality_rows
    monkeypatch.setenv(provider.ENV_DIR, str(tmp_path))
    monkeypatch.setenv("SMARTAGRI_OFFLINE", "1")
    _write(tmp_path, "t", "2026-07-12", stage(10, 19))
    profile = build_profile(store, _parcel(), as_of=datetime.fromisoformat(AS_OF))
    stored = profile["parcel_features"]
    assert stored["status"] == "ok" and stored["document_sha256"] == pfm.document_sha256(stage(10, 19))
    assert profile["provenance"]["parcel_features_sha256"] == stored["document_sha256"]
    assert profile["provenance"]["parcel_features_producer"]["name"] == "example-producer"
    ctx = context_from(_parcel(), profile)
    assert ctx.S.parcel_features is not None and ctx.S.parcel_features.document_sha256 == stored["document_sha256"]
    row = next(r for r in profile["quality"] if r["input"] == "phenophase")
    assert row["reliability"] == "low" and row["detail"]["conflicts"][0]["rule"] == "stage_conflict"
    assert {r["input"]: r for r in quality_rows(ctx)}["phenophase"]["detail"]["conflicts"]


def test_a_rejected_document_is_recorded_and_the_profile_still_builds(monkeypatch, tmp_path, store):
    from smartagri.pipeline.profile import build_profile, context_from
    monkeypatch.setenv(provider.ENV_DIR, str(tmp_path))
    monkeypatch.setenv("SMARTAGRI_OFFLINE", "1")
    _write(tmp_path, "t", "2026-07-12", doc(geometry_sha256="f" * 64))
    profile = build_profile(store, _parcel(), as_of=datetime.fromisoformat(AS_OF))
    assert profile["parcel_features"]["status"] == "rejected" and "geometry_sha256" in profile["parcel_features"]["message"]
    assert profile["provenance"]["parcel_features_status"] == "rejected"
    assert context_from(_parcel(), profile).S.parcel_features is None
    next(r for r in profile["quality"] if r["input"] == "phenophase")["reliability"] == "high"


def test_without_a_configured_provider_a_profile_has_nothing_new(monkeypatch, store):
    from smartagri.pipeline.profile import build_profile
    monkeypatch.delenv(provider.ENV_DIR, raising=False)
    monkeypatch.setenv("SMARTAGRI_OFFLINE", "1")
    profile = build_profile(store, _parcel(), as_of=datetime.fromisoformat(AS_OF))
    assert "parcel_features" not in profile and not any(k.startswith("parcel_features") for k in profile["provenance"])


# ================================================================ NDVI quality metadata in q

def obs(date_, share=0.95, **kw):
    return dict(obs_date=date_, median=0.7, p10=0.6, p90=0.8, usable_share=share, **kw)


def test_an_observation_without_the_new_fields_is_graded_exactly_as_before():
    plain = make_context(ndvi=[obs("2026-07-09")])
    assert rel(plain, "ndvi_latest") == Reliability.HIGH
    q = annotate_quality(plain)["ndvi_latest"]
    assert q.detail is None and "capped" not in q.basis
    assert NdviObservation(obs_date="x").cloud_flag is None and NdviObservation(obs_date="x").mask_layers is None


def test_cloud_flag_is_stored_and_it_lowers_the_grade_to_at_most_medium():
    flagged = make_context(ndvi=[obs("2026-07-09", cloud_flag=True)])
    q = annotate_quality(flagged)["ndvi_latest"]
    assert q.reliability == Reliability.MEDIUM and "cloud_flag" in q.basis and q.detail["cloud_flag"] is True
    assert q.detail["capped_by"] and annotate_quality(flagged)["ndvi_spatial_contrast"].reliability == Reliability.MEDIUM
    clean = make_context(ndvi=[obs("2026-07-09", cloud_flag=False)])
    assert rel(clean, "ndvi_latest") == Reliability.HIGH and annotate_quality(clean)["ndvi_latest"].detail["cloud_flag"] is False
    assert nd_value(flagged) == nd_value(clean) == 0.7                                       # the value is not touched


def nd_value(ctx):
    return observe_all(ctx)["ndvi_latest"].value


@pytest.mark.parametrize("fields, expected", [
    ({"cloud_px_share": 0.10, "shadow_px_share": 0.05}, Reliability.HIGH),
    ({"cloud_px_share": 0.15, "shadow_px_share": 0.10}, Reliability.MEDIUM),         # masked 0.25 > 0.20
    ({"cloud_px_share": 0.40, "shadow_px_share": 0.15}, Reliability.LOW),            # masked 0.55 > 0.50
    ({"shadow_px_share": 0.30}, Reliability.MEDIUM),
    ({"mixed_px_share": 0.25}, Reliability.HIGH),
    ({"mixed_px_share": 0.35}, Reliability.MEDIUM),
    ({"mixed_px_share": 0.70}, Reliability.LOW),
    ({"n_px_interior": 44}, Reliability.HIGH),
    ({"n_px_interior": 20}, Reliability.MEDIUM),
    ({"n_px_interior": 6}, Reliability.LOW),
    ({"n_px_interior": 60, "n_px_valid": 8}, Reliability.LOW),                       # valid interior pixels decide
    ({"interior_buffer_m": 10.0, "mask_layers": ["scl"]}, Reliability.HIGH),         # recorded, no rule
    ({"cloud_flag": True, "mixed_px_share": 0.70}, Reliability.LOW),                 # the lowest cap wins
])
def test_ndvi_quality_thresholds_cap_the_grade(fields, expected):
    ctx = make_context(ndvi=[obs("2026-07-09", **fields)])
    assert rel(ctx, "ndvi_latest") == expected


def test_quality_fields_never_raise_a_grade():
    old_low = make_context(ndvi=[obs("2026-07-03", share=0.55, cloud_flag=False, cloud_px_share=0.0, n_px_interior=90)])
    assert rel(old_low, "ndvi_latest") == Reliability.LOW                      # clean metadata does not lift a low grade
    plain = make_context(ndvi=[obs("2026-07-03", share=0.55)])
    assert rel(plain, "ndvi_latest") == Reliability.LOW
    for fields in ({}, {"cloud_flag": True}, {"cloud_px_share": 0.3}, {"mixed_px_share": 0.5}, {"n_px_interior": 8}):
        with_f = annotate_quality(make_context(ndvi=[obs("2026-07-09", **fields)]))["ndvi_latest"].reliability.rank
        without = annotate_quality(make_context(ndvi=[obs("2026-07-09")]))["ndvi_latest"].reliability.rank
        assert with_f <= without


def test_the_quality_rules_are_off_by_a_switch_and_for_variants_without_q(cfg):
    ctx = make_context(ndvi=[obs("2026-07-09", cloud_flag=True)])
    assert rel(ctx, "ndvi_latest", aware=False) == Reliability.UNGRADED
    cfg("ndvi_quality", enabled=False)
    assert rel(ctx, "ndvi_latest") == Reliability.HIGH


def test_a_temporal_outlier_is_left_out_of_the_summary_and_named(cfg):
    series = [NdviObservation(**obs("2026-07-01", share=0.9)), NdviObservation(**obs("2026-07-06", share=0.9)),
              NdviObservation(**dict(obs("2026-07-09", share=0.95), median=0.2, temporal_outlier=True))]
    out = ndvi_summary(series, date(2026, 7, 12)).output
    assert out["latest_date"] == "2026-07-06" and out["outliers_excluded"] == ["2026-07-09"]
    assert out["trend_count"] == 2
    ctx = make_context(ndvi=[dict(obs("2026-07-06")), dict(obs("2026-07-09"), median=0.2, temporal_outlier=True)])
    q = annotate_quality(ctx)["ndvi_latest"]
    assert nd_value(ctx) == 0.7 and q.detail["outliers_excluded"] == ["2026-07-09"] and q.age_days == 6
    cfg("ndvi_quality", exclude_temporal_outliers=False)
    assert ndvi_summary(series, date(2026, 7, 12)).output["latest_date"] == "2026-07-09"
    plain = ndvi_summary([NdviObservation(**obs("2026-07-06"))], date(2026, 7, 12)).output
    assert "quality" not in plain and "outliers_excluded" not in plain


def test_the_document_observations_replace_the_series_entry_of_the_same_date_and_add_new_dates():
    base = [obs("2026-07-04", share=0.50), obs("2026-06-20")]
    ctx = ctx_with(doc(), ndvi=base)
    by_day = {o.obs_date: o for o in ctx.S.ndvi_series}
    assert sorted(by_day) == ["2026-06-20", "2026-07-04", "2026-07-09"]
    assert by_day["2026-07-04"].usable_share == 0.90 and by_day["2026-07-04"].n_px_interior == 44
    assert by_day["2026-06-20"].n_px_interior is None


def test_ndvi_quality_never_raises_the_sufficiency_when_the_masked_share_grows():
    from smartagri.core.sufficiency import sufficiency
    ranks = []
    for masked in (0.0, 0.1, 0.25, 0.45, 0.6, 0.9):
        ctx = make_context(advice_type=AdviceType.SCOUTING, ndvi=[obs("2026-07-09", cloud_px_share=masked)])
        ranks.append(sufficiency(AdviceType.SCOUTING, annotate_quality(ctx)).status.rank)
    assert ranks == sorted(ranks, reverse=True)


# ================================================================ the stage-conflict rule

def test_sources_that_agree_within_the_tolerance_change_nothing(cfg):
    plain = annotate_quality(make_context())
    agree = annotate_quality(ctx_with(stage(60, 69)))
    assert agree["phenophase"].reliability == plain["phenophase"].reliability == Reliability.HIGH
    assert agree["phenophase"].detail is None
    inside_tol = annotate_quality(ctx_with(stage(40, 51)))["phenophase"]          # 61 is 10 above 51: on the limit
    assert inside_tol.reliability == Reliability.HIGH and inside_tol.detail is None
    just_outside = annotate_quality(ctx_with(stage(40, 50)))["phenophase"]        # 11 above
    assert just_outside.reliability == Reliability.LOW
    below = annotate_quality(ctx_with(stage(72, 80)))["phenophase"]               # 61 is 11 below 72
    assert below.reliability == Reliability.LOW
    cfg("stage_conflict", tolerance_bbch=20)
    assert rel(ctx_with(stage(40, 50)), "phenophase") == Reliability.HIGH


def test_a_conflict_caps_the_stage_reliability_at_low_and_is_recorded():
    ctx = ctx_with(stage(10, 19))
    q = annotate_quality(ctx)["phenophase"]
    assert q.reliability == Reliability.LOW and q.origin.value == "user_reported" and q.age_days == 1.0
    assert "capped to low" in q.basis and "stage_conflict" in q.basis
    c = q.detail["conflicts"][0]
    assert c["in_use"]["bbch"] == 61 and c["in_use"]["origin"] == "user_reported"
    assert (c["satellite"]["bbch_min"], c["satellite"]["bbch_max"]) == (10, 19) and c["tolerance_bbch"] == 10
    assert c["distance_bbch"] == 42.0 and c["satellite"]["age_days"] == 3
    d = decide(ctx, [], load_variants()["V4"])
    assert d.input_conflicts == [c] and d.quality["phenophase"].reliability == Reliability.LOW
    assert d.quality["phenophase"].to_dict()["detail"]["conflicts"][0]["rule"] == "stage_conflict"


def test_the_stage_in_use_may_be_the_estimate_from_the_sowing_date():
    ctx = ctx_with(stage(5, 12), agronomic={"bbch": None})                     # sown 78 days ago: BBCH well above 12
    o = observe_all(ctx)["phenophase"]
    assert o.origin.value == "derived" and o.value > 22
    q = annotate_quality(ctx)["phenophase"]
    assert q.reliability == Reliability.LOW and q.detail["conflicts"][0]["in_use"]["origin"] == "derived"
    assert o.value == observe_all(make_context(agronomic={"bbch": None}))["phenophase"].value      # the value is unchanged


def test_text_and_code_agree_on_which_source_wins_when_there_is_no_satellite_estimate():
    """Reconciliation with the rule the code has always had: of a reported stage and the estimate from the sowing date,
    the one with the higher reliability is used, so a report older than 14 days (low) yields to the estimate (medium).
    The satellite estimate is never a third value candidate."""
    old = make_context(agronomic={"bbch": 14, "bbch_reported_on": "2026-06-20"})
    o = observe_all(old)["phenophase"]
    assert o.origin.value == "derived" and o.value != 14
    fresh = make_context(agronomic={"bbch": 14, "bbch_reported_on": "2026-07-10"})
    assert observe_all(fresh)["phenophase"].value == 14
    with_sat = ctx_with(stage(60, 69), agronomic={"bbch": 14, "bbch_reported_on": "2026-06-20"})
    assert observe_all(with_sat)["phenophase"].value == o.value                    # the value never comes from the satellite


@pytest.mark.parametrize("estimate", [
    {"status": "insufficient_data", "bbch_min": None},
    {"status": "pre_emergence"},
    {"last_clear_obs_date": "2026-06-20", "n_clear_obs": 2},                      # 22 days old: past max_estimate_age_days
])
def test_an_estimate_that_cannot_be_compared_changes_nothing(estimate):
    s = dict(doc()["stage_estimate"], bbch_min=0, bbch_max=9)
    s.update(estimate)
    if s.get("bbch_min") is None:
        s.pop("bbch_min")
        s.pop("bbch_max")
    d = doc(stage_estimate=s, source_obs_dates=["2026-06-20", "2026-07-04", "2026-07-09"])
    d["ndvi_observations"] = doc()["ndvi_observations"]
    ctx = ctx_with(d)
    assert rel(ctx, "phenophase") == Reliability.HIGH
    assert annotate_quality(ctx)["phenophase"].detail is None


def test_the_rule_is_off_by_a_switch_and_has_no_effect_without_q(cfg):
    ctx = ctx_with(stage(10, 19))
    assert rel(ctx, "phenophase", aware=False) == Reliability.UNGRADED
    assert observe_all(ctx)["phenophase"].value == 61
    cfg("stage_conflict", enabled=False)
    assert rel(ctx, "phenophase") == Reliability.HIGH
    assert pfm.stage_status(ctx.S.parcel_features, ctx.as_of) == "off"


def test_a_conflict_never_raises_a_reliability_it_only_caps():
    for reported_on in ("2026-07-11", "2026-07-02", "2026-06-20"):              # high, medium, low reports
        for lo, hi in ((10, 19), (60, 69), (30, 40)):
            base = make_context(agronomic={"bbch_reported_on": reported_on})
            with_pf = ctx_with(stage(lo, hi), agronomic={"bbch_reported_on": reported_on})
            assert rel(with_pf, "phenophase").rank <= rel(base, "phenophase").rank
    medium = ctx_with(stage(10, 19), agronomic={"bbch": None})
    assert rel(medium, "phenophase") == Reliability.LOW


def test_the_conflict_flows_into_sigma_alpha_and_the_policy_through_the_existing_layers():
    variants = load_variants()
    clean, conflict = ctx_with(stage(60, 69)), ctx_with(stage(10, 19))
    d0, d1 = decide(clean, [], variants["V4"]), decide(conflict, [], variants["V4"])
    assert d0.sufficiency.status.value == "sufficient" and d0.question is None
    assert d1.sufficiency.status.value != "sufficient" and "phenophase" in d1.sufficiency.missing_inputs()
    assert d1.question is not None and d1.question.input == "phenophase"            # alpha asks for the stage
    assert d1.policy.act.value in ("ask", "conditional", "abstain") and d0.policy.act.value == "recommend"
    v5 = decide(conflict, [], variants["V5"])
    assert v5.policy.act.value != "recommend"


def test_the_layers_below_q_do_not_see_the_conflict_and_the_ablation_removes_it():
    variants = load_variants()
    q = ctx_with(stage(10, 19))
    plain = make_context()

    def view(ctx, name):
        d = decide(ctx, [], variants[name])
        return (d.policy.to_dict(), d.sufficiency.to_dict() if d.sufficiency else None,
                d.question.to_dict() if d.question else None, d.core_action, [t.to_dict() for t in d.tools])
    assert view(q, "V3") == view(plain, "V3")                                       # V3 has no q: nothing changes
    assert view(ablate_context(q, variants["V5-satellite"]), "V5") == view(plain, "V5")
    assert view(q, "V5") != view(plain, "V5")


def test_pi_makes_a_stage_conditioned_passage_conditional_when_the_stage_is_in_conflict():
    passage = Passage("p", "d", "text", PassageMeta(crop=["maize"], bbch_min=55, bbch_max=69))
    clean, conflict = ctx_with(stage(60, 69)), ctx_with(stage(10, 19))
    for ctx, status in ((clean, Applicability.APPLICABLE), (conflict, Applicability.CONDITIONAL)):
        q = annotate_quality(ctx)
        from smartagri.core.quality import values
        r = applicability(passage, ctx, q, values(ctx), "parcel_conditions", True)
        assert r.status == status, r
    assert "phenophase" in applicability(passage, conflict, annotate_quality(conflict), {"phenophase": 61},
                                         "parcel_conditions", True).unverifiable


# ================================================================ provenance of a run

def test_a_run_records_the_document_the_comparison_and_the_conflict(tmp_path, monkeypatch):
    from smartagri.evalkit.runner import run_scenario
    from smartagri.pipeline.generate import TemplateGenerator
    from smartagri.retrieval import load_corpus, make_retriever
    from smartagri.store import SqliteStore
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    corpus = load_corpus()
    retriever = make_retriever(corpus, SqliteStore(":memory:"))
    base = yaml.safe_load((Path(__file__).resolve().parents[1] / "eval" / "scenarios" / "dev"
                           / "IRR-T-01_complete.yaml").read_text(encoding="utf-8"))
    base["context"]["P"]["parcel_id"] = "t"
    sc = copy.deepcopy(base)
    sc["context"]["S"] = {"ndvi_series": [], "parcel_features": no_ndvi(stage(10, 19))}
    res = run_scenario(sc, "V4", corpus, retriever, TemplateGenerator())
    block = res["records"][0]["provenance"]["parcel_features"]
    assert block["document_sha256"] == pfm.document_sha256(no_ndvi(stage(10, 19))) and block["producer"]["commit"] == "abc1234"
    assert block["applied"]["stage_conflict"] is True and block["input_conflicts"][0]["rule"] == "stage_conflict"
    assert block["stage_estimate"]["comparison"] == "compared" and block["stage_estimate"]["bbch_min"] == 10
    assert block["crop_plausibility"] == {"enabled": False, "recorded": stage(10, 19)["crop_plausibility"]}
    assert res["records"][0]["decisions"]["input_conflicts"]
    assert res["first_act"] != "recommend"                                          # the conflict reached the act
    assert "parcel_features" not in run_scenario(sc, "V5-satellite", corpus, retriever,
                                                 TemplateGenerator())["records"][0]["provenance"]
    plain = run_scenario(base, "V4", corpus, retriever, TemplateGenerator())
    assert "parcel_features" not in plain["records"][0]["provenance"] and plain["first_act"] == "recommend"
    # V3 sees the features in S but has no q: its answer does not depend on them
    a, b = (run_scenario(s, "V3", corpus, retriever, TemplateGenerator()) for s in (sc, base))
    assert (a["first_act"], a["turns"][0]["answer"]) == (b["first_act"], b["turns"][0]["answer"])


# ================================================================ crop plausibility and field markers (consumer side)

def crop(decision, validated, **kw):
    c = dict(doc()["crop_plausibility"], decision=decision, transfer_validated=validated, prediction_set=["wheat"],
             p_maize=0.04)
    c.update(kw)
    return doc(crop_plausibility=c)


def events(**kw):
    e = dict(doc()["events"])
    e.update(kw)
    return doc(events=e)


def test_the_crop_and_marker_checks_are_off_in_the_shipped_config():
    cfg = pfm.settings()
    assert cfg["crop_plausibility"]["enabled"] is False and cfg["field_markers"]["enabled"] is False
    assert cfg["crop_plausibility"]["status"] == "not_validated" and cfg["field_markers"]["status"] == "not_validated"
    assert cfg["ndvi_quality"]["status"] == cfg["stage_conflict"]["status"] == "development_default"


@pytest.mark.parametrize("features", [
    crop("discrepancy", True),
    events(bare_soil_now=True, bare_soil_since="2026-06-30", confidence=0.95, data_sufficiency="s2+s1"),
    events(harvest_detected=True, harvest_date="2026-07-05", confidence=0.95, data_sufficiency="s2+s1"),
])
def test_disabled_means_no_effect_on_any_decision_and_the_parts_are_only_recorded(features):
    variants = load_variants()
    plain, with_pf = make_context(), ctx_with(no_ndvi(features))
    assert annotate_quality(with_pf).keys() == annotate_quality(plain).keys()          # no crop_identity, no field_state
    for name in ("V3", "V4", "V5"):
        a, b = decide(plain, [], variants[name]), decide(with_pf, [], variants[name])
        assert (a.policy, a.sufficiency, a.question, a.core_action) == (b.policy, b.sufficiency, b.question, b.core_action)
        assert [(k, q.reliability) for k, q in a.quality.items()] == [(k, q.reliability) for k, q in b.quality.items()]
        assert b.input_conflicts == []
    block = pfm.provenance(with_pf, annotate_quality(with_pf))
    key = "crop_plausibility" if "decision" in (features.get("crop_plausibility") or {}) and \
        features["crop_plausibility"]["decision"] == "discrepancy" else "events"
    assert block[key]["enabled"] is False and block[key]["recorded"] == features[key]
    assert block["applied"] == {"ndvi_quality": False, "stage_conflict": False, "crop_plausibility": False,
                                "field_markers": False}


def test_enabled_a_validated_discrepancy_caps_the_crop_identity_and_makes_pi_conditional(cfg):
    cfg("crop_plausibility", enabled=True)
    ctx = ctx_with(crop("discrepancy", True))
    q = annotate_quality(ctx)
    assert q["crop_identity"].reliability == Reliability.LOW and q["crop_identity"].origin.value == "user_reported"
    assert q["crop_identity"].detail["conflicts"][0]["rule"] == "crop_plausibility"
    assert q["crop_identity"].detail["crop_plausibility"]["coverage_guarantee"] is False
    assert pfm.provenance(ctx, q)["applied"]["crop_plausibility"] is True
    passage = Passage("p", "d", "text", PassageMeta(crop=["maize"]))
    from smartagri.core.quality import values
    r = applicability(passage, ctx, q, values(ctx), "parcel_conditions", True)
    assert r.status == Applicability.CONDITIONAL and r.unverifiable == ["crop"] and r.hard_fail is None
    clean = ctx_with(crop("agreement", True))
    assert annotate_quality(clean)["crop_identity"].reliability == Reliability.HIGH
    rc = applicability(passage, clean, annotate_quality(clean), values(clean), "parcel_conditions", True)
    assert rc.status == Applicability.APPLICABLE
    other = Passage("w", "d", "text", PassageMeta(crop=["wheat"]))
    assert applicability(other, ctx, q, values(ctx), "parcel_conditions", True).hard_fail == "crop"   # still a hard check


@pytest.mark.parametrize("decision, validated", [
    ("discrepancy", False), ("uncertain", True), ("insufficient_resolution", True), ("out_of_applicability", True),
    ("agreement", True)])
def test_enabled_only_a_validated_discrepancy_counts(cfg, decision, validated):
    cfg("crop_plausibility", enabled=True)
    q = annotate_quality(ctx_with(crop(decision, validated)))["crop_identity"]
    assert q.reliability == Reliability.HIGH and not (q.detail or {}).get("conflicts")
    assert q.detail["crop_plausibility"]["decision"] == decision                       # recorded all the same


def test_enabled_bare_soil_with_a_stage_above_the_limit_is_a_conflict_on_the_stage(cfg):
    cfg("field_markers", enabled=True)
    bare = events(bare_soil_now=True, bare_soil_since="2026-06-30", confidence=0.9, data_sufficiency="s2+s1")
    q = annotate_quality(ctx_with(bare))
    assert observe_all(ctx_with(bare))["field_state"].value == "bare_soil"
    assert q["field_state"].reliability == Reliability.HIGH
    assert q["phenophase"].reliability == Reliability.LOW
    assert q["phenophase"].detail["conflicts"][0]["rule"] == "field_markers"
    assert q["field_state"].age_days == 12.0
    young = ctx_with(dict(bare, stage_estimate=None), agronomic={"bbch": 5})
    assert rel(young, "phenophase") == Reliability.HIGH                                # BBCH 5 on bare soil is normal
    weak = events(bare_soil_now=True, bare_soil_since="2026-06-30", confidence=0.3, data_sufficiency="s2")
    qw = annotate_quality(ctx_with(weak))
    assert qw["field_state"].reliability == Reliability.LOW and qw["phenophase"].reliability == Reliability.HIGH
    assert "field_state" not in annotate_quality(ctx_with(events(data_sufficiency="insufficient", bare_soil_now=True)))


def test_enabled_a_harvest_conflicts_with_advice_that_assumes_a_standing_crop_only(cfg):
    cfg("field_markers", enabled=True)
    harvested = events(harvest_detected=True, harvest_date="2026-07-05", harvest_evidence="ndvi drop and s1 backscatter",
                       confidence=0.9, data_sufficiency="s2+s1")
    irrigation = ctx_with(harvested)
    assert observe_all(irrigation)["field_state"].value == "harvested"
    assert rel(irrigation, "phenophase") == Reliability.LOW
    scouting = ctx_with(harvested, advice_type=AdviceType.SCOUTING)
    assert rel(scouting, "phenophase") == Reliability.HIGH                            # scouting does not assume a crop stage
    variants = load_variants()
    d = decide(irrigation, [], variants["V4"])
    assert d.sufficiency.status.value != "sufficient" and d.input_conflicts[0]["field_state"] == "harvested"
    assert decide(make_context(), [], variants["V4"]).sufficiency.status.value == "sufficient"


def test_the_markers_cannot_lower_anything_when_they_say_a_crop_is_present(cfg):
    cfg("field_markers", enabled=True)
    ok = events(bare_soil_now=False, confidence=0.9, data_sufficiency="s2+s1")
    q = annotate_quality(ctx_with(ok))
    assert observe_all(ctx_with(ok))["field_state"].value == "crop_present"
    assert q["phenophase"].reliability == Reliability.HIGH


# ================================================================ the research API

def test_the_series_view_carries_the_new_ndvi_fields_and_the_features_summary(monkeypatch, tmp_path, store):
    from smartagri.pipeline.profile import build_profile
    from smartagri.research_api import views
    monkeypatch.setenv(provider.ENV_DIR, str(tmp_path))
    monkeypatch.setenv("SMARTAGRI_OFFLINE", "1")
    _write(tmp_path, "t", "2026-07-12", stage(10, 19))
    profile = build_profile(store, _parcel(), as_of=datetime.fromisoformat(AS_OF))
    out = views.series(_parcel(), profile)
    n = out["ndvi"]
    assert [r["obs_date"] for r in n["rows"]] == ["2026-07-04", "2026-07-09"]
    row = n["rows"][0]
    assert row["cloud_flag"] is False and row["cloud_px_share"] == 0.05 and row["n_px_interior"] == 44
    assert row["mixed_px_share"] == 0.27 and row["temporal_outlier"] is False and row["valid_px_ratio"] == 0.9
    assert n["cloud_flag"] is False and "per observation" in n["cloud_flag_note"]
    assert out["parcel_features"]["status"] == "ok" and out["parcel_features"]["stage_estimate"]["bbch_min"] == 10
    assert out["parcel_features"]["producer"]["name"] == "example-producer"
    bare = views.series(_parcel(), {"id": "p", "as_of": AS_OF, "weather": {}, "satellite": {}})
    assert "parcel_features" not in bare and bare["ndvi"]["cloud_flag"] is None


# ================================================================ the protocol lock covers the features

def test_the_lock_hashes_the_features_of_a_scenario_and_the_new_configuration_file(tmp_path):
    from smartagri import config
    from smartagri.evalkit import lock
    from smartagri.retrieval.corpus import corpus_dir
    base = yaml.safe_load((Path(__file__).resolve().parents[1] / "eval" / "scenarios" / "dev"
                           / "IRR-T-01_complete.yaml").read_text(encoding="utf-8"))
    base["context"]["S"] = {"parcel_features": dict(no_ndvi(stage(60, 69)), parcel_id="dev")}
    folder = tmp_path / "set"
    folder.mkdir()

    def files():
        return lock.collect(folder, corpus_dir(), config.config_dir(), lock.default_rater_guide(),
                            analysis_plan=lock.default_analysis_plan())
    (folder / "A.yaml").write_text(yaml.safe_dump(base), encoding="utf-8")
    before = files()
    assert "config/parcel_features.yaml" in before
    assert Context.from_dict(base["context"]).S.parcel_features is not None            # the scenario loads with it
    base["context"]["S"]["parcel_features"]["stage_estimate"]["bbch_max"] = 70        # one number of the producer's block
    (folder / "A.yaml").write_text(yaml.safe_dump(base), encoding="utf-8")
    after = files()
    assert after["scenarios/A.yaml"] != before["scenarios/A.yaml"]
    assert lock.combined(after, "p") != lock.combined(before, "p")
    assert set(config.config_hashes()) >= {"parcel_features"}
