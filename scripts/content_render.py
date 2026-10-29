"""Render CMS reports and the rider's message into the static publication.

The browser refreshes these same fields from JSON. Static output makes saved
content readable before JavaScript loads and when JavaScript is disabled.
"""
from __future__ import annotations

from html import escape
from html.parser import HTMLParser
import re
from urllib.parse import unquote, urlsplit

CATEGORIES = {"ACTIVITY": "活動報告", "RACE": "レース", "INFORMATION": "お知らせ", "MEDIA": "メディア"}
EMPTY_NEWS = ('<div class="empty-state"><span class="tiny-caps">LATEST UPDATES</span>'
              '<p>新しいお知らせを準備しています。</p>'
              '<span>レースや活動の情報を、こちらからお届けします。</span></div>')


class _Elements(HTMLParser):
    """Locate complete selected containers without mistaking a nested div."""
    def __init__(self, text, predicate):
        super().__init__(convert_charrefs=True)
        self.text = text
        self.predicate = predicate
        self.positions = [0]
        for match in re.finditer("\n", text):
            self.positions.append(match.end())
        self.active = None
        self.elements = []
        self.feed(text)

    def absolute_position(self):
        line, column = self.getpos()
        return self.positions[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if self.active:
            if tag == self.active[0]:
                self.active[5] += 1
        elif self.predicate(tag, dict(attrs)):
            start = self.absolute_position()
            opening = self.get_starttag_text()
            self.active = [tag, dict(attrs), start, start + len(opening), opening, 1]

    def handle_endtag(self, tag):
        if self.active and tag == self.active[0]:
            self.active[5] -= 1
            if not self.active[5]:
                start = self.absolute_position()
                end = self.text.index(">", start) + 1
                self.elements.append((*self.active[:5], start, end))
                self.active = None


def _rewrite(text, predicate, replacement):
    for tag, attrs, start, body_start, opening, close_start, end in reversed(_Elements(text, predicate).elements):
        body = text[body_start:close_start]
        closing = text[close_start:end]
        text = text[:start] + replacement(tag, attrs, opening, body, closing) + text[end:]
    return text


def _opening(tag, attrs):
    return "<" + tag + "".join(" " + key + ("" if value is None else '="' + escape(value, quote=True) + '"')
                                for key, value in attrs.items()) + ">"


def _safe_url(value, base):
    if not isinstance(value, str) or not value.strip() or re.search(r"[\x00-\x20\x7f\\]", value):
        return None
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if parsed.username or parsed.password:
            return None
        if parsed.scheme or parsed.netloc:
            if parsed.scheme != "https" or not parsed.netloc:
                return None
        elif parsed.path.startswith("/") or ".." in parsed.path.split("/"):
            return None
    except ValueError:
        return None
    external = bool(parsed.netloc and parsed.netloc != urlsplit(base).netloc)
    return escape(value, quote=True), external


def render_news(items, limit=0, base=""):
    if not isinstance(items, list):
        return EMPTY_NEWS
    ordered = sorted((item for item in items if isinstance(item, dict)),
                     key=lambda item: str(item.get("date", "")), reverse=True)
    visible = ordered[:limit] if limit else ordered
    if not visible:
        return EMPTY_NEWS
    rendered = []
    for item in visible:
        title = escape(str(item.get("title") or "xxx"))
        published = str(item.get("date") or "")
        category = str(item.get("category") or "INFORMATION")
        raw_link = item.get("url")
        link = _safe_url(raw_link, base) if isinstance(raw_link, str) and not re.search(r"xxx|^TBA$", raw_link, re.I) else None
        link_attrs = ''
        if link:
            url, external = link
            link_attrs = f'href="{url}"' + (' target="_blank" rel="noopener noreferrer"' if external else '')
        date_attrs = ' datetime="' + published + '"' if re.fullmatch(r"\d{4}-\d{2}-\d{2}", published) else ''
        article = '<article class="news-item"><time' + date_attrs + '>' + escape(published.replace("-", ".")) + '</time>'
        article += '<span class="news-category">' + escape(CATEGORIES.get(category.upper(), category)) + '</span>'
        article += '<h3>' + (f'<a {link_attrs}>{title}</a>' if link else title) + '</h3>'
        if link:
            article += f'<a class="news-arrow" {link_attrs} aria-label="{escape(str(item.get("title") or "ニュース"), quote=True)}の詳細">↗</a>'
        if item.get("isSample") is True:
            article += '<p class="news-sample-note">仮原稿</p>'
        description = item.get("description")
        if isinstance(description, str) and description:
            paragraphs = re.split(r"\n\s*\n", description)
            article += '<p class="news-description">' + escape(paragraphs[0] if limit else description) + '</p>'
            if limit and len(paragraphs) > 1:
                article += '<a class="news-read-more" href="news.html">活動報告・ニュースを読む →</a>'
        image = item.get("image")
        if (isinstance(image, str) and image.startswith("assets/images/")
                and not re.search(r"xxx|^TBA$", image, re.I) and _safe_url(image, base)):
            article += ('<figure class="photo-slot news-image"><picture><img src="' + escape(image, quote=True)
                        + '" alt="' + escape(str(item.get("title") or "池田優介のレース活動"), quote=True)
                        + '" width="1600" height="1067" loading="lazy" decoding="async" data-photo-image></picture></figure>')
        rendered.append(article + '</article>')
    return "".join(rendered)


def update_content_html(text, news, profile, base=""):
    """Keep CMS content in the deployed HTML synchronized with its public JSON."""
    news = news if isinstance(news, dict) else {}
    profile = profile if isinstance(profile, dict) else {}

    def news_container(tag, attrs, opening, _body, closing):
        try:
            limit = max(0, int(attrs.get("data-limit") or 0))
        except ValueError:
            limit = 0
        return opening + render_news(news.get("items"), limit, base) + closing

    text = _rewrite(text, lambda _tag, attrs: "data-news-list" in attrs, news_container)
    message = profile.get("message")
    available = isinstance(message, str) and bool(message.strip())
    text = _rewrite(text, lambda _tag, attrs: attrs.get("data-bind") == "profile.message",
                    lambda _tag, _attrs, opening, _body, closing: opening + escape(message if available else "") + closing)

    def note(tag, attrs, _opening_text, body, closing):
        attrs.pop("hidden", None)
        if profile.get("messageIsSample") is not True:
            attrs["hidden"] = None
        return _opening(tag, attrs) + body + closing

    text = _rewrite(text, lambda _tag, attrs: "data-profile-message-note" in attrs, note)

    def message_section(tag, attrs, _opening_text, body, closing):
        attrs.pop("hidden", None)
        if not available:
            attrs["hidden"] = None
        return _opening(tag, attrs) + body + closing

    return _rewrite(text, lambda _tag, attrs: "data-profile-message" in attrs, message_section)


def _gallery_image(value, base):
    """Only relative uploaded images may be delivered by the gallery."""
    if not isinstance(value, str) or not value.startswith("assets/images/"):
        return None
    if re.search(r"xxx|^TBA$", value, re.I) or not _safe_url(value, base):
        return None
    decoded = unquote(urlsplit(value).path)
    if any(part in {".", ".."} for part in decoded.split("/")) or re.search(r"[\x00-\x1f\x7f\\]", decoded):
        return None
    return escape(value, quote=True)


def _gallery_size(width, height):
    try:
        numbers = tuple(float(value) for value in (width, height))
    except (TypeError, ValueError, OverflowError):
        return None
    if any(isinstance(value, bool) for value in (width, height)):
        return None
    return tuple(int(value) for value in numbers) if all(value.is_integer() and 0 < value <= 30000 for value in numbers) else None


def update_gallery_html(text, gallery, base=""):
    """Publish the same uploaded gallery before JavaScript initializes it."""
    items = gallery.get("items", []) if isinstance(gallery, dict) else []
    rendered = []
    for index, item in enumerate(items if isinstance(items, list) else [], 1):
        if not isinstance(item, dict):
            continue
        image = _gallery_image(item.get("image"), base)
        if not image:
            continue
        caption = escape(str(item.get("caption") or f"フォトギャラリー {index:02d}"), quote=True)
        alt = escape(str(item.get("alt") or f"池田優介 フォトギャラリー {index:02d}"), quote=True)
        width, height = _gallery_size(item.get("width"), item.get("height")) or (1600, 1067)
        mobile = _gallery_image(item.get("mobileImage"), base)
        source = ""
        if mobile:
            dimensions = _gallery_size(item.get("mobileWidth"), item.get("mobileHeight"))
            size_attrs = f' width="{dimensions[0]}" height="{dimensions[1]}"' if dimensions else ""
            source = f'<source media="(max-width: 767px)" srcset="{mobile}" data-photo-source{size_attrs}>'
        rendered.append(
            f'<button type="button" class="gallery-item reveal-image" data-lightbox data-src="{image}" '
            f'data-caption="{caption}" aria-label="ギャラリー {index} を拡大：{alt}">'
            f'<figure class="photo-slot" data-photo="{image}"><picture>{source}'
            f'<img src="{image}" alt="{alt}" width="{width}" height="{height}" '
            'loading="lazy" decoding="async" data-photo-image></picture></figure>'
            f'<span class="gallery-index">{index:02d}<span aria-hidden="true">↗</span></span></button>'
        )
    body = "".join(rendered) or '<p class="quiet-empty">写真は、準備が整い次第掲載します。</p>'
    return _rewrite(text, lambda _tag, attrs: "data-gallery" in attrs,
                    lambda _tag, _attrs, opening, _body, closing: opening + body + closing)


def update_utility_contact_html(text, settings):
    """Error notices remain useful even when the content loader is omitted."""
    email = settings.get("email") if isinstance(settings, dict) else None
    valid = (isinstance(email, str)
             and re.fullmatch(r"[^\s@<>\"'?#]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", email)
             and not re.search(r"%(?:0a|0d)", email, re.I))

    def contact(_tag, _attrs, opening, body, closing):
        if not re.search(r'\bdata-contact\s*=\s*["\']email["\']', body):
            return opening + body + closing
        if not valid:
            return ""
        safe_email = escape(email, quote=True)
        return opening + f'お急ぎの場合：<span data-contact="email"><a href="mailto:{safe_email}">{safe_email}</a></span>' + closing

    return _rewrite(text, lambda tag, attrs: tag == "p" and "fine-print" in attrs.get("class", "").split(), contact)
