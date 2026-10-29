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
PUBLIC_PAGES = ("index.html", "profile.html", "race.html", "news.html", "sponsor.html",
                "support.html", "contact.html", "partners.html", "messages.html")
PAGES = PUBLIC_PAGES + ("404.html", "maintenance.html")
PUBLIC_DATA = ("site.json", "profile.json", "races.json", "news.json",
               "sponsors.json", "gallery.json", "messages.json")
PUBLIC_ASSET_EXTENSIONS = {
    "css": {".css"},
    "js": {".js"},
    "icons": {".svg", ".png", ".ico", ".webp"},
    "images": {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".svg", ".ico"},
    "documents": {".pdf"},
}
SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.I | re.S)
CANONICAL = re.compile(r'(<link\b[^>]*\brel=["\']canonical["\'][^>]*\bhref=["\'])([^"\']+)', re.I)


def public_message_errors(value: object) -> list[str]:
    """Public JSON is downloadable: reject draft/contact-only fields, not just HTML."""
    if not isinstance(value, dict) or set(value) != {"items"} or not isinstance(value.get("items"), list):
        return ["data/messages.json must contain only an items array"]
    errors = []
    for index, item in enumerate(value["items"], 1):
        prefix = f"data/messages.json item {index}"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: expected an object")
            continue
        if set(item) - {"name", "message", "date"}:
            errors.append(f"{prefix}: only public name, message and date fields are allowed")
        for field in ("name", "message"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                errors.append(f"{prefix}: {field} must be nonempty public text")
        if "date" in item:
            if not isinstance(item["date"], str):
                errors.append(f"{prefix}: date must be text")
            elif item["date"]:
                try:
                    date.fromisoformat(item["date"])
                except ValueError:
                    errors.append(f"{prefix}: date must use YYYY-MM-DD")
    return errors


def copy_public_assets(source: Path, destination: Path) -> int:
    """Copy explicit asset types; hidden files, source maps and symlinks stay local.

    Files deliberately stored as public images/scripts remain public. This is an
    artifact allowlist, not a scanner capable of detecting secrets inside them.
    """
    count = 0
    for folder, extensions in PUBLIC_ASSET_EXTENSIONS.items():
        directory = source / folder
        if not directory.is_dir() or directory.is_symlink():
            continue
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(source)
            if (path.is_symlink() or not path.is_file()
                    or any(part.startswith(".") for part in relative.parts)
                    or path.suffix.lower() not in extensions):
                continue
            # Reject files reached through a symlinked ancestor as well.
            if any(parent.is_symlink() for parent in path.parents if parent != source.parent):
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            count += 1
    return count


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
    messages = json.loads((ROOT / "data/messages.json").read_text(encoding="utf-8"))
    message_errors = public_message_errors(messages)
    if message_errors:
        raise ValueError("\n".join(message_errors))
    for filename in PUBLIC_DATA:
        path = ROOT / "data" / filename
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing regular public data file: data/{filename}")
    for page in PAGES:
        if not (ROOT / page).is_file() or (ROOT / page).is_symlink():
            raise FileNotFoundError(f"Missing required page: {page}")
    if OUTPUT.is_symlink():
        raise ValueError("Refusing to replace a symlink at dist/")
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir()
    for page in PAGES:
        text = (ROOT / page).read_text(encoding="utf-8")
        (OUTPUT / page).write_text(update_page(text, base, settings, profile), encoding="utf-8")
    copy_public_assets(ROOT / "assets", OUTPUT / "assets")
    (OUTPUT / "data").mkdir()
    for filename in PUBLIC_DATA:
        shutil.copy2(ROOT / "data" / filename, OUTPUT / "data" / filename)
    (OUTPUT / ".nojekyll").touch()
    write_discovery(OUTPUT, base)
    # Keep the source checkout's discovery files in sync for direct static hosting.
    write_discovery(ROOT, base)
    count = sum(1 for path in OUTPUT.rglob("*") if path.is_file())
    print(f"Built {len(PAGES)} pages and {count} public files in {OUTPUT}")
    print(f"Public URL: {base}")


if __name__ == "__main__":
    main()
