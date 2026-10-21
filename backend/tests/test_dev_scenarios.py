from pathlib import Path

import pytest
import yaml

from smartagri.config import load_variants
from smartagri.core.decide import decide
from smartagri.core.types import Applicability, Context, Passage

DEV = Path(__file__).resolve().parents[1] / "eval" / "scenarios" / "dev"
PASSAGES = [Passage.from_dict(p) for p in yaml.safe_load((DEV / "_passages.yaml").read_text(encoding="utf-8"))]
FILES = sorted(p for p in DEV.glob("*.yaml") if not p.name.startswith("_"))


def _param(path):
    """A scenario with `xfail_reason:` states the agronomically sensible expectation that the current
    code does not yet meet. strict=True: once the code meets it, the XPASS fails and the key must be removed."""
    reason = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("xfail_reason")
    marks = [pytest.mark.xfail(reason=reason, strict=True)] if reason else []
    return pytest.param(path, id=path.stem, marks=marks)


@pytest.mark.parametrize("path", [_param(p) for p in FILES])
def test_dev_scenario(path):
    sc = yaml.safe_load(path.read_text(encoding="utf-8"))
    ctx = Context.from_dict(sc["context"])
    expect = sc["expect"]
    variants = load_variants()
    for name in ("V4", "V5"):
        if name not in expect:
            continue
        d = decide(ctx, PASSAGES, variants[name])
        e = expect[name]
        assert d.policy.act.value == e["act"], (name, d.policy)
        if "sufficiency" in e:
            assert d.sufficiency.status.value == e["sufficiency"], (name, d.sufficiency)
        if "question" in e:
            assert (d.question.input if d.question else None) == e["question"], (name, d.question)
        if "reason_code" in e:
            assert d.policy.reason_code == e["reason_code"]
        if "allow_quantity" in e:
            assert d.policy.allow_quantity == e["allow_quantity"]
    d = decide(ctx, PASSAGES, variants["V5"])
    if "core_action" in expect:
        assert d.core_action == expect["core_action"]
    for inp in expect.get("missing_contains", []):
        assert inp in d.sufficiency.missing_inputs()
    for inp, rel in expect.get("quality", {}).items():
        assert d.quality[inp].reliability.value == rel
    na = {r.passage_id for r in d.applicability if r.status == Applicability.NOT_APPLICABLE}
    assert set(expect.get("not_applicable", [])) <= na
