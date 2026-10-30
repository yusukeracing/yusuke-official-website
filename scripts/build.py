#!/usr/bin/env python3
"""Create the GitHub Pages artifact; no third-party build tools are required."""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
from datetime import date
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from html import escape, unescape
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

from content_render import update_content_html, update_gallery_html, update_utility_contact_html
from social_links import normalize_social_links, update_social_html
from media_assets import MediaPipeline
from news_content import public_news, article_filename, update_news_html, generate_article_pages

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist"
PUBLIC_PAGES = ("index.html", "profile.html", "race.html", "news.html", "sponsor.html",
                "support.html", "contact.html", "partners.html", "messages.html")
PAGES = PUBLIC_PAGES + ("404.html", "maintenance.html")
PUBLIC_DATA = ("site.json", "profile.json", "races.json", "news.json",
               "sponsors.json", "gallery.json", "messages.json", "media-manifest.json", "publication.json")
SOURCE_DATA = tuple(name for name in PUBLIC_DATA if name not in {"media-manifest.json", "publication.json"})
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
    return text


def without_content_loader(text: str) -> str:
    """The compiled error/maintenance page has no runtime CMS data to fetch."""
    def keep_script(match):
        src = re.search(r'\bsrc\s*=\s*["\']([^"\']+)["\']', match[1], re.I)
        if src and urlsplit(unescape(src[1])).path.rsplit("/", 1)[-1] in {"data-loader.js", "social-links.js", "news.js", "community.js"}:
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
        if folder == "images":
            continue  # Source photographs are retained in Git, not bulk-copied to the web artifact.
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


def read_source_json(filename: str) -> dict:
    """Read an allowed CMS source file with actionable, content-free failures."""
    if filename not in SOURCE_DATA:
        raise ValueError("Only declared CMS source JSON files may be read")
    directory = ROOT / "data"
    path = directory / filename
    display = "data/" + filename
    if directory.is_symlink() or path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing regular public data file: {display}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{display}: invalid UTF-8 at byte {error.start}") from None
    except OSError:
        raise ValueError(f"{display}: source file could not be read") from None
    if CONFLICT_MARKER.search(text):
        raise ValueError(f"{display}: unresolved merge conflict markers must be removed before publishing")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        # File and position are useful to an editor. Do not echo article text,
        # credentials or other source values into a public workflow log.
        raise ValueError(f"{display}: invalid JSON at line {error.lineno}, column {error.colno}") from None
    if not isinstance(value, dict):
        raise ValueError(f"{display}: top-level JSON must be an object")
    return value


