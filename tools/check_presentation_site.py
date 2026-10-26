"""Check the presentation site: local links and anchors, accessibility references, external resources and the
provenance hashes of the screenshots. Standard library only; Python 3.9+.

    python tools/check_presentation_site.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import List
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1] / "website"
REQUIRED_FIELDS = ("interface", "file", "sha256", "source_commit", "capture_method")


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set = set()
        self.refs: List[str] = []
        self.resources: List[str] = []     # loaded by the page itself (scripts, styles, images, icons)
        self.errors: List[str] = []
        self.lang = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang") or ""
        if "id" in a:
            if a["id"] in self.ids:
                self.errors.append("duplicate id: %s" % a["id"])
            self.ids.add(a["id"])
        if tag == "img" and "alt" not in a:
            self.errors.append("image without alt text: %s" % a.get("src"))
        if tag == "button" and "type" not in a:
            self.errors.append("button without type: %s" % a.get("id", "?"))
        for key in ("href", "src", "data-image"):
            if a.get(key):
                self.refs.append(a[key])
        if tag in ("script", "img") and a.get("src"):
            self.resources.append(a["src"])
        if tag == "link" and a.get("href") and a.get("rel") in ("stylesheet", "icon", "preload", "modulepreload"):
            self.resources.append(a["href"])
        for key in ("aria-controls", "aria-labelledby", "aria-describedby"):
            for target in (a.get(key) or "").split():
                self.refs.append("#" + target)


def inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def check() -> List[str]:
    root = ROOT.resolve()
    page = Page()
    page.feed((ROOT / "index.html").read_text(encoding="utf-8"))
    errors = list(page.errors)
    if page.lang != "en":
        errors.append("the page must declare lang=\"en\"")
    for ref in page.refs:
        parts = urlsplit(ref)
        if parts.scheme or parts.netloc:
            continue
        if not parts.path:
            if parts.fragment and parts.fragment not in page.ids:
                errors.append("unknown anchor: %s" % ref)
            continue
        if parts.path.startswith("/"):
            errors.append("absolute path breaks a project subpath: %s" % ref)
            continue
        target = (ROOT / unquote(parts.path)).resolve()
        if not inside(target, root) or not target.is_file():
            errors.append("missing or escaping local file: %s" % ref)
    for res in page.resources:
        if urlsplit(res).scheme or res.startswith("//"):
            errors.append("external resource (no CDN, fonts or analytics allowed): %s" % res)
    for css in ROOT.glob("assets/*.css"):
        text = css.read_text(encoding="utf-8")
        if "@import" in text or "url(http" in text or "url(//" in text:
            errors.append("external resource in %s" % css.name)

    evidence = json.loads((ROOT / "assets/screenshots.json").read_text(encoding="utf-8"))
    shots = evidence.get("screenshots") or []
    if not any(s.get("interface") == "web" for s in shots):
        errors.append("at least one web app screenshot is required")
    listed = set()
    for s in shots:
        missing = [k for k in REQUIRED_FIELDS if not s.get(k)]
        if missing:
            errors.append("screenshot %s lacks %s" % (s.get("file"), ", ".join(missing)))
            continue
        path = (ROOT / s["file"]).resolve()
        listed.add(path)
        if not inside(path, root) or not path.is_file():
            errors.append("missing screenshot: %s" % s["file"])
        elif hashlib.sha256(path.read_bytes()).hexdigest() != s["sha256"]:
            errors.append("screenshot hash mismatch: %s" % s["file"])
    for img in ROOT.glob("assets/images/*.png"):
        if img.resolve() not in listed:
            errors.append("image without provenance entry: %s" % img.name)
    return errors


if __name__ == "__main__":
    issues = check()
    for issue in issues:
        print(issue)
    if issues:
        sys.exit(1)
    print("Presentation site: links, anchors, accessibility references, resources and screenshots passed.")
