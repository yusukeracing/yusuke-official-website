#!/usr/bin/env python3
"""Test CMS-to-publication paths and media integrity in an isolated fixture."""
from __future__ import annotations

from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from PIL import Image, ImageCms, Jpeg2KImagePlugin
import build
import media_assets


TEMPLATE = '''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>活動報告</title><meta name="description" content="site description">
<meta property="og:title" content="title"><meta property="og:description" content="description">
<meta property="og:url" content="https://example.test/project/index.html">
<meta property="og:image" content="https://example.test/project/assets/images/landscape.jpg">
<link rel="canonical" href="https://example.test/project/index.html">
<link rel="stylesheet" href="assets/css/style.css?v=old">
<script src="assets/js/main.js?v=old" defer></script>
<script src="assets/js/data-loader.js?v=old" defer></script></head><body><main id="main">
<figure class="photo-slot hero-frame" data-photo-bind="site.heroImage" data-photo="assets/images/landscape.jpg">
<picture><img src="assets/images/landscape.jpg" alt="走行するライダー" width="1" height="1" data-photo-image></picture></figure>
<div data-news-list data-limit="0"><div>previous</div></div><div data-gallery></div>
<p data-maintenance-message>notice</p><p class="fine-print">お急ぎの場合：<span data-contact="email">xxx</span></p>
</main></body></html>'''


class PublicationPipelineTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="yusuke-pipeline-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.output = self.root / "published"
        (self.root / "data").mkdir()
        for folder in ("images", "css", "js", "icons"):
            (self.root / "assets" / folder).mkdir(parents=True)
        Image.new("RGB", (300, 200), (32, 100, 180)).save(self.root / "assets/images/landscape.jpg", quality=98)
        image = Image.new("RGB", (300, 200), (180, 95, 35))
        exif = Image.Exif(); exif[274] = 6
        image.save(self.root / "assets/images/portrait.jpg", exif=exif, quality=98)
        (self.root / "assets/css/style.css").write_text("img { max-width: 100%; height: auto; object-fit: contain; }")
        for file in ("main.js", "data-loader.js", "news.js"):
            (self.root / "assets/js" / file).write_text('"use strict";')
        for file in (*build.PAGES, "article-template.html"):
            (self.root / file).write_text(TEMPLATE)
        self.originals = {path.name: path.read_bytes() for path in (self.root / "assets/images").iterdir()}
        self.save("site", {"name": "Site", "url": "https://example.test/project/", "description": "site description",
             "heroImage": "assets/images/portrait.jpg", "heroMobileImage": "", "heroAlt": "原写真の説明",
             "ogImage": "assets/images/landscape.jpg", "photos": {"supportFeature": "assets/images/portrait.jpg"}, "maintenanceEnabled": False, "socials": [], "email": ""})
        self.save("profile", {"name": "池田優介", "message": "応援ありがとうございます。", "messageIsSample": False})
        self.save("gallery", {"items": [{"image": "assets/images/landscape.jpg", "mobileImage": "assets/images/landscape.jpg",
                                         "alt": "走行写真", "caption": "写真の説明"}]})
        self.save("races", {"next": {}, "schedule": [], "results": []})
        self.save("sponsors", {"items": [{"name": "ローカル表示確認用", "logo": "assets/images/landscape.jpg", "url": "https://example.test/"}]})
        self.save("messages", {"items": []})
        self.article = {"slug": "season-report", "published": True, "date": "2026-10-30", "title": "活動報告",
                        "description": "一段落目。", "category": "ACTIVITY", "image": "assets/images/landscape.jpg",
                        "imageAlt": "サムネイル", "blocks": [{"type": "image", "image": "assets/images/portrait.jpg", "alt": "本文中の写真", "caption": "本文写真の説明"}]}
        self.save("news", {"items": [self.article]})

    def save(self, name, value):
        (self.root / "data" / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False))

    def load(self, name, source=False):
        return json.loads(((self.root if source else self.output) / "data" / (name + ".json")).read_text())

    def publish(self, preview=False):
        with patch.object(build, "ROOT", self.root), patch.object(build, "OUTPUT", self.output), redirect_stdout(StringIO()):
            return build.build_site(normal_preview=preview)

    def test_configured_hero_exact_path_orientation_and_originals(self):
        info = self.publish()
        data = self.load("site")
        hero = data["heroImage"]
        self.assertTrue(hero.startswith("assets/optimized/"))
        self.assertTrue(data["photos"]["supportFeature"].startswith("assets/optimized/"))
        sponsor = self.load("sponsors")["items"][0]
        self.assertTrue(sponsor["logo"].startswith("assets/optimized/"))
        self.assertEqual((sponsor["logoWidth"], sponsor["logoHeight"]), (300, 200))
        self.assertTrue((self.output / sponsor["logo"]).is_file())
        for name in build.SOURCE_DATA:
            public_text = (self.output / "data" / name).read_text()
            self.assertNotIn("assets/images/", public_text, name)
        text = (self.output / "index.html").read_text()
        self.assertIn(f'src="{hero}"', text)
        self.assertIn('width="200" height="300"', text)
        self.assertIn('alt="原写真の説明"', text)
        self.assertIn('?v=' + info["contentId"], text)
        self.assertIn('name="publication-id"', text)
        self.assertFalse((self.output / "assets/images/portrait.jpg").exists())
        for name, value in self.originals.items():
            self.assertEqual((self.root / "assets/images" / name).read_bytes(), value)
        with Image.open(self.output / hero) as delivered:
            self.assertEqual(delivered.size, (200, 300))
            self.assertFalse(delivered.getexif())
            self.assertTrue(delivered.info.get("icc_profile"))
        manifest = self.load("media-manifest")
        source = next(item for item in manifest["images"] if item["source"].endswith("portrait.jpg"))
        self.assertEqual(source["sourceSha256"], sha256(self.originals["portrait.jpg"]).hexdigest())

    def test_create_edit_photo_replace_delete_and_unpublished_exclusion(self):
        draft = {**self.article, "slug": "private-draft", "published": False, "title": "DRAFT SHOULD NOT LEAK",
                 "image": "assets/images/not-uploaded-yet.jpg", "blocks": []}
        self.save("news", {"items": [self.article, draft]})
        self.publish()
        self.assertTrue((self.output / "article-season-report.html").is_file())
        self.assertFalse((self.output / "article-private-draft.html").exists())
        self.assertNotIn("DRAFT SHOULD NOT LEAK", (self.output / "data/news.json").read_text())
        self.assertEqual(self.load("news")["items"][0]["imageWidth"], 300)
        self.assertEqual(self.load("news")["items"][0]["blocks"][0]["width"], 200)
        self.article.update(title="編集後のタイトル", image="assets/images/portrait.jpg", imageAlt="変更したサムネイル")
        self.article["blocks"].append({"type": "text", "text": "写真の後に追記。"})
        self.save("news", {"items": [self.article]})
        self.publish()
        article = (self.output / "article-season-report.html").read_text()
        self.assertIn("編集後のタイトル", article)
        self.assertIn("写真の後に追記。", article)
        self.assertIn("変更したサムネイル", article)
        self.save("news", {"items": []})
        self.publish()
        self.assertFalse((self.output / "article-season-report.html").exists())
        self.assertEqual(self.load("news")["items"], [])
        self.assertNotIn("article-season-report", (self.output / "sitemap.xml").read_text())

    def test_bad_case_or_unsafe_path_keeps_previous_publication(self):
        self.publish()
        previous = (self.output / "index.html").read_bytes()
        settings = self.load("site", source=True)
        settings["heroImage"] = "assets/images/Portrait.jpg"
        self.save("site", settings)
        with self.assertRaisesRegex(ValueError, "exact spelling/case"):
            self.publish()
        self.assertEqual((self.output / "index.html").read_bytes(), previous)
        settings["heroImage"] = "assets/images/%2e%2e/data/site.json"
        self.save("site", settings)
        with self.assertRaisesRegex(ValueError, "Unsafe local image"):
            self.publish()
        self.assertEqual((self.output / "index.html").read_bytes(), previous)

    def test_json_conflict_markers_identify_file_and_keep_previous_artifact(self):
        self.publish()
        previous = (self.output / "index.html").read_bytes()
        source = self.root / "data/gallery.json"
        source.write_text('{"items": [\n<<<<<<< HEAD\n]}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"data/gallery\.json: unresolved merge conflict"):
            self.publish()
        self.assertEqual((self.output / "index.html").read_bytes(), previous)
        source.write_text('{"items": [\n}\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"data/gallery\.json: invalid JSON at line 2, column 1$"):
            self.publish()
        self.assertEqual((self.output / "index.html").read_bytes(), previous)
        source.unlink()
        source.symlink_to(self.root / "data/site.json")
        with patch.object(build, "ROOT", self.root), patch.object(Path, "read_text", side_effect=AssertionError("A symlink must not be read")):
            with self.assertRaisesRegex(ValueError, r"Missing regular public data file: data/gallery\.json"):
                build.read_source_json("gallery.json")
        self.assertEqual((self.output / "index.html").read_bytes(), previous)
        # site_url uses the same safe loader and reports the actual source file.
        site = self.root / "data/site.json"
        site.write_text('<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> owner\n', encoding="utf-8")
        with patch.object(build, "ROOT", self.root):
            with self.assertRaisesRegex(ValueError, r"data/site\.json: unresolved merge conflict"):
                build.site_url()

    def test_disguised_jpeg2000_never_enters_its_decoder(self):
        self.publish()
        previous = (self.output / "index.html").read_bytes()
        disguised = self.root / "assets/images/disguised.jpg"
        # This is only the harmless JP2 identification signature, not a crafted
        # codestream. Even its decoder entry point must never be called.
        disguised.write_bytes(b"\x00\x00\x00\x0cjP  \r\n\x87\n")
        settings = self.load("site", source=True)
        settings["heroImage"] = "assets/images/disguised.jpg"
        self.save("site", settings)
        with patch.object(Jpeg2KImagePlugin.Jpeg2KImageFile, "_open", side_effect=AssertionError("JPEG 2000 decoder must not be entered")) as decoder:
            with self.assertRaisesRegex(ValueError, "Cannot decode photo: assets/images/disguised.jpg"):
                self.publish()
            decoder.assert_not_called()
        self.assertEqual((self.output / "index.html").read_bytes(), previous)
        Image.new("RGB", (8, 8)).save(disguised, format="PNG")
        with self.assertRaisesRegex(ValueError, "assets/images/disguised.jpg: extension .jpg does not match image format PNG"):
            self.publish()
        self.assertEqual((self.output / "index.html").read_bytes(), previous)
        with patch.object(media_assets, "PILLOW_VERSION", "12.3.0"), patch.object(Image, "open", side_effect=AssertionError("An outdated decoder must not run")):
            with self.assertRaisesRegex(ValueError, "Pillow 13.0.0 or later.*build-venv"):
                media_assets.MediaPipeline(self.root, self.output, "https://example.test/project/")

    def test_delivery_urls_hash_encoded_bytes_and_ignore_icc_clock_metadata(self):
        gradient = Image.new("RGB", (96, 72))
        gradient.putdata([(x * 3 % 256, y * 4 % 256, x * y % 256) for y in range(72) for x in range(96)])
        source = self.root / "assets/images/cache.jpg"
        gradient.save(source, quality=98)
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        first_profile, second_profile = bytearray(profile), bytearray(profile)
        first_profile[24:36] = bytes.fromhex("07d100010001000000000001")
        second_profile[24:36] = bytes.fromhex("07d200010001000000000002")
        paths = []
        for index, data in enumerate((first_profile, second_profile)):
            pipeline = media_assets.MediaPipeline(self.root, self.root / f"variant-{index}", "https://example.test/project/")
            with patch.object(ImageCms.ImageCmsProfile, "tobytes", return_value=bytes(data)):
                image = pipeline.image("assets/images/cache.jpg")
            paths.append(image.path)
            self.assertIn(image.sha256[:20], image.path)
            self.assertEqual(sha256((self.root / f"variant-{index}" / image.path).read_bytes()).hexdigest(), image.sha256)
        self.assertEqual(paths[0], paths[1])
        pipeline = media_assets.MediaPipeline(self.root, self.root / "different-quality", "https://example.test/project/")
        with patch.object(media_assets, "WEBP_QUALITY", 70):
            changed = pipeline.image("assets/images/cache.jpg")
        self.assertNotEqual(paths[0], changed.path)
        self.assertIn(changed.sha256[:20], changed.path)
        data = {"site": {"maintenanceEnabled": False}}
        dependency = self.root / "requirements-build.txt"
        dependency.write_text("Pillow==13.0.0\n")
        before = build.publication_id({"index.html": TEMPLATE}, data, self.root)
        dependency.write_text("Pillow==13.0.1\n")
        after = build.publication_id({"index.html": TEMPLATE}, data, self.root)
        self.assertNotEqual(before, after)
        (self.root / "scripts").mkdir()
        converter = self.root / "scripts/media_assets.py"
        converter.write_text("# converter policy v1\n")
        first_policy = build.publication_id({"index.html": TEMPLATE}, data, self.root)
        converter.write_text("# converter policy v2\n")
        self.assertNotEqual(first_policy, build.publication_id({"index.html": TEMPLATE}, data, self.root))

    def test_output_cannot_replace_the_source_checkout(self):
        settings = (self.root / "data/site.json").read_bytes()
        with patch.object(build, "ROOT", self.root), patch.object(build, "OUTPUT", self.root):
            with self.assertRaisesRegex(ValueError, "source checkout"):
                build.build_site()
        self.assertEqual((self.root / "data/site.json").read_bytes(), settings)

    def test_preview_does_not_disable_owner_maintenance_and_articles_are_covered(self):
        settings = self.load("site", source=True)
        settings["maintenanceEnabled"] = True
        self.save("site", settings)
        self.publish(preview=True)
        self.assertFalse(self.load("site")["maintenanceEnabled"])
        self.assertTrue(self.load("site", source=True)["maintenanceEnabled"])
        self.assertIn("活動報告", (self.output / "article-season-report.html").read_text())
        info = self.publish()
        for name in info["pages"]:
            text = (self.output / name).read_text()
            self.assertIn('data-maintenance-mode="true"', text)
            self.assertNotIn('src="assets/js/news.js', text)
        self.assertEqual(ET.parse(self.output / "sitemap.xml").findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"), [])
        self.assertTrue(self.load("site", source=True)["maintenanceEnabled"])


if __name__ == "__main__":
    unittest.main()
