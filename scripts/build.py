#!/usr/bin/env python3
"""Create the GitHub Pages artifact; no third-party build tools are required."""
from __future__ import annotations

import base64
from datetime import date
import hashlib
import json
import re
import shutil
from html import escape, unescape
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist"
PAGES = ("index.html", "profile.html", "race.html", "news.html", "sponsor.html",
         "support.html", "contact.html", "404.html", "maintenance.html")
PUBLIC_PAGES = PAGES[:7]
SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.I | re.S)
CANONICAL = re.compile(r'(<link\b[^>]*\brel=["\']canonical["\'][^>]*\bhref=["\'])([^"\']+)', re.I)


def site_url() -> str:
    value = json.loads((ROOT / "data/site.json").read_text(encoding="utf-8"))["url"]
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password
            or parsed.query or parsed.fragment or "xxx" in parsed.netloc):
        raise ValueError("data/site.json: url must be the public HTTPS site URL without credentials, query or fragment")
    return value.rstrip("/") + "/"


def update_page(text: str, base: str, settings: dict | None = None, profile: dict | None = None) -> str:
    """Update published URLs and preserve the CSP integrity of inline JSON-LD."""
    hashes = []
    for script in SCRIPT.finditer(text):
        if re.search(r'\btype\s*=\s*["\']application/ld\+json["\']', script[1], re.I):
            digest = base64.b64encode(hashlib.sha256(script[2].encode()).digest()).decode()
            hashes.append(digest)
    match = CANONICAL.search(text)
    if match:
        old_base = urljoin(unescape(match[2]), "./")
        if old_base != base:
            text = text.replace(old_base, escape(base, quote=True))
    if settings:
        description = settings.get("description")
        image = settings.get("ogImage")
        image_url = None
        if image:
            if not isinstance(image, str):
                raise ValueError("data/site.json: ogImage must be an image path or HTTPS URL")
            parsed_image = urlsplit(image)
            if parsed_image.scheme or parsed_image.netloc:
                if (parsed_image.scheme != "https" or not parsed_image.netloc
                        or parsed_image.username or parsed_image.password):
                    raise ValueError("data/site.json: ogImage external URLs must use HTTPS without credentials")
            elif (not parsed_image.path.startswith("assets/images/")
                  or ".." in parsed_image.path.split("/") or image.startswith("/")):
                raise ValueError("data/site.json: local ogImage must be under assets/images/")
            image_url = urljoin(base, image)

        def metadata(match):
            tag = match.group(0)
            identity = re.search(r'\b(?:name|property)\s*=\s*["\']([^"\']+)["\']', tag, re.I)
            if not identity:
                return tag
            key = identity[1].lower()
            value = None
            if key in {"description", "og:description"} and isinstance(description, str):
                value = description
            elif key == "og:image" and image_url:
                value = image_url
            if value is None:
                return tag
            replacement = 'content="' + escape(value, quote=True) + '"'
            if re.search(r'\bcontent\s*=', tag, re.I):
                return re.sub(r'\bcontent\s*=\s*(?:"[^"]*"|\'[^\']*\')',
                              lambda _: replacement, tag, count=1, flags=re.I)
            return tag[:-1] + " " + replacement + ">"

        text = re.sub(r"<meta\b[^>]*>", metadata, text, flags=re.I)
    if settings or profile:
        def structured_data(match):
            if not re.search(r'\btype\s*=\s*["\']application/ld\+json["\']', match[1], re.I):
                return match.group(0)
            payload = json.loads(match[2])
            entities = payload.get("@graph", [payload]) if isinstance(payload, dict) else payload
            if not isinstance(entities, list):
                return match.group(0)
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                if entity.get("@type") == "Person" and profile:
                    for key, source in (("name", "name"), ("alternateName", "nameEn")):
                        value = profile.get(source)
                        if isinstance(value, str) and value.strip():
                            entity[key] = value
                    birth = profile.get("birth", "")
                    try:
                        entity["birthDate"] = date.fromisoformat(str(birth).replace(".", "-")).isoformat()
                    except ValueError:
                        entity.pop("birthDate", None)
                    hometown = profile.get("hometown")
                    if isinstance(hometown, str) and hometown.strip():
                        entity["homeLocation"] = {"@type": "Place", "name": hometown}
                    else:
                        entity.pop("homeLocation", None)
                    team = (settings or {}).get("team")
                    if isinstance(team, str) and team.strip():
                        entity["memberOf"] = {"@type": "SportsOrganization", "name": team}
                    elif settings:
                        entity.pop("memberOf", None)
                if entity.get("@type") == "WebSite" and settings:
                    name = settings.get("name")
                    if isinstance(name, str) and name.strip():
                        entity["name"] = name
            # JSON-LD is inline HTML: escape markup delimiters even though it is data.
            serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            serialized = serialized.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            return "<script" + match[1] + ">" + serialized + "</script>"

        text = SCRIPT.sub(structured_data, text)
    updated_hashes = []
    for script in SCRIPT.finditer(text):
        if re.search(r'\btype\s*=\s*["\']application/ld\+json["\']', script[1], re.I):
            updated_hashes.append(base64.b64encode(hashlib.sha256(script[2].encode()).digest()).decode())
    for old, new in zip(hashes, updated_hashes):
        text = text.replace("sha256-" + old, "sha256-" + new)
    return text


def write_discovery(destination: Path, base: str) -> None:
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ET.register_namespace("", namespace)
    root = ET.Element(f"{{{namespace}}}urlset")
    for page in PUBLIC_PAGES:
        item = ET.SubElement(root, f"{{{namespace}}}url")
        ET.SubElement(item, f"{{{namespace}}}loc").text = urljoin(base, "" if page == "index.html" else page)
    ET.indent(root)
    ET.ElementTree(root).write(destination / "sitemap.xml", encoding="utf-8", xml_declaration=True)
    path = urlsplit(base).path
    robots = "User-agent: *\nAllow: /\n"
    robots += f"Disallow: {path}maintenance.html\nDisallow: {path}404.html\n\nSitemap: {base}sitemap.xml\n"
    (destination / "robots.txt").write_text(robots, encoding="utf-8")


def main() -> None:
    base = site_url()
    settings = json.loads((ROOT / "data/site.json").read_text(encoding="utf-8"))
    profile = json.loads((ROOT / "data/profile.json").read_text(encoding="utf-8"))
    for page in PAGES:
        if not (ROOT / page).is_file():
            raise FileNotFoundError(f"Missing required page: {page}")
    if OUTPUT.is_symlink():
        raise ValueError("Refusing to replace a symlink at dist/")
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir()
    for page in PAGES:
        text = (ROOT / page).read_text(encoding="utf-8")
        (OUTPUT / page).write_text(update_page(text, base, settings, profile), encoding="utf-8")
    for folder in ("assets", "data"):
        shutil.copytree(ROOT / folder, OUTPUT / folder,
                        ignore=shutil.ignore_patterns(".gitkeep", "README*", ".DS_Store"))
    (OUTPUT / ".nojekyll").touch()
    write_discovery(OUTPUT, base)
    # Keep the source checkout's discovery files in sync for direct static hosting.
    write_discovery(ROOT, base)
    count = sum(1 for path in OUTPUT.rglob("*") if path.is_file())
    print(f"Built {len(PAGES)} pages and {count} public files in {OUTPUT}")
    print(f"Public URL: {base}")


if __name__ == "__main__":
    main()
