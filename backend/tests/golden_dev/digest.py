"""Golden digests of the development scenarios' decisions (never the test set).

For every development scenario and every variant, the decision of the core (`decide(...).to_dict()`) is reduced to a
canonical JSON text and hashed. Ids and timestamps are removed first, so a digest changes only when a decision changes.
`dev_decisions.json` holds the expected digests; a test compares the current code with it, with and without an empty
settings overlay. The file is rewritten only by the explicit command

    python tests/golden_dev/update.py

which is run on purpose when a change of the decision core, of a configuration file or of the development scenarios is
meant to change a decision. A pull request that touches the file shows exactly which decisions moved.
"""
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

import yaml

BACKEND = Path(__file__).resolve().parents[2]
DEV = BACKEND / "eval" / "scenarios" / "dev"
GOLDEN = Path(__file__).resolve().parent / "dev_decisions.json"
VARIANTS = ("V0", "V1", "V2", "V3", "V4", "V5")
VOLATILE = {"id", "created_at", "updated_at", "at", "timestamp", "generated_at", "run_id", "conversation_id", "seq"}


def scrub(obj: Any) -> Any:
    """The object without ids and timestamps (any key named like one of them, at any depth)."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if k not in VOLATILE and not k.endswith("_id")}
    if isinstance(obj, (list, tuple)):
        return [scrub(v) for v in obj]
    return obj


def canonical(obj: Any) -> str:
    return json.dumps(scrub(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute(overlay: bool = False) -> Dict[str, str]:
    """{"<scenario>/<variant>": sha256 of the decision}, for the development scenarios only."""
    from smartagri import config
    from smartagri.core.decide import decide
    from smartagri.core.types import Context, Passage
    from smartagri.web_settings.service import empty_summary
    variants = config.load_variants()
    passages = [Passage.from_dict(p) for p in yaml.safe_load((DEV / "_passages.yaml").read_text(encoding="utf-8"))]
    out: Dict[str, str] = {}
    for path in sorted(p for p in DEV.glob("*.yaml") if not p.name.startswith("_")):
        ctx = Context.from_dict(yaml.safe_load(path.read_text(encoding="utf-8"))["context"])
        for name in VARIANTS:
            if overlay:
                with config.use_overlay(config.Overlay({}, empty_summary())):
                    text = canonical(decide(ctx, passages, variants[name]).to_dict())
            else:
                text = canonical(decide(ctx, passages, variants[name]).to_dict())
            out["%s/%s" % (path.stem, name)] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return out


def overall(items: Dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(items, sort_keys=True).encode("utf-8")).hexdigest()


def load() -> Dict[str, Any]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def write(items: Dict[str, str]) -> None:
    doc = {"what": "sha256 of the decision (ids and timestamps removed) per development scenario and variant",
           "update_with": "python tests/golden_dev/update.py", "scenarios": len({k.split("/")[0] for k in items}),
           "variants": list(VARIANTS), "overall": overall(items), "items": dict(sorted(items.items()))}
    GOLDEN.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
