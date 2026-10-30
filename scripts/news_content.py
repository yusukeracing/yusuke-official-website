"""Validate and publish plain-text activity reports with ordered photo blocks.

`published: false` excludes an entry from the site artifact. It cannot make
content in a public Git repository or its history private.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from html import escape
import re
from urllib.parse import unquote, urljoin, urlsplit

from content_render import CATEGORIES, EMPTY_NEWS, _rewrite

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _text(value, field, limit=100000):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"news: {field} must be text up to {limit} characters")
    return value.strip()


def image_path(value):
    value = _text(value, "image path", 4096)
    if value.lower() in {"", "xxx", "tba"}:
        return ""
    decoded = unquote(value)
    parsed = urlsplit(value)
    if (not value.startswith(("assets/images/", "assets/optimized/")) or parsed.scheme or parsed.netloc
            or parsed.query or parsed.fragment
            or any(part in {"", ".", ".."} for part in decoded.split("/"))
            or re.search(r"[\x00-\x1f\x7f\\]", decoded)
            or not re.search(r"\.(?:jpe?g|png|webp|avif|gif)$", parsed.path, re.I)):
        raise ValueError("news: images must be relative files under assets/images/ or the generated assets/optimized/")
    return value


def related_url(value):
    value = _text(value, "related URL", 4096)
    if value.lower() in {"", "xxx", "tba"}:
        return ""
    parsed = urlsplit(value)
    if (parsed.username or parsed.password or re.search(r"[\x00-\x20\x7f\\]", value)
            or (parsed.scheme or parsed.netloc) and (parsed.scheme != "https" or not parsed.netloc)
            or not parsed.scheme and (value.startswith("/") or ".." in unquote(parsed.path).split("/"))):
        raise ValueError("news: related URL must be HTTPS or a safe relative page")
    return value


def _dimension(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return int(number) if number.is_integer() and 0 < number <= 30000 else None
    except (TypeError, ValueError, OverflowError):
        return None


def normalize_news(data):
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("news: items must be an array")
    result, seen = [], set()
    for index, source in enumerate(data["items"], 1):
        if not isinstance(source, dict):
            raise ValueError(f"news item {index}: expected an object")
        slug = _text(source.get("slug"), "slug", 80)
        if not SLUG.fullmatch(slug) or slug in seen:
            raise ValueError(f"news item {index}: slug must be unique lowercase letters/numbers separated by hyphens")
        seen.add(slug)
        published = source.get("published", True)
        if type(published) is not bool:
            raise ValueError(f"news {slug}: published must be a boolean")
        title = _text(source.get("title"), "title", 300)
        if not title:
            raise ValueError(f"news {slug}: title is required")
        published_date = _text(source.get("date"), "date", 10)
        try:
            if date.fromisoformat(published_date).isoformat() != published_date:
                raise ValueError()
        except ValueError:
            raise ValueError(f"news {slug}: date must use YYYY-MM-DD") from None
        image = image_path(source.get("image"))
        image_alt = _text(source.get("imageAlt"), "thumbnail alt", 1000)
        if image and not image_alt:
            raise ValueError(f"news {slug}: thumbnail alternative text is required when an image is selected")
        raw_blocks = source.get("blocks", [])
        if raw_blocks is None:
            raw_blocks = []
        if not isinstance(raw_blocks, list):
            raise ValueError(f"news {slug}: blocks must be an array")
        blocks = []
        for block in raw_blocks:
            if not isinstance(block, dict) or block.get("type") not in {"text", "image"}:
                raise ValueError(f"news {slug}: each block must have type text or image")
            if block["type"] == "text":
                text = _text(block.get("text"), "block text")
                if text:
                    blocks.append({"type": "text", "text": text})
            else:
                photo = image_path(block.get("image"))
                alt = _text(block.get("alt"), "photo alternative text", 1000)
                if not photo or not alt:
                    raise ValueError(f"news {slug}: a photo block needs an image and alternative text")
                blocks.append({"type": "image", "image": photo, "alt": alt,
                               "width": _dimension(block.get("width")), "height": _dimension(block.get("height")),
                               "caption": _text(block.get("caption"), "photo caption", 2000)})
        result.append({"slug": slug, "published": published, "date": published_date,
                       "category": _text(source.get("category") or "ACTIVITY", "category", 60).upper(),
                       "title": title, "description": _text(source.get("description"), "description"),
                       "image": image, "imageAlt": image_alt,
                       "imageWidth": _dimension(source.get("imageWidth")), "imageHeight": _dimension(source.get("imageHeight")),
                       "imageCaption": _text(source.get("imageCaption"), "thumbnail caption", 2000),
                       "url": related_url(source.get("url")), "featured": source.get("featured") is True,
                       "isSample": source.get("isSample") is True, "blocks": blocks})
    return {"items": sorted(result, key=lambda item: item["date"], reverse=True)}


def public_news(data):
    return {"items": [item for item in normalize_news(data)["items"] if item["published"]]}


def article_filename(item):
    slug = item.get("slug", "")
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        raise ValueError("news: invalid article slug")
    return f"article-{slug}.html"


def _paragraphs(text):
    return "".join('<p class="article-paragraph">' + escape(part) + '</p>'
                   for part in re.split(r"\n\s*\n", text) if part.strip())


def _photo(path, alt, caption="", class_name="article-photo"):
    # The publication image pipeline replaces these dimensions with actual values.
    return (f'<figure class="{class_name}"><img src="{escape(path, quote=True)}" '
            f'alt="{escape(alt, quote=True)}" width="1600" height="1067" loading="lazy" decoding="async">'
            + (f'<figcaption>{escape(caption)}</figcaption>' if caption else '') + '</figure>')


def render_news_list(items, limit=0):
    items = [item for item in items if item.get("published", True)]
    if limit:
        items = items[:limit]
    if not items:
        return EMPTY_NEWS
    output = []
    for item in items:
        href = escape(article_filename(item), quote=True)
        category = escape(CATEGORIES.get(item["category"], item["category"]))
        description = re.split(r"\n\s*\n", item["description"])[0]
        article = (f'<article class="news-item" data-news-category="{escape(item["category"], quote=True)}">'
                   f'<time datetime="{item["date"]}">{item["date"].replace("-", ".")}</time>'
                   f'<span class="news-category">{category}</span>'
                   f'<h3><a href="{href}">{escape(item["title"])}</a></h3>')
        if item["isSample"]:
            article += '<p class="news-sample-note">仮原稿</p>'
        if description:
            article += f'<p class="news-description">{escape(description)}</p>'
        if item["image"]:
            article += _photo(item["image"], item["imageAlt"], item["imageCaption"], "news-thumbnail")
        article += f'<a class="news-read-more" href="{href}">記事を読む →</a></article>'
        output.append(article)
    return "".join(output)


def update_news_html(text, news, base=""):
    items = public_news(news)["items"]
    def replace(_tag, attrs, opening, _body, closing):
        try:
            limit = max(0, int(attrs.get("data-limit") or 0))
        except ValueError:
            limit = 0
        return opening + render_news_list(items, limit) + closing
    return _rewrite(text, lambda _tag, attrs: "data-news-list" in attrs, replace)


def render_article(item):
    category = escape(CATEGORIES.get(item["category"], item["category"]))
    text = (f'<article class="activity-article" data-article-slug="{escape(item["slug"], quote=True)}">'
            '<header class="article-heading"><p class="eyebrow">ACTIVITY &amp; NEWS</p>'
            f'<p class="article-meta"><time datetime="{item["date"]}">{item["date"].replace("-", ".")}</time> / {category}</p>'
            f'<h1>{escape(item["title"])}</h1></header>')
    if item["isSample"]:
        text += '<p class="news-sample-note">仮原稿</p>'
    if item["image"]:
        text += _photo(item["image"], item["imageAlt"], item["imageCaption"])
    text += '<div class="article-body">' + _paragraphs(item["description"])
    for block in item["blocks"]:
        text += (_paragraphs(block["text"]) if block["type"] == "text" else
                 _photo(block["image"], block["alt"], block["caption"]))
    text += '</div>'
    if item["url"]:
        parsed = urlsplit(item["url"])
        attrs = ' target="_blank" rel="noopener noreferrer"' if parsed.netloc else ''
        text += f'<p><a class="text-link" href="{escape(item["url"], quote=True)}"{attrs}>関連ページを見る ↗</a></p>'
    return text + '<p class="article-back"><a class="text-link" href="news.html">活動報告一覧へ戻る ←</a></p></article>'


def generate_article_pages(template, news, base):
    pages = {}
    for item in public_news(news)["items"]:
        filename = article_filename(item)
        text = _rewrite(template, lambda tag, attrs: tag == "main" and attrs.get("id") == "main",
                        lambda _tag, _attrs, opening, _body, closing:
                            opening + '<section class="wrap section-space article-page"><p class="news-load-status" data-news-load-status role="status" aria-live="polite"></p>' + render_article(item) + '</section>' + closing)
        title = item["title"] + " | 池田優介"
        description = re.sub(r"\s+", " ", item["description"]).strip()[:160] or item["title"]
        text = re.sub(r"<title>.*?</title>", lambda _: '<title>' + escape(title) + '</title>', text, flags=re.S)
        text = re.sub(r'(<link\b[^>]*\brel="canonical"[^>]*\bhref=")[^"]+',
                      lambda match: match[1] + escape(urljoin(base, filename), quote=True), text)
        def meta(match):
            tag = match.group()
            identity = re.search(r'\b(?:name|property)="([^"]+)"', tag)
            if not identity:
                return tag
            key = identity[1]
            values = {"description": description, "og:description": description, "og:title": title,
                      "og:url": urljoin(base, filename), "og:type": "article"}
            if item["image"]:
                values["og:image"] = urljoin(base, item["image"])
            if key not in values:
                return tag
            return re.sub(r'\bcontent="[^"]*"', lambda _: 'content="' + escape(values[key], quote=True) + '"', tag)
        text = re.sub(r"<meta\b[^>]*>", meta, text, flags=re.S)
        pages[filename] = text
    return pages


def render_article_page(template, item, base):
    """Render one validated published item; useful to the publication builder."""
    return generate_article_pages(template, {"items": [item]}, base)[article_filename(item)]
