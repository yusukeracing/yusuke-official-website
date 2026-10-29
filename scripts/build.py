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

from content_render import update_content_html
from social_links import normalize_social_links, update_social_html

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
DEFAULT_MAINTENANCE_MESSAGE = "現在、Webサイトのメンテナンスを行っています。\nご不便をおかけしますが、公開再開までしばらくお待ちください。"
CONFLICT_MARKER = re.compile(r"^(?:<<<<<<< |=======\s*$|>>>>>>> )", re.M)


def maintenance_enabled(settings: dict) -> bool:
    value = settings.get("maintenanceEnabled", False)
    if type(value) is not bool:
        raise ValueError("data/site.json: maintenanceEnabled must be true or false")
    return value


def update_maintenance_message(text: str, settings: dict) -> str:
    value = settings.get("maintenanceMessage", DEFAULT_MAINTENANCE_MESSAGE)
    if not isinstance(value, str) or len(value) > 4000:
        raise ValueError("data/site.json: maintenanceMessage must be text up to 4000 characters")
    value = value.strip() or DEFAULT_MAINTENANCE_MESSAGE
    content = "<br />".join(escape(line) for line in value.splitlines())
    return re.sub(r'(<p\b[^>]*\bdata-maintenance-message\b[^>]*>).*?(</p\s*>)',
                  lambda match: match[1] + content + match[2], text, flags=re.I | re.S)


def maintenance_page(template: str, page: str, base: str) -> str:
    """Serve the notice at every existing URL without relying on JavaScript."""
    text = template
    canonical = urljoin(base, "" if page == "index.html" else page)
    text = CANONICAL.sub(lambda match: match[1] + escape(canonical, quote=True), text)
    text = re.sub(r'(<meta\b[^>]*\bproperty=["\']og:url["\'][^>]*\bcontent=["\'])[^"\']+',
                  lambda match: match[1] + escape(canonical, quote=True), text, flags=re.I)
    text = re.sub(r'(<body\b[^>]*)(>)', r'\1 data-maintenance-mode="true"\2', text, count=1, flags=re.I)
    # Do not invite visitors to navigate between identical maintenance notices.
    text = re.sub(r'<noscript\b[^>]*>.*?</noscript\s*>', "", text, flags=re.I | re.S)
    text = re.sub(r'<nav\b[^>]*>.*?</nav\s*>', "", text, flags=re.I | re.S)
    text = re.sub(r'<button\b[^>]*\bclass=["\']menu-toggle["\'][^>]*>.*?</button\s*>', "", text, flags=re.I | re.S)
    text = re.sub(r'<div\b[^>]*\bclass=["\']footer-directory["\'][^>]*>.*?</div\s*>', "", text, flags=re.I | re.S)
    text = re.sub(r'(<a\b[^>]*\bhref=["\'])index\.html(["\'][^>]*\bclass=["\']brand["\'])',
                  r'\1#main\2', text, flags=re.I)
    # Email information is configured separately; omit the unconfigured prompt.
    text = re.sub(r'<p\b[^>]*\bclass=["\']fine-print["\'][^>]*>\s*お急ぎの場合：.*?</p\s*>', "", text, flags=re.I | re.S)
    return text


def without_content_loader(text: str) -> str:
    """The compiled error/maintenance page has no runtime CMS data to fetch."""
    def keep_script(match):
        src = re.search(r'\bsrc\s*=\s*["\']([^"\']+)["\']', match[1], re.I)
        if src and urlsplit(unescape(src[1])).path.rsplit("/", 1)[-1] in {"data-loader.js", "social-links.js"}:
            return ""
        return match.group(0)
    return SCRIPT.sub(keep_script, text)


def absolute_error_references(text: str, base: str) -> str:
    """An error served at /unknown/nested/ must load the site's real assets."""
    def absolute(value):
        value = unescape(value)
        parsed = urlsplit(value)
        if not value or value.startswith("#") or parsed.scheme or parsed.netloc:
            return escape(value, quote=True)
        return escape(urljoin(base, value), quote=True)

    text = re.sub(r'(\b(?:src|href|poster)\s*=\s*)(["\'])(.*?)\2',
                  lambda match: match[1] + match[2] + absolute(match[3]) + match[2], text, flags=re.I | re.S)

    def sources(match):
        values = []
        for source in unescape(match[3]).split(","):
            parts = source.strip().split()
            if parts:
                values.append(" ".join([absolute(parts[0]), *parts[1:]]))
        return match[1] + match[2] + ", ".join(values) + match[2]

    return re.sub(r'(\bsrcset\s*=\s*)(["\'])(.*?)\2', sources, text, flags=re.I | re.S)


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
    if settings is not None:
        text = update_social_html(text, normalize_social_links(settings.get("socials")))
    return text


