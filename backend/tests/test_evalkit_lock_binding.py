"""The lock a locked run used is the lock of the repository (or a file whose hash the operator states), the run
section (repeats, variants) is part of it, and every item records which lock produced it.

The real test set is never read: a protected folder is a temporary copy of two development scenarios."""
import json
import shutil

import pytest

from smartagri.evalkit import lock, report
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
    # the lock refuses a dirty checkout; these tests are about the lock, not about the state of the working tree
    monkeypatch.setattr(lock, "git_state", lambda: {"git": True, "commit": "0" * 40, "dirty": []})
    return tmp_path


def _fake_test_set(tmp_path, ids=("IRR-T-01", "SCO-05")):
    folder = tmp_path / "fake_test"
    folder.mkdir()
    for p in DEV.glob("*.yaml"):
        if any(p.name.startswith(i + "_") for i in ids):
            shutil.copy(p, folder / p.name)
    return folder


def _make_lock(env, folder, name="lock.json", *extra):
    snap = env / "snapshot.tar"
    snap.write_bytes(b"cache snapshot")
    out = env / name
    assert cli(["lock", "--set", "test", "--scenarios-dir", str(folder), "--cache-snapshot", str(snap),
                "--out", str(out), *extra]) == 0
    return out


def _run_args(folder, lock_file, *extra):
    return ["run", "--set", "test", "--locked", "--lock-file", str(lock_file), "--scenarios-dir", str(folder),
            "--variant", "V5", *extra]


def test_a_foreign_lock_file_is_refused_unless_its_hash_is_stated(env, capsys):
    folder = _fake_test_set(env)
    other = _make_lock(env, folder)                              # a lock anyone can write anywhere
    capsys.readouterr()
    assert cli(_run_args(folder, other)) == 2
    assert "not the repository's lock" in capsys.readouterr().err
    assert cli(_run_args(folder, other, "--lock-sha256", "0" * 64)) == 2
    assert "does not match" in capsys.readouterr().err
    assert cli(_run_args(folder, other, "--lock-sha256", lock.lock_sha256(other))) == 0


def test_the_repositorys_own_lock_needs_no_stated_hash(env, capsys, monkeypatch):
    folder = _fake_test_set(env)
    own = _make_lock(env, folder, "repo-lock.json")
    monkeypatch.setattr(lock, "default_lock_path", lambda: own)
    capsys.readouterr()
    assert cli(["run", "--set", "test", "--locked", "--scenarios-dir", str(folder), "--variant", "V5"]) == 0


def test_every_item_records_the_lock_it_came_from(env, capsys):
    folder = _fake_test_set(env)
    one = _make_lock(env, folder)
    capsys.readouterr()
    sha = lock.lock_sha256(one)
    assert cli(_run_args(folder, one, "--lock-sha256", sha)) == 0
    capsys.readouterr()
    assert cli(["run", "--set", "dev", "--scenarios-dir", str(folder), "--variant", "V4"]) == 0
    capsys.readouterr()
    assert cli(["export", "--set", "dev"]) == 0
    assert {i["lock_sha256"] for i in json.loads(capsys.readouterr().out)["items"]} == {None}
    from smartagri.store import make_store
    items = [i for i in make_store().list_eval_items() if i["set"] == "test"]
    assert items and {i["lock_sha256"] for i in items} == {sha}
    assert {i["lock_combined_sha256"] for i in items} == {json.loads(one.read_text())["combined_sha256"]}


def test_report_and_export_refuse_to_mix_items_of_different_locks(env, capsys):
    folder = _fake_test_set(env)
    a = _make_lock(env, folder, "a.json")
    assert cli(_run_args(folder, a, "--lock-sha256", lock.lock_sha256(a))) == 0
    first = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["batch_id"]
    b = env / "b.json"
    snap = env / "snapshot.tar"
    assert cli(["lock", "--set", "test", "--scenarios-dir", str(folder), "--cache-snapshot", str(snap),
                "--out", str(b), "--tag", "protocol-v2"]) == 0
    capsys.readouterr()
    assert cli(_run_args(folder, b, "--lock-sha256", lock.lock_sha256(b))) == 0
    second = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["batch_id"]
    for cmd in (["report", "--set", "test"], ["export", "--set", "test"]):
        assert cli(cmd) == 2
        assert "different protocol locks" in capsys.readouterr().err
    assert cli(["report", "--set", "test", "--batch", first]) == 0
    assert cli(["export", "--set", "test", "--batch", second]) == 0
    with pytest.raises(ValueError):
        lock.single_lock([{"lock_sha256": "a" * 64}, {"lock_sha256": None}])
    assert report.select([], "test") == []


def test_repeats_and_variants_are_part_of_the_lock(env, capsys):
    folder = _fake_test_set(env)
    out = _make_lock(env, folder, "r.json", "--repeats", "2", "--variant", "V4", "--variant", "V3")
    capsys.readouterr()
    data = json.loads(out.read_text())
    assert data["format"] == "smartagri-protocol-lock/3" and data["run"] == {"repeats": 2, "variants": ["V3", "V4"], "decision_hour_utc": None}
    sha = lock.lock_sha256(out)
    common = ["--lock-sha256", sha, "--variant", "V4"]
    assert cli(["run", "--set", "test", "--locked", "--lock-file", str(out), "--scenarios-dir", str(folder)] + common) == 2
    assert "changed: repeats" in capsys.readouterr().err                    # default 1 repeat is not the locked 2
    assert cli(["run", "--set", "test", "--locked", "--lock-file", str(out), "--scenarios-dir", str(folder),
                "--repeats", "2", "--lock-sha256", sha, "--variant", "V5"]) == 2
    assert "not in lock: variant V5" in capsys.readouterr().err
    assert cli(["run", "--set", "test", "--locked", "--lock-file", str(out), "--scenarios-dir", str(folder),
                "--repeats", "2"] + common) == 0
    capsys.readouterr()
    from smartagri.store import make_store
    items = make_store().list_eval_items()
    assert len(items) == 4 and {i["repeats"] for i in items} == {2} and {i["repeat"] for i in items} == {1, 2}
    # a different repeats value is a different protocol fingerprint
    assert lock.combined({"a": "1"}, "p", run=lock.run_section(1)) != lock.combined({"a": "1"}, "p", run=lock.run_section(2))
    assert lock.run_differences({"format": "x"}, 1, ["V4"])[0].startswith("lock has no run section")