def site_url() -> str:
    value = read_source_json("site.json").get("url")
    error = "data/site.json: url must be the public HTTPS site URL without credentials, query or fragment"
    if not isinstance(value, str):
        raise ValueError(error)
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise ValueError(error) from None
    if (parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password
            or parsed.query or parsed.fragment or "xxx" in parsed.netloc):
        raise ValueError(error)
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
            elif (not parsed_image.path.startswith(("assets/images/", "assets/optimized/"))
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


def write_discovery(destination: Path, base: str, maintenance: bool = False, articles=()) -> None:
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ET.register_namespace("", namespace)
    root = ET.Element(f"{{{namespace}}}urlset")
    for page in (() if maintenance else (*PUBLIC_PAGES, *articles)):
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


def publication_id(source_pages, data, root):
    """Content identifier stays stable across rebuilds of the same publication."""
    fingerprint = deepcopy(data)
    if not fingerprint.get("site", {}).get("maintenanceEnabled"):
        fingerprint.get("site", {}).pop("maintenanceMessage", None)
    digest = hashlib.sha256(json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode())
    for name, text in sorted(source_pages.items()):
        digest.update(name.encode())
        digest.update(text.encode())
    for relative in ("requirements-build.txt", "scripts/build.py", "scripts/media_assets.py",
                     "scripts/content_render.py", "scripts/news_content.py", "scripts/social_links.py"):
        file = root / relative
        if file.is_file() and not file.is_symlink():
            digest.update(relative.encode())
            digest.update(file.read_bytes())
    for directory in ("css", "js", "icons"):
        for file in sorted((root / "assets" / directory).glob("*")):
            if file.is_file() and not file.is_symlink():
                digest.update(file.name.encode())
                digest.update(file.read_bytes())
    return digest.hexdigest()[:20]


def publication_markup(text, identifier):
    tag = '<meta name="publication-id" content="' + identifier + '" />'
    if re.search(r'<meta\b[^>]*\bname=["\']publication-id["\']', text, re.I):
        text = re.sub(r'<meta\b[^>]*\bname=["\']publication-id["\'][^>]*>', tag, text, flags=re.I)
    else:
        text = text.replace('</head>', '    ' + tag + '\n  </head>', 1)
    def version(match):
        value = unescape(match[3])
        parsed = urlsplit(value)
        if parsed.path.startswith(("assets/css/", "assets/js/")) and parsed.path.endswith((".css", ".js")):
            value = parsed.path + '?v=' + identifier
        return match[1] + match[2] + escape(value, quote=True) + match[2]
    return re.sub(r'(\b(?:src|href)\s*=\s*)(["\'])(.*?)\2', version, text, flags=re.I | re.S)


def build_site(*, normal_preview=False):
    resolved_root, resolved_output = ROOT.resolve(), OUTPUT.resolve()
    if resolved_output == resolved_root or resolved_root.is_relative_to(resolved_output):
        raise ValueError("Output directory must not replace the source checkout or one of its parents")
    if OUTPUT.exists() and not OUTPUT.is_dir():
        raise ValueError("Output path must be a directory")
    base = site_url()
    raw = {Path(name).stem: read_source_json(name) for name in SOURCE_DATA}
    settings = raw["site"]
    maintenance = maintenance_enabled(settings)
    if normal_preview:
        settings = {**settings, "maintenanceEnabled": False}
        raw["site"] = settings
        maintenance = False
    message_errors = public_message_errors(raw["messages"])
    if message_errors:
        raise ValueError("\n".join(message_errors))
    # Validate and filter articles before media discovery: unpublished photographs
    # and text must never enter the site artifact through the JSON copy step.
    raw["news"] = public_news(raw["news"])
    source_pages = {}
    for page in (*PAGES, "article-template.html"):
        path = ROOT / page
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"Missing required page/template: {page}")
        text = path.read_text(encoding="utf-8")
        if CONFLICT_MARKER.search(text):
            raise ValueError(f"{page}: unresolved merge conflict markers must be removed before publishing")
        source_pages[page] = text
    if OUTPUT.is_symlink():
        raise ValueError("Refusing to replace a symlink at the output path")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # Complete the artifact before replacing a previously valid build.
    with tempfile.TemporaryDirectory(prefix=".site-build-", dir=OUTPUT.parent) as folder:
        stage = Path(folder)
        media = MediaPipeline(ROOT, stage, base)
        published = media.rewrite_data(raw)
        published["site"]["socials"] = normalize_social_links(settings.get("socials"))
        identifier = publication_id(source_pages, published, ROOT)
        pages = {}
        for page in PAGES:
            text = update_page(source_pages[page], base, published["site"], published["profile"])
            text = update_content_html(text, published["news"], published["profile"], base)
            text = update_news_html(text, published["news"], base)
            text = update_gallery_html(text, raw["gallery"], base)
            if page in {"404.html", "maintenance.html"}:
                text = update_utility_contact_html(text, settings)
            if page == "maintenance.html":
                text = update_maintenance_message(text, settings)
            pages[page] = media.rewrite_html(text, published)
        # Configure common SEO/CSP before the article module writes item-specific
        # title, excerpt, canonical and OGP information.
        template = update_page(source_pages["article-template.html"], base, published["site"], published["profile"])
        articles = generate_article_pages(template, published["news"], base)
        for page, text in articles.items():
            pages[page] = media.rewrite_html(text, published)
        if maintenance:
            template = pages["maintenance.html"]
            pages = {page: without_content_loader(maintenance_page(template, page, base)) for page in pages}
        pages = {name: publication_markup(text, identifier) for name, text in pages.items()}
        pages["404.html"] = absolute_error_references(without_content_loader(pages["404.html"]), base)
        for page, text in pages.items():
            (stage / page).write_text(text, encoding="utf-8")
        copy_public_assets(ROOT / "assets", stage / "assets")
        media.copy_runtime_fallbacks()
        (stage / "data").mkdir(exist_ok=True)
        for filename in SOURCE_DATA:
            (stage / "data" / filename).write_text(json.dumps(published[Path(filename).stem], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        media.write_manifest()
        publication = {"version": 1, "contentId": identifier, "url": base,
                       "maintenanceEnabled": maintenance, "pages": list(pages),
                       "articlePages": list(articles), "sourcePhotosPublished": False}
        (stage / "data/publication.json").write_text(json.dumps(publication, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (stage / ".nojekyll").touch()
        write_discovery(stage, base, maintenance, tuple(articles))
        previous = stage.with_name(stage.name + "-previous")
        if OUTPUT.exists():
            os.replace(OUTPUT, previous)
        try:
            os.replace(stage, OUTPUT)
        except OSError:
            if previous.exists():
                os.replace(previous, OUTPUT)
            raise
        if previous.exists():
            shutil.rmtree(previous)
    count = sum(1 for path in OUTPUT.rglob("*") if path.is_file())
    print(f"Built {len(pages)} pages and {count} public files in {OUTPUT}")
    print(f"Public URL: {base}")
    print("Maintenance mode: " + ("ON (all HTML URLs show the notice)" if maintenance else "OFF"))
    print("Publication: " + identifier)
    if normal_preview:
        print("Normal preview only: the CMS maintenance setting was not changed.")
    return publication


def main(argv=None):
    global OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Output directory (default: dist)")
    parser.add_argument("--normal-preview", action="store_true", help="Build a normal-site review artifact without changing the CMS maintenance setting")
    args = parser.parse_args([] if argv is None else argv)
    previous_output = OUTPUT
    try:
        if args.output is not None:
            OUTPUT = args.output.resolve()
        return build_site(normal_preview=args.normal_preview)
    finally:
        OUTPUT = previous_output


if __name__ == "__main__":
    main(sys.argv[1:])
