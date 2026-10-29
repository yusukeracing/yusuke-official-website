#!/usr/bin/env python3
"""Validate the static site, local links, content JSON and performance budgets.

Usage: python3 scripts/check_site.py [dist]
This complements browser tests; it does not claim to measure Core Web Vitals.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from build import PAGES, PUBLIC_PAGES, PUBLIC_DATA, public_message_errors

ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self, path: Path):
        super().__init__(convert_charrefs=True)
        self.path = path
        self.tags = []
        self.ids = []
        self.references = []
        self.inline_scripts = []
        self.script = None
        self.title = ""
        self.in_title = False
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        if tag == "title":
            self.in_title = True
        if tag == "script" and not attrs.get("src"):
            self.script = [attrs, ""]
        for attribute in ("src", "href", "poster"):
            if attrs.get(attribute):
                self.references.append((tag, attribute, attrs[attribute]))
        if attrs.get("srcset"):
            for part in attrs["srcset"].split(","):
                self.references.append((tag, "srcset", part.strip().split()[0]))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "script" and self.script is not None:
            self.inline_scripts.append(self.script)
            self.script = None

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.script is not None:
            self.script[1] += data


def validate(root: Path):
    errors = []
    warnings = []
    pages = {}
    try:
        public_url = urlsplit(json.loads((root / "data/site.json").read_text(encoding="utf-8")).get("url", ""))
    except (OSError, ValueError, AttributeError):
        public_url = urlsplit("")

    def require(condition, message):
        if not condition:
            errors.append(message)

    for name in PAGES:
        path = root / name
        if not path.is_file():
            errors.append(f"Missing required page: {name}")
            continue
        require(not re.search(r"^(?:<<<<<<< |=======$|>>>>>>> )", path.read_text(encoding="utf-8"), re.M),
                f"{name}: unresolved merge conflict markers")
        page = pages[name] = Page(path)
        meta = {a.get("name", a.get("property", a.get("http-equiv", ""))).lower(): a.get("content", "")
                for tag, a in page.tags if tag == "meta"}
        require(bool(page.title.strip()), f"{name}: missing title")
        require(any(tag == "html" and a.get("lang", "").startswith("ja") for tag, a in page.tags), f"{name}: missing Japanese lang")
        require(bool(meta.get("description")), f"{name}: missing meta description")
        require("width=device-width" in meta.get("viewport", ""), f"{name}: missing responsive viewport")
        require(bool(meta.get("og:title")) and bool(meta.get("og:description")) and bool(meta.get("og:url")), f"{name}: incomplete OGP")
        require(any(tag == "link" and a.get("rel") == "canonical" and a.get("href", "").startswith("https://") for tag, a in page.tags), f"{name}: missing HTTPS canonical")
        require(any(tag == "h1" for tag, _ in page.tags), f"{name}: missing h1")
        require(len(page.ids) == len(set(page.ids)), f"{name}: duplicate HTML IDs")
        require(any(tag == "a" and a.get("href") == "#main" for tag, a in page.tags), f"{name}: missing skip link to #main")
        csp = meta.get("content-security-policy", "")
        require("object-src 'none'" in csp and "script-src" in csp, f"{name}: missing restrictive CSP")
        for tag, attrs in page.tags:
            require(not any(re.search(r"[<>\"']", key) for key in attrs),
                    f"{name}: malformed HTML attributes on {tag}")
            require(not any(key.lower().startswith("on") for key in attrs), f"{name}: inline event handler on {tag}")
            if tag == "script" and attrs.get("src"):
                require("defer" in attrs or attrs.get("type") == "module", f"{name}: blocking script {attrs['src']}")
                src = urlsplit(attrs["src"])
                public_asset = (src.scheme == "https" and src.netloc == public_url.netloc
                                and src.path.startswith(public_url.path.rstrip("/") + "/assets/js/"))
                require(not src.netloc or public_asset or src.netloc == "www.googletagmanager.com", f"{name}: unexpected external JavaScript {attrs['src']}")
            if tag == "img":
                require("alt" in attrs, f"{name}: image lacks alt")
                require(bool(attrs.get("width")) and bool(attrs.get("height")), f"{name}: image lacks dimensions")
                on_demand_dialog = "lightbox-image" in attrs.get("class", "").split() and "hidden" in attrs and not attrs.get("src")
                require(on_demand_dialog or attrs.get("loading") == "lazy" or attrs.get("fetchpriority") == "high", f"{name}: non-hero image must lazy load")
            if attrs.get("target") == "_blank":
                require({"noopener", "noreferrer"}.issubset(set(attrs.get("rel", "").split())), f"{name}: unsafe external tab link")
            if tag == "iframe":
                require(bool(attrs.get("title")), f"{name}: iframe lacks accessible title")
                frame = urlsplit(attrs.get("src", ""))
                require(frame.scheme == "https" and frame.netloc == "docs.google.com"
                        and re.fullmatch(r"/forms/(?:d/e/|d/)[\w-]+/viewform", frame.path),
                        f"{name}: unexpected iframe destination")
        for attrs, content in page.inline_scripts:
            require(attrs.get("type") == "application/ld+json", f"{name}: unexpected inline JavaScript")
            if attrs.get("type") == "application/ld+json":
                try:
                    json.loads(content)
                except json.JSONDecodeError as exc:
                    errors.append(f"{name}: invalid JSON-LD: {exc}")
                digest = base64.b64encode(hashlib.sha256(content.encode()).digest()).decode()
                require("sha256-" + digest in csp, f"{name}: CSP hash does not cover JSON-LD")
        if path.stat().st_size > 50 * 1024:
            warnings.append(f"{name}: HTML exceeds the 50 KB target")

    for name, page in pages.items():
        for tag, attribute, value in page.references:
            parsed = urlsplit(value)
            require(parsed.scheme not in {"javascript", "vbscript"}, f"{name}: unsafe {attribute} URL")
            if parsed.scheme or parsed.netloc:
                continue
            target = unquote(parsed.path)
            # Absolute project-root paths break under GitHub Pages repository URLs.
            require(not target.startswith("/"), f"{name}: root-absolute URL breaks project hosting: {value}")
            if not target:
                destination = root / name
            else:
                destination = (root / target).resolve()
            require(destination.is_relative_to(root.resolve()), f"{name}: local URL escapes public root: {value}")
            if not destination.is_relative_to(root.resolve()):
                continue
            require(destination.exists(), f"{name}: missing local {attribute}: {value}")
            if parsed.fragment and destination.name in pages:
                require(unquote(parsed.fragment) in pages[destination.name].ids, f"{name}: missing anchor {value}")

    required_json = {Path(filename).stem: dict for filename in PUBLIC_DATA}
    data = {}
    for name, expected in required_json.items():
        try:
            value = data[name] = json.loads((root / "data" / f"{name}.json").read_text(encoding="utf-8"))
            require(isinstance(value, expected), f"data/{name}.json: unexpected top-level structure")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"data/{name}.json: {exc}")
    for name in ("news", "sponsors", "gallery", "messages"):
        value = data.get(name)
        require(isinstance(value, dict) and isinstance(value.get("items"), list), f"data/{name}.json: items must be an array")
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            require(all(isinstance(item, dict) for item in value["items"]),
                    f"data/{name}.json: each item must be an object")
    if "messages" in data:
        errors.extend(public_message_errors(data["messages"]))
    site = data.get("site")
    maintenance = isinstance(site, dict) and site.get("maintenanceEnabled") is True
    if isinstance(site, dict) and "maintenanceEnabled" in site:
        require(isinstance(site["maintenanceEnabled"], bool), "data/site.json: maintenanceEnabled must be a boolean")
    if maintenance:
        for name, page in pages.items():
            require(any(tag == "body" and a.get("data-maintenance-mode") == "true" for tag, a in page.tags),
                    f"{name}: maintenance mode is not rendered")
            require(any(tag == "meta" and a.get("name") == "robots" and "noindex" in a.get("content", "") for tag, a in page.tags),
                    f"{name}: maintenance page must be noindex")
    else:
        for name, page in pages.items():
            require(not any(tag == "body" and a.get("data-maintenance-mode") == "true" for tag, a in page.tags),
                    f"{name}: maintenance mode remains enabled in normal publication")
    # Each file in data/ is public after deployment, even when the UI hides it.
    data_directory = root / "data"
    if data_directory.is_dir():
        for path in data_directory.rglob("*"):
            if path.is_file():
                require(path.parent == data_directory and path.name in PUBLIC_DATA,
                        f"Unexpected public data file: {path.relative_to(root)}")
    for field in ("results", "schedule"):
        races = data.get("races")
        require(isinstance(races, dict) and isinstance(races.get(field), list),
                f"data/races.json: {field} must be an array")
        if isinstance(races, dict) and isinstance(races.get(field), list):
            require(all(isinstance(item, dict) for item in races[field]),
                    f"data/races.json: each {field} item must be an object")
    for extension, budget in (("css", 100 * 1024), ("js", 80 * 1024)):
        files = list((root / "assets" / extension).glob(f"*.{extension}"))
        require(bool(files), f"Missing {extension} assets")
        total = sum(path.stat().st_size for path in files)
        require(total <= budget, f"{extension.upper()} total {total} bytes exceeds {budget}-byte performance budget")
    require((root / ".nojekyll").exists(), "Missing .nojekyll")
    for filename in ("robots.txt", "sitemap.xml"):
        require((root / filename).is_file(), f"Missing {filename}; run python3 scripts/build.py")
    if (root / "sitemap.xml").is_file():
        try:
            tree = ET.parse(root / "sitemap.xml")
            locations = tree.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            indexed_pages = () if maintenance else PUBLIC_PAGES
            require(len(locations) == len(indexed_pages),
                    f"sitemap.xml must include {len(indexed_pages)} pages in the current publication mode")
            site = data.get("site")
            url = site.get("url", "") if isinstance(site, dict) else ""
            base = url.rstrip("/") + "/" if isinstance(url, str) else ""
            require(all((item.text or "").startswith(base) for item in locations), "sitemap.xml URLs differ from data/site.json")
            expected = {base + ("" if page == "index.html" else page) for page in indexed_pages}
            require({item.text for item in locations} == expected,
                    "sitemap.xml does not match the public content page list")
        except ET.ParseError as exc:
            errors.append(f"sitemap.xml: {exc}")
    require(not list(root.rglob("*.php")), "PHP is not supported on GitHub Pages")
    require(not (root / "admin").exists(), "Do not expose a custom admin directory")
    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.directory.resolve()
    errors, warnings = validate(root)
    for message in warnings:
        print("WARNING:", message)
    for message in errors:
        print("FAIL:", message)
    if errors:
        print(f"{len(errors)} validation failure(s) in {root}")
        return 1
    print(f"PASS: {len(PAGES)} pages, local links, public JSON data, metadata, CSP, image attributes and CSS/JS budgets ({root})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
