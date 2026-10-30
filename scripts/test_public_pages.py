#!/usr/bin/env python3
"""Optional local browser regressions for contact, partners and public messages.

Usage: python3 scripts/test_public_pages.py --directory dist
Requires Python Playwright and Chromium only as development tools. Every request
stays on an ephemeral loopback server, or receives a local Google Forms fixture.
The test never loads the real Google form or submits an inquiry.
"""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
from threading import Thread
import time
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PAGES = ("index.html", "profile.html", "race.html", "news.html", "sponsor.html",
         "support.html", "contact.html", "partners.html", "messages.html",
         "404.html", "maintenance.html")
FORM_FIXTURE = """<!doctype html><html lang="ja"><meta charset="utf-8">
<title>Local form fixture</title><body><p>ローカルの表示確認用フォーム代替応答です。</p>
<p>入力欄や送信処理はありません。</p></body></html>"""


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
        parser.error("Install the optional development tool: python3 -m pip install playwright")
    root = args.directory.resolve()
    site = json.loads((root / "data/site.json").read_text(encoding="utf-8"))
    expected_form = site["googleFormUrl"]
    expected_height = str(site.get("googleFormHeight", 2081))
    expected_form_path = urlsplit(expected_form).path
    assert expected_form.startswith("https://docs.google.com/forms/"), "Configure the supplied Google form first"
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
    Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    checks = 0
    failures = []
    try:
        with sync_playwright() as p:
            options = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
            if args.browser:
                options["executable_path"] = args.browser
            browser = p.chromium.launch(**options)

            def context_for_test(**options):
                context = browser.new_context(reduced_motion="reduce", **options)
                requests = {"google_fixtures": [], "blocked_external": [], "blocked_mutations": [], "page_errors": []}

                def route_request(route):
                    url = route.request.url
                    if route.request.method not in {"GET", "HEAD"}:
                        requests["blocked_mutations"].append({"method": route.request.method, "url": url})
                        route.abort()
                        return
                    if url.startswith(base + "/"):
                        if urlsplit(url).path == "/404.html":
                            # Published 404 assets use the canonical site root so
                            # nested unknown URLs work. Rebase that root for this
                            # loopback-only fixture instead of contacting Pages.
                            text = (root / "404.html").read_text(encoding="utf-8")
                            text = text.replace(site["url"].rstrip("/") + "/", base + "/")
                            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=text)
                        else:
                            route.continue_()
                    elif url.startswith("https://docs.google.com/forms/"):
                        requests["google_fixtures"].append(url)
                        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=FORM_FIXTURE)
                    else:
                        requests["blocked_external"].append(url)
                        route.abort()

                context.route("**/*", route_request)
                context.on("page", lambda page: page.on("pageerror", lambda error: requests["page_errors"].append(str(error))))
                return context, requests

            def run(name, test):
                nonlocal checks
                try:
                    test()
                    checks += 1
                    print("PASS:", name, flush=True)
                except Exception as error:
                    failures.append(f"{name}: {error}")
                    print("FAIL:", name, str(error), flush=True)

            def assert_clean(requests):
                assert not requests["blocked_external"], requests["blocked_external"]
                assert not requests["blocked_mutations"], requests["blocked_mutations"]
                assert not requests["page_errors"], requests["page_errors"]

            def data_route(context, name, handler):
                # Published data is versioned; match both source and built URLs.
                context.route(re.compile(r"/data/" + re.escape(name) + r"\.json(?:\?.*)?$"), handler)

            def contact_configured():
                context, requests = context_for_test(viewport={"width": 390, "height": 844})
                try:
                    # The delayed JSON response lets us identify the authored
                    # iframe before the enhancement runs and check node reuse.
                    def delayed_site(route):
                        time.sleep(0.2)
                        route.fulfill(json=site)

                    data_route(context, "site", delayed_site)
                    context.add_init_script("""document.addEventListener('DOMContentLoaded', () => {
                      window.__authoredContactFrame = document.querySelector('[data-contact-form] iframe');
                    });""")
                    page = context.new_page()
                    page.goto(base + "/contact.html", wait_until="networkidle")
                    iframe = page.locator("[data-contact-form] iframe")
                    expect(iframe).to_have_count(1)
                    expect(iframe).to_have_attribute("height", expected_height)
                    expect(iframe).to_have_attribute("referrerpolicy", "strict-origin-when-cross-origin")
                    expect(iframe).to_have_attribute("title", re.compile("Google Forms"))
                    expect(iframe).to_have_attribute("loading", "lazy")
                    assert page.evaluate("window.__authoredContactFrame === document.querySelector('[data-contact-form] iframe')")
                    source = iframe.get_attribute("src")
                    assert urlsplit(source).path == expected_form_path, source
                    assert parse_qs(urlsplit(source).query).get("embedded") == ["true"], source
                    iframe.scroll_into_view_if_needed()
                    expect(page.frame_locator("[data-contact-form] iframe").locator("p").first).to_contain_text("ローカル")
                    assert len(requests["google_fixtures"]) == 1, requests["google_fixtures"]
                    expect(page.locator("[data-form-link]")).to_be_visible()
                    expect(page.locator("[data-form-link]")).to_have_attribute("rel", "noopener noreferrer")
                    assert_clean(requests)
                finally:
                    context.close()

            run("configured contact iframe: safe URL, height, node reuse and one local Google fixture", contact_configured)

            def contact_invalid():
                for value in ("https://untrusted.invalid/forms/d/e/a/viewform", "javascript:window.__publicPagesXSS=1"):
                    context, requests = context_for_test()
                    try:
                        data_route(context, "site", lambda route: route.fulfill(json={**site, "googleFormUrl": value}))
                        page = context.new_page()
                        page.goto(base + "/contact.html", wait_until="networkidle")
                        expect(page.locator("[data-contact-form] iframe")).to_have_count(0)
                        expect(page.locator("[data-contact-form]")).to_contain_text("準備中")
                        expect(page.locator("[data-form-link]")).to_be_hidden()
                        assert page.evaluate("window.__publicPagesXSS === undefined")
                        assert_clean(requests)
                    finally:
                        context.close()

            run("untrusted and script form URLs remove the iframe and direct link", contact_invalid)

            def public_partners():
                payload = '<img src=x onerror="window.__publicPagesXSS=1">'
                optimized_files = sorted((root / "assets/optimized").glob("*.webp"))
                assert optimized_files, "Build the optimized publication before running this test"
                optimized_path = optimized_files[0].relative_to(root).as_posix()
                from PIL import Image
                with Image.open(optimized_files[0]) as optimized_image:
                    optimized_width, optimized_height = optimized_image.size
                fixtures = {"items": [
                    {"name": payload, "category": "' OR 1=1 --", "description": payload,
                     "logo": "https://untrusted.invalid/logo.png", "url": "javascript:window.__publicPagesXSS=2"},
                    {"name": "ローカル検証用企業", "category": "TEST", "description": "テスト専用の未公開データです。",
                     "logo": "assets/images/yusuke.gallery_01.jpg", "url": "https://example.com/partner"},
                    {"name": "配信用画像のローカル検証用企業", "category": "TEST", "description": "最適化画像のテスト専用データです。",
                     "logo": optimized_path, "logoWidth": optimized_width, "logoHeight": optimized_height,
                     "url": "https://example.com/optimized-partner"},
                ]}
                context, requests = context_for_test()
                try:
                    data_route(context, "sponsors", lambda route: route.fulfill(json=fixtures))
                    # Original uploads are retained in the source checkout, while
                    # production serves derivatives. This local-only response
                    # exercises the accepted original-path rendering branch.
                    context.route("**/assets/images/yusuke.gallery_01.jpg", lambda route: route.fulfill(
                        status=200, content_type="image/jpeg",
                        body=(ROOT / "assets/images/yusuke.gallery_01.jpg").read_bytes()))
                    page = context.new_page()
                    page.goto(base + "/partners.html", wait_until="networkidle")
                    entries = page.locator("[data-partner-directory] .partner-entry")
                    expect(entries).to_have_count(3)
                    expect(entries.first.locator(".partner-copy h2")).to_have_text(payload)
                    expect(entries.first.locator(".partner-description")).to_have_text(payload)
                    expect(entries.first).to_contain_text("' OR 1=1 --")
                    expect(entries.first.locator("img")).to_have_count(0)
                    expect(entries.first.locator("a")).to_have_count(0)
                    expect(entries.nth(1).locator("img")).to_have_attribute("src", re.compile("yusuke.gallery_01.jpg"))
                    for entry in (entries.nth(1), entries.nth(2)):
                        image = entry.locator("img")
                        image.scroll_into_view_if_needed()
                        expect(image).to_be_visible()
                        expect(image).to_have_js_property("complete", True)
                        assert image.evaluate("element => element.naturalWidth > 0")
                    derivative = entries.nth(2).locator("img")
                    expect(derivative).to_have_attribute("src", base + "/" + optimized_path)
                    expect(derivative).to_have_attribute("width", str(optimized_width))
                    expect(derivative).to_have_attribute("height", str(optimized_height))
                    safe_link = entries.nth(1).locator("a")
                    expect(safe_link).to_have_attribute("href", "https://example.com/partner")
                    expect(safe_link).to_have_attribute("target", "_blank")
                    expect(safe_link).to_have_attribute("rel", "noopener noreferrer")
                    expect(entries.nth(2).locator("a")).to_have_attribute("href", "https://example.com/optimized-partner")
                    assert page.evaluate("window.__publicPagesXSS === undefined")
                    assert_clean(requests)
                finally:
                    context.close()

            run("partner CMS fixtures render original/optimized logos and keep markup literal while rejecting unsafe links and external logos", public_partners)

            def public_messages():
                name = '<svg onload="window.__publicPagesXSS=3">'
                message = "' OR 1=1 --\n<img src=x onerror=window.__publicPagesXSS=4>"
                fixtures = {"items": [
                    {"name": name, "message": message, "date": "2026-10-29"},
                    {"name": "ローカル検証用表示名", "message": "未公開のテスト文です。", "date": "2026-02-30"},
                ]}
                context, requests = context_for_test()
                try:
                    data_route(context, "messages", lambda route: route.fulfill(json=fixtures))
                    page = context.new_page()
                    page.goto(base + "/messages.html", wait_until="networkidle")
                    entries = page.locator("[data-message-list] .support-message")
                    expect(entries).to_have_count(2)
                    expect(entries.first.locator(".message-name")).to_have_text(name)
                    expect(entries.first.locator(".message-text")).to_have_text(message)
                    expect(entries.first.locator("time")).to_have_attribute("datetime", "2026-10-29")
                    expect(entries.first.locator("time")).to_have_text("2026.10.29")
                    expect(entries.nth(1).locator("time")).to_have_count(0)
                    expect(entries.locator("img, svg, script")).to_have_count(0)
                    assert page.evaluate("window.__publicPagesXSS === undefined")
                    assert_clean(requests)
                finally:
                    context.close()

            run("message CMS fixtures keep attack strings literal and reject impossible dates", public_messages)

            def empty_pages():
                context, requests = context_for_test()
                try:
                    data_route(context, "sponsors", lambda route: route.fulfill(json={"items": []}))
                    data_route(context, "messages", lambda route: route.fulfill(json={"items": []}))
                    page = context.new_page()
                    for filename, target in (("partners.html", "[data-partner-directory]"), ("messages.html", "[data-message-list]")):
                        page.goto(base + "/" + filename, wait_until="networkidle")
                        expect(page.locator(target + " .community-empty")).to_be_visible()
                        expect(page.locator("[data-community-status]")).to_contain_text("0件")
                    assert_clean(requests)
                finally:
                    context.close()

            run("empty public lists display an honest empty state", empty_pages)

            def responsive_pages():
                context, requests = context_for_test()
                try:
                    page = context.new_page()
                    for width in (320, 390, 1440):
                        page.set_viewport_size({"width": width, "height": 1000})
                        for filename in PAGES:
                            page.goto(base + "/" + filename, wait_until="networkidle")
                            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (filename, width)
                            expect(page.locator("main h1")).to_be_visible()
                    assert_clean(requests)
                finally:
                    context.close()

            run("11 pages fit 320/390/1440px with no JavaScript exceptions", responsive_pages)

            def contact_no_javascript():
                context, requests = context_for_test(java_script_enabled=False, viewport={"width": 390, "height": 844})
                try:
                    page = context.new_page()
                    page.goto(base + "/contact.html", wait_until="networkidle")
                    iframe = page.locator("[data-contact-form] iframe")
                    expect(iframe).to_have_count(1)
                    expect(iframe).to_have_attribute("src", expected_form)
                    expect(iframe).to_have_attribute("height", expected_height)
                    iframe.scroll_into_view_if_needed()
                    expect(page.frame_locator("[data-contact-form] iframe").locator("p").first).to_contain_text("ローカル")
                    assert len(requests["google_fixtures"]) == 1
                    expect(page.locator("[data-form-link]")).to_be_visible()
                    assert_clean(requests)
                finally:
                    context.close()

            run("contact keeps its configured iframe and direct link without JavaScript", contact_no_javascript)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    if failures:
        for failure in failures:
            print("FAIL:", failure)
        return 1
    print(f"PASS: {checks} public-page checks; all Google responses were local fixtures; no inquiry submitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
