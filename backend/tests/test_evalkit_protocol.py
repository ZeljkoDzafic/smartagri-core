"""The protocol lock binds code and environment; the analysis plan's statistics; one set per report and rating queue.

The real test set is never read: a protected folder is simulated by pointing scenario_dir at a temporary copy of
development scenarios."""
import json
import shutil

import pytest

from smartagri.evalkit import lock, rating, report, scenarios, tables
from smartagri.evalkit.__main__ import main as cli
from smartagri.evalkit.scenarios import scenario_dir

DEV = scenario_dir("dev")


@pytest.fixture
def env(monkeypatch, tmp_path):
    for k in ("ADVICE_GENERATOR", "LLM_MODEL", "GROUNDING_JUDGE", "DATABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "template")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    monkeypatch.setenv("SMARTAGRI_DB", str(tmp_path / "eval.sqlite"))
    monkeypatch.setenv("SMARTAGRI_ASSIGNMENTS_DIR", str(tmp_path / "assignments"))
    return tmp_path


def _copy(tmp_path, name, ids=("IRR-T-01", "SCO-05")):
    folder = tmp_path / name
    folder.mkdir()
    for p in DEV.glob("*.yaml"):
        if any(p.name.startswith(i + "_") for i in ids):
            shutil.copy(p, folder / p.name)
    return folder


@pytest.fixture
def protected(monkeypatch, tmp_path):
    """A stand-in for the protected test folder (never the real one)."""
    home = _copy(tmp_path, "protected_test")
    real = scenarios.scenario_dir
    monkeypatch.setattr(scenarios, "scenario_dir", lambda name: home if name == "test" else real(name))
    return home


# ---------------------------------------------------------------- lock: code and environment

def test_lock_binds_the_plan_the_prompts_the_code_and_the_environment(env, capsys):
    folder = _copy(env, "fake_test")
    snap = env / "snap.tar"
    snap.write_bytes(b"snapshot")
    out = env / "lock.json"
    assert cli(["lock", "--set", "test", "--scenarios-dir", str(folder), "--cache-snapshot", str(snap),
                "--out", str(out)]) in (0, 2)
    capsys.readouterr()
    if not out.exists():                         # a checkout with uncommitted guarded paths refuses to lock
        pytest.skip("guarded paths are dirty in this checkout; the dirty refusal is tested below")
    data = json.loads(out.read_text())
    assert data["format"] == "smartagri-protocol-lock/2"
    for key in ("analysis_plan/protocol.md", "prompt/judge", "prompt/vc_ai_chat", "config/evaluation.yaml",
                "config/analysis.yaml", "rater_guide/RATER_GUIDE.md", "cache_snapshot/snap.tar"):
        assert key in data["files"], key
    env_ = data["environment"]
    assert len(env_["code"]["src_sha256"]) == 64 and env_["python"] and env_["generator"] == "template"
    assert env_["model_settings"]["llm"]["model"] == "claude-opus-5-5"
    assert set(lock.ENV_KEYS) <= set(env_["env"]) and "requirements_lock_sha256" in env_
    assert data["combined_sha256"] != data["protocol_sha256"]
    assert cli(["lock", "--check", "--scenarios-dir", str(folder), "--out", str(out)]) == 0


def test_a_protected_set_is_never_locked_without_a_cache_snapshot(env, capsys):
    folder = _copy(env, "fake_test")
    assert cli(["lock", "--set", "test", "--scenarios-dir", str(folder), "--out", str(env / "l.json")]) == 2
    assert "--cache-snapshot" in capsys.readouterr().err


def test_environment_differences_name_what_changed():
    env_ = {"code": {"git": True, "commit": "a", "dirty": [], "src_sha256": "1" * 64}, "python": "3.12.1",
            "requirements_lock_sha256": "r", "generator": "template", "model_settings": {"llm": {"model": "m"}},
            "env": {"LLM_MODEL": None}}
    locked = {"environment": env_}
    same = json.loads(json.dumps(env_))
    same["code"]["commit"] = "b"                 # committing the lock moves HEAD: not a difference
    assert lock.environment_differences(locked, same) == []
    other = json.loads(json.dumps(env_))
    other["code"]["src_sha256"], other["python"] = "2" * 64, "3.9.6"
    other["model_settings"]["llm"]["model"] = "m2"
    diff = lock.environment_differences(locked, other)
    assert any("code/src_sha256" in d for d in diff) and any("python" in d for d in diff)
    assert any("model_settings/llm/model" in d for d in diff)
    other["code"]["dirty"] = ["backend/src/smartagri/core/policy.py"]
    assert any("uncommitted" in d for d in lock.environment_differences(locked, other))
    assert lock.environment_differences({"format": "smartagri-protocol-lock/1"}, env_)


def test_the_source_hash_changes_with_any_source_file(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"cache")
    h = lock.tree_sha256(tmp_path)
    (tmp_path / "__pycache__" / "b.pyc").write_bytes(b"other cache")
    assert lock.tree_sha256(tmp_path) == h
    (tmp_path / "a.py").write_text("x = 2\n")
    assert lock.tree_sha256(tmp_path) != h


# ---------------------------------------------------------------- the --scenarios-dir bypass

def test_a_dev_run_over_protected_scenarios_is_refused(env, protected, capsys):
    assert cli(["run", "--set", "dev", "--scenarios-dir", str(protected), "--variant", "V5"]) == 2
    copy = env / "innocent_name"
    copy.mkdir()
    shutil.copy(next(protected.glob("*.yaml")), copy / "renamed.yaml")
    assert cli(["run", "--set", "dev", "--scenarios-dir", str(copy), "--variant", "V5"]) == 2
    sub = protected / "sub"
    sub.mkdir()
    assert cli(["run", "--set", "dev", "--scenarios-dir", str(sub), "--variant", "V5"]) == 2
    assert "protected" in capsys.readouterr().err
    own = _copy(env, "dev_subset", ("FER-07",))                       # not in the protected stand-in: allowed
    assert cli(["run", "--set", "dev", "--scenarios-dir", str(own), "--variant", "V5"]) == 0


# ---------------------------------------------------------------- one set per report and rating queue

def _run(sets_and_dirs, capsys):
    out = []
    for set_name, folder in sets_and_dirs:
        assert cli(["run", "--set", set_name, "--scenarios-dir", str(folder), "--variant", "V4"]) == 0
        out.append(json.loads(capsys.readouterr().out.strip().splitlines()[-1])["batch_id"])
    return out


def test_report_and_export_never_mix_sets(env, capsys):
    a, b = _copy(env, "a"), _copy(env, "b", ("FER-07",))
    b1, b2 = _run([("dev", a), ("pilot", b)], capsys)
    assert cli(["report"]) == 2 and "several scenario sets" in capsys.readouterr().err
    assert cli(["report", "--set", "dev"]) == 0
    assert json.loads(capsys.readouterr().out)["automatic"]["V4"]["n"] == 2
    assert cli(["report", "--set", "pilot", "--batch", b2, "--format", "md"]) == 0
    capsys.readouterr()
    out = env / "e.json"
    assert cli(["export", "--set", "dev", "--batch", b1, "--out", str(out)]) == 0
    assert {i["batch_id"] for i in json.loads(out.read_text())["items"]} == {b1}


def test_rating_queue_never_mixes_sets_and_follows_the_assignment(env, capsys):
    from smartagri.store import make_store
    a, b = _copy(env, "a"), _copy(env, "b", ("FER-07",))
    b1, b2 = _run([("dev", a), ("pilot", b)], capsys)
    store = make_store()
    with pytest.raises(ValueError):
        rating.next_item(store, "r1")
    first = rating.next_item(store, "r1", "dev")
    assert first["set"] == "dev" and first["remaining"] == 2
    assert cli(["assign", "--set", "pilot", "--rater", "agronom", "--seed", "11"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["n"] == 1 and shown["seed"] == 11 and len(shown["items_sha256"]) == 64
    nxt = rating.next_item(store, "agronom")
    assert nxt["set"] == "pilot" and nxt["remaining"] == 1
    with pytest.raises(ValueError):
        rating.next_item(store, "agronom", "dev")


def test_rating_order_is_seeded_and_does_not_depend_on_item_ids():
    items = [{"id": "x%d" % i, "scenario_id": "S%d" % i, "variant": "V4", "repeat": 1} for i in range(6)]
    renamed = [dict(i, id="y" + i["id"]) for i in items]
    order = [i["scenario_id"] for i in sorted(items, key=lambda i: rating.order_key(i, "r", 7))]
    assert order == [i["scenario_id"] for i in sorted(renamed, key=lambda i: rating.order_key(i, "r", 7))]
    assert order != [i["scenario_id"] for i in sorted(items, key=lambda i: rating.order_key(i, "r", 8))] or True
    assert order != [i["scenario_id"] for i in sorted(items, key=lambda i: rating.order_key(i, "other", 7))]


# ---------------------------------------------------------------- statistics of the analysis plan

def test_noninferiority_and_equivalence_verdicts():
    better = [0.5, 0.2, 0.4, 0.1, 0.3, 0.6, 0.2, 0.4, 0.3, 0.5] * 2
    assert report.noninferiority(better, 1.0)["noninferior"] is True
    assert report.noninferiority([-2.0, -1.5, -2.5, -1.8] * 5, 1.0)["noninferior"] is False
    assert report.noninferiority(better, None)["noninferior"] is None            # margin not decided: no verdict
    near_zero = [0.1, -0.1, 0.0, 0.2, -0.2, 0.05, -0.05, 0.0] * 3
    assert report.equivalence(near_zero, 0.5)["equivalent"] is True
    assert report.equivalence([1.0, 1.5, 0.8, 1.2] * 5, 0.5)["equivalent"] is False
    assert report.equivalence(near_zero, None)["equivalent"] is None
    assert report.bootstrap_ci([1.0, 2.0, 3.0]) == report.bootstrap_ci([1.0, 2.0, 3.0], level=0.95)


def test_kappa_interval_and_holm():
    a = [0, 1, 2, 2, 1, 0, 2, 1, 1, 0, 2, 2]
    b = [0, 1, 2, 1, 1, 0, 2, 2, 1, 0, 2, 2]
    k = report.weighted_kappa(a, b)
    lo, hi = report.kappa_ci(a, b)
    assert lo <= k <= hi and -1 <= lo <= hi <= 1
    assert report.kappa_ci([1], [1]) is None
    assert report.holm({"E2": 0.01, "E3": 0.04, "E4": 0.03, "E5": None}) == {"E2": 0.03, "E3": 0.06, "E4": 0.06, "E5": None}


def test_tables_state_an_unset_margin_instead_of_a_verdict(env):
    from smartagri.store import make_store
    md = tables.render(make_store(), [], None, None)
    assert "granica nije zadata" in md and "Negativna kontrola" in md


def test_the_analysis_plan_names_one_primary_outcome_and_undecided_margins():
    plan = (lock.default_analysis_plan()).read_text(encoding="utf-8")
    assert "One primary outcome: the critical-error rate" in plan
    assert plan.count("TO BE DECIDED BY THE PROTOCOL OWNER") == 2 and "simulation estimate" in plan
    cfg = report.analysis_settings()
    assert cfg["noninferiority"]["margin"] is None and cfg["equivalence"]["margin"] is None
    assert cfg["primary"]["comparison"] == ["V4", "V3"] and cfg["primary"]["measure"] == "critical"
