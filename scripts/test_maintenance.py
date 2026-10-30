#!/usr/bin/env python3
"""Check maintenance publication and recovery in a temporary copy of the site."""
from __future__ import annotations

from contextlib import redirect_stdout
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

import build
from check_site import validate


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class MaintenancePublicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="yusuke-maintenance-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.output = self.root / "dist"
        for name in (*build.PAGES, "article-template.html"):
            shutil.copy2(build.ROOT / name, self.root / name)
        shutil.copytree(build.ROOT / "data", self.root / "data")
        shutil.copytree(build.ROOT / "assets", self.root / "assets")
        self.settings_path = self.root / "data/site.json"

    def save_settings(self, **changes):
        settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
        settings.update(changes)
        self.settings_path.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")

    def publish(self):
        with patch.object(build, "ROOT", self.root), patch.object(build, "OUTPUT", self.output), redirect_stdout(io.StringIO()):
            return build.main()

    def test_enabled_notice_at_every_url_and_disabled_recovery(self):
        source_files = (*build.PAGES, "article-template.html")
        original_pages = {name: (self.root / name).read_bytes() for name in source_files}
        # Exercise generated URLs even when production has no published reports.
        news_path = self.root / "data/news.json"
        news = json.loads(news_path.read_text(encoding="utf-8"))
        news["items"].append({"slug": "maintenance-regression", "published": True,
                              "title": "Local maintenance fixture", "date": "2026-10-30",
                              "description": "Temporary publication check", "image": "", "blocks": []})
        news["items"].append({"slug": "maintenance-hidden-fixture", "published": False,
                              "title": "NOT_FOR_ARTIFACT", "date": "2026-10-30",
                              "description": "NOT_FOR_ARTIFACT", "image": "", "blocks": []})
        news_path.write_text(json.dumps(news, ensure_ascii=False), encoding="utf-8")
        self.save_settings(maintenanceEnabled=False)
        publication = self.publish()
        self.assertIn("article-maintenance-regression.html", publication["articlePages"])
        self.assertNotIn("article-maintenance-hidden-fixture.html", publication["pages"])
        self.assertNotIn("NOT_FOR_ARTIFACT", (self.output / "data/news.json").read_text())
        self.assertEqual(set(publication["pages"]), set(build.PAGES) | set(publication["articlePages"]))
        self.assertEqual(set(path.name for path in (self.output / "data").iterdir()), set(build.PUBLIC_DATA))
        normal_pages = {name: (self.output / name).read_bytes() for name in publication["pages"] if name != "maintenance.html"}
        error_tags = Tags((self.output / "404.html").read_text()).tags
        for tag, attrs in error_tags:
            if tag == "script":
                self.assertNotIn("data-loader.js", attrs.get("src", ""))
                self.assertNotIn("social-links.js", attrs.get("src", ""))
            for attr in ("src", "href", "poster"):
                value = attrs.get(attr, "")
                if value and not value.startswith("#"):
                    self.assertTrue(bool(urlsplit(value).scheme), (tag, attr, value))
        errors, _ = validate(self.output)
        self.assertEqual(errors, [])

        self.save_settings(maintenanceEnabled=True, maintenanceMessage='公開再開をお待ちください。\n<script>alert("test")</script> & 安全な案内')
        maintenance_publication = self.publish()
        self.assertEqual(set(maintenance_publication["pages"]), set(publication["pages"]))
        self.assertTrue(maintenance_publication["maintenanceEnabled"])
        for name in maintenance_publication["pages"]:
            text = (self.output / name).read_text(encoding="utf-8")
            tags = Tags(text).tags
            self.assertTrue(any(tag == "body" and attrs.get("data-maintenance-mode") == "true" for tag, attrs in tags), name)
            self.assertTrue(any(tag == "meta" and attrs.get("name") == "robots" and "noindex" in attrs.get("content", "") for tag, attrs in tags), name)
            self.assertFalse(any(tag == "nav" for tag, _ in tags), name)
            self.assertFalse(any(tag == "button" and "menu-toggle" in attrs.get("class", "").split() for tag, attrs in tags), name)
            self.assertFalse(any(tag == "script" and any(loader in attrs.get("src", "") for loader in ("data-loader.js", "social-links.js", "news.js", "community.js")) for tag, attrs in tags), name)
            self.assertIn('&lt;script&gt;alert(&quot;test&quot;)&lt;/script&gt; &amp; 安全な案内', text)
            self.assertIn('公開再開をお待ちください。<br />', text)
            self.assertNotIn('<script>alert("test")</script>', text)
            settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
            expected = settings["url"].rstrip("/") + "/" + ("" if name == "index.html" else name)
            self.assertTrue(any(tag == "link" and attrs.get("rel") == "canonical" and attrs.get("href") == expected for tag, attrs in tags), name)
        locations = ET.parse(self.output / "sitemap.xml").findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
        self.assertEqual(locations, [])
        self.assertNotIn("Disallow:", (self.output / "robots.txt").read_text())
        errors, _ = validate(self.output)
        self.assertEqual(errors, [])

        self.save_settings(maintenanceEnabled=False)
        recovered = self.publish()
        self.assertFalse(recovered["maintenanceEnabled"])
        self.assertEqual(set(recovered["pages"]), set(publication["pages"]))
        for name, content in normal_pages.items():
            self.assertEqual((self.output / name).read_bytes(), content, name)
        self.assertEqual(len(ET.parse(self.output / "sitemap.xml").findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")), len(build.PUBLIC_PAGES) + len(publication["articlePages"]))
        self.assertEqual({name: (self.root / name).read_bytes() for name in source_files}, original_pages)
        errors, _ = validate(self.output)
        self.assertEqual(errors, [])

    def test_text_false_is_rejected_without_removing_previous_artifact(self):
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("previous output")
        self.save_settings(maintenanceEnabled="false")
        with self.assertRaisesRegex(ValueError, "maintenanceEnabled must be true or false"):
            self.publish()
        self.assertEqual(marker.read_text(), "previous output")

    def test_merge_conflict_is_rejected_before_output_is_replaced(self):
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("previous output")
        self.save_settings(maintenanceEnabled=False)
        page = self.root / "profile.html"
        page.write_text(page.read_text() + "\n<<<<<<< HEAD\nunresolved\n=======\nother\n>>>>>>> branch\n")
        with self.assertRaisesRegex(ValueError, "profile.html: unresolved merge conflict"):
            self.publish()
        self.assertEqual(marker.read_text(), "previous output")


if __name__ == "__main__":
    unittest.main()
