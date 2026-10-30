#!/usr/bin/env python3
"""Activity-report publication regressions; no external CMS account is used."""
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
import unittest

from news_content import (article_filename, generate_article_pages, image_path,
                          normalize_news, public_news, render_article_page,
                          update_news_html)

ROOT = Path(__file__).resolve().parents[1]


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def article(**changes):
    value = {"slug": "sugo-report-2026", "published": True, "date": "2026-10-30",
             "category": "ACTIVITY", "title": "活動報告", "description": "冒頭です。\n\n第二段落です。",
             "image": "assets/images/yusuke.gallery_09.jpg", "imageAlt": "走行中のライダー",
             "imageCaption": "撮影者クレジット", "blocks": [
                 {"type": "text", "text": "写真の前の文章。"},
                 {"type": "image", "image": "assets/images/yusuke.gallery_06.jpg", "alt": "マシンとライダー", "caption": "縦写真の説明"},
                 {"type": "text", "text": "二枚目の写真の前。"},
                 {"type": "image", "image": "assets/images/yusuke.gallery_09.jpg", "alt": "サーキット走行", "caption": "横写真の説明"},
             ]}
    value.update(changes)
    return value


class NewsPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = (ROOT / "article-template.html").read_text()
        cls.base = "https://example.test/racing/"

    def test_create_edit_change_photos_delete_and_publication_switch(self):
        data = {"items": [article()]}
        filename = "article-sugo-report-2026.html"
        pages = generate_article_pages(self.template, data, self.base)
        self.assertEqual(set(pages), {filename})
        self.assertIn("活動報告", pages[filename])
        data["items"][0]["title"] = "更新したタイトル"
        data["items"][0]["blocks"][1]["image"] = "assets/images/yusuke.gallery_07.jpg"
        pages = generate_article_pages(self.template, data, self.base)
        self.assertIn("更新したタイトル", pages[filename])
        self.assertIn("assets/images/yusuke.gallery_07.jpg", pages[filename])
        data["items"][0]["published"] = False
        self.assertEqual(public_news(data), {"items": []})
        self.assertEqual(generate_article_pages(self.template, data, self.base), {})
        data["items"][0]["published"] = True
        self.assertIn(filename, generate_article_pages(self.template, data, self.base))
        data["items"].clear()
        self.assertEqual(generate_article_pages(self.template, data, self.base), {})

    def test_thumbnail_two_photos_alt_captions_and_order(self):
        item = public_news({"items": [article()]})["items"][0]
        text = render_article_page(self.template, item, self.base)
        images = [attrs for tag, attrs in Tags(text).tags if tag == "img" and attrs.get("src")]
        self.assertEqual(len(images), 3)
        self.assertEqual([image["alt"] for image in images], ["走行中のライダー", "マシンとライダー", "サーキット走行"])
        self.assertTrue(all(image.get("loading") == "lazy" for image in images))
        self.assertLess(text.index("写真の前の文章。"), text.index("縦写真の説明"))
        self.assertLess(text.index("縦写真の説明"), text.index("二枚目の写真の前。"))
        self.assertIn('href="https://example.test/racing/article-sugo-report-2026.html"', text)
        listing = update_news_html('<div data-news-list data-limit="3"><div>old</div></div>', {"items": [item]}, self.base)
        self.assertIn(f'href="{article_filename(item)}"', listing)
        self.assertIn("撮影者クレジット", listing)
        self.assertNotIn("第二段落", listing)

    def test_text_is_literal_and_unsafe_urls_rejected(self):
        sample = article(title='<script>window.injected=1</script>', description='<img src=x onerror="alert(1)">')
        sample["blocks"][1]["caption"] = '<script>alert("caption")</script>'
        text = generate_article_pages(self.template, {"items": [sample]}, self.base)[article_filename(sample)]
        self.assertNotIn('<script>window.injected', text)
        self.assertNotIn('<img src=x', text)
        self.assertIn('&lt;script&gt;', text)
        for value in ("javascript:alert(1)", "https://evil.test/a.jpg", "assets/images/../secret.jpg",
                      "assets/images/%2e%2e/secret.jpg", "assets/images/a.jpg?script=1", "assets/images/a\x00.jpg"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_news({"items": [article(image=value)]})
        for value in ("javascript:alert(1)", "http://external.test/", "https://user:pass@example.test/", "//evil.test/"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_news({"items": [article(url=value)]})

    def test_invalid_metadata_cannot_accidentally_publish(self):
        for changes in ({"slug": "../oops"}, {"slug": "Upper"}, {"slug": ""},
                        {"published": "false"}, {"date": "2026-02-30"}, {"imageAlt": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                public_news({"items": [article(**changes)]})
        with self.assertRaises(ValueError):
            public_news({"items": [article(), article()]})
        value = article(blocks=[{"type": "image", "image": "assets/images/a.jpg", "alt": ""}])
        with self.assertRaises(ValueError):
            public_news({"items": [value]})

    def test_media_pipeline_paths_and_dimensions_survive_normalization(self):
        sample = article(image="assets/optimized/abc123.webp", imageWidth=640, imageHeight=427)
        sample["blocks"][1].update(image="assets/optimized/def456.webp", width=400, height=600)
        item = public_news({"items": [sample]})["items"][0]
        self.assertEqual((item["imageWidth"], item["imageHeight"]), (640, 427))
        self.assertEqual((item["blocks"][1]["width"], item["blocks"][1]["height"]), (400, 600))
        self.assertEqual(image_path("assets/images/uploads/photo name.jpg"), "assets/images/uploads/photo name.jpg")
        # Unknown internal-only fields never reach downloadable public JSON.
        sample["privateNote"] = "Do not publish"
        self.assertNotIn("privateNote", public_news({"items": [sample]})["items"][0])


if __name__ == "__main__":
    unittest.main()
