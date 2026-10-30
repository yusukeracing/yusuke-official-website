#!/usr/bin/env python3
"""Browser regressions for CMS photos, cached HTML photos and mobile fallback.

Optional development tool: install Python Playwright, then run this script.
No Playwright package is used by the site or its production build.
"""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from pathlib import Path
import shutil
from threading import Thread
import time

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT)
    parser.add_argument("--browser", default=shutil.which("chromium"))
    args = parser.parse_args()
    try:
        from playwright.sync_api import sync_playwright, expect
    except ImportError:
        parser.error("Install the optional developer tool: python3 -m pip install playwright")
    root = args.directory.resolve()
    site = json.loads((root / "data/site.json").read_text())
    profile = json.loads((root / "data/profile.json").read_text())
    source_site = json.loads((ROOT / "data/site.json").read_text())
    source_profile = json.loads((ROOT / "data/profile.json").read_text())
    source_photo = "assets/images/yusuke.gallery_09.jpg"
    source_story = "assets/images/yusuke.hero_04.jpg"
    assert source_site["heroImage"] == source_photo, "Source CMS HERO must select the supplied gallery_09 photo"
    assert source_profile["stories"][0]["image"] == source_story, "Source PHOTO STORY 01 must retain the supplied 04 photo"
    photo = site["heroImage"]
    story_photo = profile["stories"][0]["image"]
    manifest_path = root / "data/media-manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {"images": []}
    variants = {}
    for entry in manifest["images"]:
        for variant in entry["variants"]:
            variants.setdefault(variant["path"], set()).add(entry["source"])
    def matches_source(path, source):
        return path == source or source in variants.get(path, set())
    assert matches_source(photo, source_photo), "Delivered HERO must map to gallery_09 in the media manifest"
    assert matches_source(story_photo, source_story), "Delivered STORY 01 must map to hero_04 in the media manifest"
    if (root / "data/publication.json").is_file() and site.get("maintenanceEnabled"):
        parser.error("Use a normal preview artifact: python3 scripts/build.py --normal-preview --output dist-preview")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
    Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    failures = []
    try:
        with sync_playwright() as p:
            options = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
            if args.browser:
                options["executable_path"] = args.browser
            browser = p.chromium.launch(**options)

            def run_case(name, overrides=None, viewport=None, delayed=False):
                context = browser.new_context(viewport=viewport or {"width": 1440, "height": 1000}, reduced_motion="reduce")
                context.route("**/data/profile.json*", lambda route: route.fulfill(json=profile))
                settings = {**site, **(overrides or {})}

                def site_route(route):
                    if delayed:
                        time.sleep(0.2)
                    route.fulfill(json=settings)

                context.route("**/data/site.json*", site_route)
                page = context.new_page()
                errors = []
                requests = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: requests.append(request.url))
                page.goto(url)
                hero = page.locator(".hero-photo")
                expect(hero).to_have_class(re.compile(r"\bis-loaded\b"))
                expect(hero.locator(".photo-label")).to_be_hidden()
                expect(hero.locator(".hero-watermark")).to_be_hidden()
                assert hero.locator("img").evaluate("image => image.naturalWidth > 0")
                hero_source = hero.locator("img").evaluate("image => image.currentSrc")
                selected = hero_source.removeprefix(url)
                candidates = {path for path in (photo, site.get("heroMobileImage", "")) if path}
                assert selected in candidates and matches_source(selected, source_photo), hero_source
                expected = settings.get("heroMobileImage") if page.viewport_size["width"] <= 767 else settings.get("heroImage")
                if expected in candidates:
                    assert selected == expected, (page.viewport_size, selected, expected)
                story = page.locator("[data-stories] .photo-slot").first
                story.scroll_into_view_if_needed()
                expect(story).to_have_class(re.compile(r"\bis-loaded\b"))
                expect(story.locator("img")).to_have_attribute("src", url + story_photo)
                expect(story.locator(".photo-label")).to_be_hidden()
                assert not errors, errors
                if delayed:
                    assert sum(request.endswith(photo) for request in requests) == 1, requests
                if (overrides or {}).get("heroMobileImage", "").endswith("missing-mobile.jpg"):
                    assert any(request.endswith("missing-mobile.jpg") for request in requests)
                    assert page.locator(".hero-frame source").count() == 0
                print(f"PASS: {name}")
                context.close()

            for name, overrides, viewport, delayed in [
                ("CMS PHOTO STORY retains yusuke.hero_04", None, None, False),
                ("cached authored HTML photo is recognized without a second request", {"heroImage": ""}, None, True),
                ("missing mobile crop falls back to desktop photo", {"heroMobileImage": "assets/images/missing-mobile.jpg"}, {"width": 390, "height": 844}, False),
            ]:
                try:
                    run_case(name, overrides, viewport, delayed)
                except Exception as error:
                    failures.append(f"{name}: {error}")
            context = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
            settings = {**site, "heroImage": "assets/images/missing-desktop.jpg", "heroMobileImage": "assets/images/missing-mobile.jpg"}
            context.route("**/data/site.json*", lambda route: route.fulfill(json=settings))
            page = context.new_page()
            requests = []
            page.on("request", lambda request: requests.append(request.url))
            page.goto(url)
            expect(page.locator(".hero-frame img")).to_have_attribute("src", re.compile(r"image-unavailable\.svg$"))
            expect(page.locator(".hero-photo")).not_to_have_class(re.compile(r"\bis-loaded\b"))
            expect(page.locator(".hero-frame")).not_to_have_class(re.compile(r"\bis-loaded\b"))
            assert page.locator(".hero-frame source").count() == 0
            assert sum(request.endswith("missing-mobile.jpg") for request in requests) == 1
            assert sum(request.endswith("missing-desktop.jpg") for request in requests) == 1
            print("PASS: both missing crops end in one neutral placeholder, without retry loops")
            context.close()

            context = browser.new_context(reduced_motion="reduce")
            settings = {**site, "heroImage": "javascript:window.untrustedPhotoExecuted=true", "heroMobileImage": ""}
            context.route("**/data/site.json*", lambda route: route.fulfill(json=settings))
            page = context.new_page()
            page.goto(url)
            expect(page.locator(".hero-frame")).to_have_attribute("data-photo", settings["heroImage"])
            assert page.evaluate("window.untrustedPhotoExecuted === undefined")
            assert page.locator(".hero-frame img").evaluate("image => image.src").startswith(url)
            print("PASS: unsafe CMS image URL is never used")
            context.close()

            # The three CTA links must remain readable and usable over any photo.
            context = browser.new_context(reduced_motion="reduce")
            page = context.new_page()
            for width in (320, 390, 768, 1024, 1440):
                page.set_viewport_size({"width": width, "height": 1000})
                page.goto(url)
                expect(page.locator(".hero-photo")).to_have_class(re.compile(r"\bis-loaded\b"))
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
                boxes = []
                for link in page.locator(".hero-actions a").all():
                    box = link.bounding_box()
                    assert box and box["height"] >= 44, (width, box)
                    assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1, (width, box)
                    boxes.append(box)
                for index, box in enumerate(boxes):
                    for other in boxes[index + 1:]:
                        overlap = min(box["x"] + box["width"], other["x"] + other["width"]) > max(box["x"], other["x"]) and min(box["y"] + box["height"], other["y"] + other["height"]) > max(box["y"], other["y"])
                        assert not overlap, (width, boxes)
                for link in page.locator(".hero-actions .text-link").all():
                    colors = link.evaluate("link => ({background: getComputedStyle(link).backgroundColor, color: getComputedStyle(link).color})")
                    assert colors["background"] == "rgb(255, 255, 255)", colors
                    assert colors["color"] == "rgb(7, 26, 51)", colors
                print(f"PASS: opaque, nonoverlapping hero buttons at {width}px")
            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    if failures:
        for failure in failures:
            print("FAIL:", failure)
        return 1
    print("PASS: real CMS photos, cached photo state and responsive fallback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