def write_discovery(destination: Path, base: str, maintenance: bool = False) -> None:
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ET.register_namespace("", namespace)
    root = ET.Element(f"{{{namespace}}}urlset")
    for page in (() if maintenance else PUBLIC_PAGES):
        item = ET.SubElement(root, f"{{{namespace}}}url")
        ET.SubElement(item, f"{{{namespace}}}loc").text = urljoin(base, "" if page == "index.html" else page)
    ET.indent(root)
    ET.ElementTree(root).write(destination / "sitemap.xml", encoding="utf-8", xml_declaration=True)
    path = urlsplit(base).path
    robots = "User-agent: *\nAllow: /\n"
    if not maintenance:
        robots += f"Disallow: {path}maintenance.html\nDisallow: {path}404.html\n"
    robots += f"\nSitemap: {base}sitemap.xml\n"
    (destination / "robots.txt").write_text(robots, encoding="utf-8")


def main() -> None:
    base = site_url()
    settings = json.loads((ROOT / "data/site.json").read_text(encoding="utf-8"))
    maintenance = maintenance_enabled(settings)
    profile = json.loads((ROOT / "data/profile.json").read_text(encoding="utf-8"))
    news = json.loads((ROOT / "data/news.json").read_text(encoding="utf-8"))
    messages = json.loads((ROOT / "data/messages.json").read_text(encoding="utf-8"))
    message_errors = public_message_errors(messages)
    if message_errors:
        raise ValueError("\n".join(message_errors))
    for filename in PUBLIC_DATA:
        path = ROOT / "data" / filename
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing regular public data file: data/{filename}")
    source_pages = {}
    for page in PAGES:
        if not (ROOT / page).is_file() or (ROOT / page).is_symlink():
            raise FileNotFoundError(f"Missing required page: {page}")
        text = (ROOT / page).read_text(encoding="utf-8")
        if CONFLICT_MARKER.search(text):
            raise ValueError(f"{page}: unresolved merge conflict markers must be removed before publishing")
        source_pages[page] = text
    if OUTPUT.is_symlink():
        raise ValueError("Refusing to replace a symlink at dist/")
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir()
    for page in PAGES:
        text = update_page(source_pages[page], base, settings, profile)
        text = update_content_html(text, news, profile, base)
        if page == "maintenance.html":
            text = update_maintenance_message(text, settings)
        (OUTPUT / page).write_text(text, encoding="utf-8")
    if maintenance:
        template = (OUTPUT / "maintenance.html").read_text(encoding="utf-8")
        for page in PAGES:
            text = without_content_loader(maintenance_page(template, page, base))
            (OUTPUT / page).write_text(text, encoding="utf-8")
    # GitHub Pages can serve this document from an arbitrarily nested URL.
    error_page = OUTPUT / "404.html"
    error_page.write_text(absolute_error_references(without_content_loader(
        error_page.read_text(encoding="utf-8")), base), encoding="utf-8")
    copy_public_assets(ROOT / "assets", OUTPUT / "assets")
    (OUTPUT / "data").mkdir()
    for filename in PUBLIC_DATA:
        shutil.copy2(ROOT / "data" / filename, OUTPUT / "data" / filename)
    # The delivered HTML and runtime JSON use the same canonical profile links.
    published_settings = {**settings, "socials": normalize_social_links(settings.get("socials"))}
    (OUTPUT / "data/site.json").write_text(
        json.dumps(published_settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / ".nojekyll").touch()
    write_discovery(OUTPUT, base, maintenance)
    # Keep the source checkout's discovery files in sync for direct static hosting.
    write_discovery(ROOT, base, maintenance)
    count = sum(1 for path in OUTPUT.rglob("*") if path.is_file())
    print(f"Built {len(PAGES)} pages and {count} public files in {OUTPUT}")
    print(f"Public URL: {base}")
    print("Maintenance mode: " + ("ON (all HTML URLs show the notice)" if maintenance else "OFF"))


if __name__ == "__main__":
    main()
