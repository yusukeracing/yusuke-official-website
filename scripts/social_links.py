"""Normalize public social profiles consistently with assets/js/social-links.js."""
from __future__ import annotations

from html import escape
import re
from urllib.parse import parse_qs, urlsplit

LABELS = {"instagram": "Instagram", "x": "X", "facebook": "Facebook"}
HOSTS = {
    "instagram": {"instagram.com", "www.instagram.com", "m.instagram.com"},
    "x": {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"},
    "facebook": {"facebook.com", "www.facebook.com", "m.facebook.com", "mbasic.facebook.com"},
}
RESERVED = {
    "instagram": {"p", "reel", "reels", "stories", "direct", "explore", "accounts"},
    "x": {"home", "intent", "i", "search", "settings", "compose", "hashtag", "messages", "notifications", "explore", "login", "signup", "share"},
    "facebook": {"login", "login.php", "share", "sharer.php", "dialog", "reel", "reels", "groups", "messages", "events", "plugins", "watch", "help", "reg", "settings"},
}
PLACEHOLDERS = {"", "xxx", "@xxx", "tba"}
PATTERNS = {"instagram": r"[A-Za-z0-9._]{1,30}", "x": r"[A-Za-z0-9_]{1,15}", "facebook": r"[A-Za-z0-9._-]{1,100}"}


def placeholder(value: object) -> bool:
    return value is None or isinstance(value, str) and value.strip().lower() in PLACEHOLDERS


def username(platform: str, value: str) -> bool:
    return bool(re.fullmatch(PATTERNS[platform], value)) and value not in {".", ".."} and not placeholder(value) and value.lower() not in RESERVED[platform]


def facebook_handle(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if placeholder(value) or len(value) > 100 or re.search(r"[\x00-\x1f\x7f<>]", value) or "://" in value:
        return ""
    return value


def official_placeholder_url(platform: str, value: object) -> bool:
    """Existing default URLs may still be present when only a handle is edited."""
    if not isinstance(value, str):
        return False
    value = value.strip()
    authority = re.match(r"https://([^/?#]+)", value, re.I)
    if (not authority or "%" in authority[1] or "@" in authority[1]
            or not value.isascii() or re.search(r"[\x00-\x20\x7f\\]", value)
            or re.search(r"/(?:\.|\.\.)(?:/|[?#]|$)", value)):
        return False
    try:
        url = urlsplit(value)
        return (url.scheme.lower() == "https" and url.hostname in HOSTS[platform]
                and url.username is None and url.password is None
                and url.port in {None, 443} and url.path.strip("/").lower() == "xxx")
    except ValueError:
        return False


def normalize_social_links(items: object) -> list[dict[str, str]]:
    result = []
    seen = set()
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("platform"), str):
            continue
        platform = item["platform"].strip().lower()
        if platform not in LABELS or platform in seen:
            continue
        raw = item.get("url")
        if placeholder(raw) or official_placeholder_url(platform, raw):
            if platform == "facebook" and (placeholder(item.get("handle")) or item.get("handle") == "アカウント準備中"):
                result.append({"platform": platform, "label": LABELS[platform], "handle": "アカウント準備中", "url": "https://www.facebook.com/"})
                seen.add(platform)
                continue
            handle = item.get("handle", "")
            if not isinstance(handle, str):
                continue
            name = handle.strip().removeprefix("@")
            if not username(platform, name):
                continue
            raw = f"https://{platform if platform != 'x' else 'x'}.com/{name}"
        if not isinstance(raw, str):
            continue
        raw = raw.strip()
        authority = re.match(r"https://([^/?#]+)", raw, re.I)
        if (not authority or "%" in authority[1] or "@" in authority[1] or not raw.isascii()
                or re.search(r"[\x00-\x20\x7f\\]", raw)
                or re.search(r"/(?:\.|\.\.)(?:/|[?#]|$)", raw)):
            continue
        try:
            url = urlsplit(raw)
            if (url.scheme.lower() != "https" or url.hostname not in HOSTS[platform]
                    or url.username or url.password or url.port not in {None, 443}):
                continue
        except ValueError:
            continue
        path = url.path.strip("/")
        if platform == "facebook" and path == "":
            result.append({"platform": platform, "label": LABELS[platform], "handle": "アカウント準備中", "url": "https://www.facebook.com/"})
            seen.add(platform)
            continue
        if platform == "facebook" and path == "profile.php":
            values = parse_qs(url.query, keep_blank_values=True).get("id", [])
            if len(values) != 1 or not re.fullmatch(r"[0-9]+", values[0]):
                continue
            name = values[0]
            canonical = f"https://www.facebook.com/profile.php?id={name}"
        elif platform == "facebook" and re.fullmatch(r"people/[A-Za-z0-9._-]+/[0-9]+", path):
            name = path.split("/")[1]
            if placeholder(name):
                continue
            canonical = f"https://www.facebook.com/{path}/"
        else:
            if not username(platform, path):
                continue
            name = path
            canonical = (f"https://www.instagram.com/{name}/" if platform == "instagram" else
                         f"https://x.com/{name}" if platform == "x" else f"https://www.facebook.com/{name}/")
        handle = facebook_handle(item.get("handle")) if platform == "facebook" else ""
        result.append({"platform": platform, "label": LABELS[platform], "handle": handle or "@" + name, "url": canonical})
        seen.add(platform)
    return result


def render_social_links(items: list[dict[str, str]], mode: str) -> str:
    if not items:
        return '<p class="social-unavailable">SNS情報は準備中です。</p>' if mode == "full" else ""
    rendered = []
    for item in items:
        platform, label, handle, url = (escape(item[key], quote=True) for key in ("platform", "label", "handle", "url"))
        icon = f'<svg aria-hidden="true"><use href="assets/icons/brands.svg#{platform}"></use></svg>'
        content = icon
        if mode == "full":
            content += f'<span>{label} <small>{handle}</small></span><span aria-hidden="true">↗</span>'
        destination = "Facebookトップ・" if item["platform"] == "facebook" and item["url"] == "https://www.facebook.com/" else ""
        accessible_label = f"{label} {handle}（{destination}新しいタブで開く）"
        rendered.append(f'<a href="{url}" target="_blank" rel="noopener noreferrer" data-track="social_click" data-social-platform="{platform}" title="{accessible_label}" aria-label="{accessible_label}">{content}</a>')
    return "".join(rendered)


def update_social_html(text: str, items: list[dict[str, str]]) -> str:
    # Social containers contain links/SVG/spans, never nested divs.
    pattern = re.compile(r'(<div\b[^>]*\bdata-socials\s*=\s*(["\'])(icons|full)\2[^>]*>).*?(</div\s*>)', re.I | re.S)
    return pattern.sub(lambda match: match[1] + render_social_links(items, match[3].lower()) + match[4], text)
