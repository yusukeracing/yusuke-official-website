#!/usr/bin/env python3
"""Optional Chromium checks of locally emulated Cloudflare Pages routes.

Run against build.py --cloudflare --normal-preview output. Every response is
supplied locally, including Google Forms. The fixture uses HTTP 302 for HTML
redirects; this does not assert Cloudflare's real redirect status. It cannot
verify Cloudflare deployment, DNS, TLS, real headers, CMS saves or form receipt.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import shutil
from threading import Thread
import time
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
FORM_FIXTURE = """<!doctype html><html lang="ja"><meta charset="utf-8">
<title>Local form fixture</title><main>ローカル表示確認用です。送信処理はありません。</main></html>"""


def clean_path(filename: str) -> str:
    return "/" if filename == "index.html" else "/" + filename.removesuffix(".html")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "dist-cloudflare-preview")
    parser.add_argument("--report", type=Path, default=Path("/tmp/yusuke-cloudflare-route-results.json"))
    parser.add_argument("--browser", default=shutil.which("chromium"))
    args = parser.parse_args()
    artifact = args.directory.resolve()
    started = time.monotonic()
    report = {
        "checked_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
        "artifact": str(artifact),
        "scope": "System Chromium and local route fixtures; not a Cloudflare production test",
        "network": "Local intercepted files and an ephemeral loopback redirect server; external navigation and all mutations blocked",
        "redirect_fixture": "302 from existing .html paths to extensionless paths; real Cloudflare status unverified",
        "browser": {"engine": "Chromium", "binary": args.browser},
        "cases": [],
        "not_executed": [
            "Actual Cloudflare build, deployment, routing and response-header application",
            "Public DNS, TLS certificate, real device, Safari and Edge checks",
            "Real Pages CMS UI save, Git commit and public CDN reflection",
            "Real Google Forms submission and owner receipt",
        ],
    }
    report["cases"].extend(
        {"name": item, "status": "SKIP", "reason": "Outside this local Chromium fixture"}
        for item in report["not_executed"]
    )

    def finish(code):
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report["summary"] = {
            status: sum(case["status"] == status for case in report["cases"])
            for status in ("PASS", "FAIL", "SKIP")
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report["summary"]), flush=True)
        return code

    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError:
        report["cases"].append({"name": "browser environment", "status": "SKIP", "reason": "Install development-only Python Playwright"})
        return finish(2)
    if not args.browser:
        report["cases"].append({"name": "browser environment", "status": "SKIP", "reason": "System Chromium is not installed"})
        return finish(2)

    try:
        site = json.loads((artifact / "data/site.json").read_text())
        publication = json.loads((artifact / "data/publication.json").read_text())
        news = json.loads((artifact / "data/news.json").read_text())
        gallery = json.loads((artifact / "data/gallery.json").read_text())["items"]
        manifest = json.loads((artifact / "data/media-manifest.json").read_text())
        base = site["url"].rstrip("/")
        origin = urlsplit(base)
        assert origin.scheme == "https" and origin.path in {"", "/"}, "Use a root HTTPS site URL"
        assert site.get("maintenanceEnabled") is False, "Use --normal-preview; do not disable the source CMS setting"
        assert publication.get("platform") == "cloudflare", "Use build.py --cloudflare"
        assert (artifact / "_headers").is_file(), "Cloudflare header configuration is missing"
        assert "frame-ancestors 'none'" in (artifact / "_headers").read_text(), "Expected framing restriction is missing"
        pages = publication["pages"]
        assert isinstance(pages, list) and pages, "Publication manifest must list the HTML pages"
        articles = [item for item in news["items"] if item.get("published", True)]
        assert articles, "Need at least one generated article to test clean detail routes"
        assert len(gallery) >= 2, "Need two real photos for local article insertion fixture"
    except Exception as error:
        report["cases"].append({"name": "artifact preconditions", "status": "FAIL", "error": str(error)})
        return finish(1)

    report.update({"publication_id": publication.get("contentId"), "site_url": site["url"], "pages": pages})
    variants = {
        variant["path"]: variant
        for image in manifest["images"]
        for variant in image.get("variants", [])
    }
    hero_candidates = {site["heroImage"], site.get("heroMobileImage", "")}
    hero_sources = {
        variant["path"]: image["source"]
        for image in manifest["images"]
        for variant in image.get("variants", [])
        if variant["path"] in hero_candidates
    }

    def case(name, test, **metadata):
        try:
            details = test() or {}
            report["cases"].append({"name": name, "status": "PASS", **metadata, **details})
            print("PASS:", name, flush=True)
        except Exception as error:
            report["cases"].append({"name": name, "status": "FAIL", "error": str(error)[:3000], **metadata})
            print("FAIL:", name, str(error)[:600], flush=True)

    class RedirectHandler(BaseHTTPRequestHandler):
        """Keep redirect follow-ups local even when Playwright skips the route.

        Playwright does not call the route handler again for every redirect
        follow-up. A real loopback endpoint is therefore needed for these cases.
        It serves only the already-built local artifact and never proxies URLs.
        """
        def log_message(self, *_args):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            relative = unquote(parsed.path).lstrip("/")
            candidate = (artifact / relative).resolve()
            if not candidate.is_relative_to(artifact) or "\\" in relative:
                self.send_error(400)
                return
            if candidate.is_file() and candidate.suffix == ".html":
                destination = clean_path(candidate.name)
                if parsed.query:
                    destination += "?" + parsed.query
                self.send_response(302)
                self.send_header("Location", destination)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if not relative:
                candidate = artifact / "index.html"
            elif not candidate.is_file() and not Path(relative).suffix:
                candidate = artifact / (relative + ".html")
            status = 200
            if not candidate.is_file():
                status = 404
                candidate = artifact / "404.html"
            body = candidate.read_bytes()
            self.send_response(status)
            self.send_header("Content-Type", mimetypes.guess_type(candidate)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser, args=["--no-sandbox", "--disable-dev-shm-usage"])
        report["browser"]["version"] = browser.version
        redirect_server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        Thread(target=redirect_server.serve_forever, daemon=True).start()
        loopback_base = f"http://127.0.0.1:{redirect_server.server_port}"

        def context(width=390, height=844, javascript=True, news_override=None, origin_base=None):
            request_origin = urlsplit(origin_base or base)
            ctx = browser.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce", java_script_enabled=javascript)
            logs = {"page_errors": [], "console_errors": [], "missing_assets": [], "unexpected_requests": [], "mutations": [], "redirects": [], "google_fixtures": 0, "requests": []}

            def route(request_route):
                request = request_route.request
                url = urlsplit(request.url)
                logs["requests"].append({"path": url.path, "type": request.resource_type})
                if request.method not in {"GET", "HEAD"}:
                    logs["mutations"].append({"method": request.method, "path": url.path})
                    request_route.abort()
                    return
                if (url.scheme, url.netloc) == (request_origin.scheme, request_origin.netloc):
                    relative = unquote(url.path).lstrip("/")
                    candidate = (artifact / relative).resolve()
                    if not candidate.is_relative_to(artifact) or "\\" in relative:
                        logs["unexpected_requests"].append("unsafe path")
                        request_route.abort()
                        return
                    if candidate.is_file() and candidate.suffix == ".html":
                        destination = clean_path(candidate.name)
                        if url.query:
                            destination += "?" + url.query
                        logs["redirects"].append({"from": url.path, "to": destination, "fixture_status": 302})
                        request_route.fulfill(status=302, headers={"Location": destination}, body="")
                        return
                    if not relative:
                        candidate = artifact / "index.html"
                    elif not candidate.is_file() and not Path(relative).suffix:
                        candidate = artifact / (relative + ".html")
                    if relative == "data/news.json" and news_override is not None:
                        request_route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(news_override, ensure_ascii=False))
                        return
                    status = 200
                    if not candidate.is_file():
                        status = 404
                        if request.resource_type not in {"document", "other"}:
                            logs["missing_assets"].append(relative)
                        candidate = artifact / "404.html"
                    request_route.fulfill(status=status, content_type=mimetypes.guess_type(candidate)[0] or "application/octet-stream", body=candidate.read_bytes())
                elif url.scheme == "https" and url.netloc == "docs.google.com" and url.path.startswith("/forms/"):
                    logs["google_fixtures"] += 1
                    request_route.fulfill(status=200, content_type="text/html; charset=utf-8", body=FORM_FIXTURE)
                else:
                    logs["unexpected_requests"].append(request.url.split("?")[0])
                    request_route.abort()

            ctx.route("**/*", route)

            def capture(page):
                page.on("pageerror", lambda error: logs["page_errors"].append(str(error)))
                page.on("console", lambda message: logs["console_errors"].append(message.text) if message.type == "error" else None)

            ctx.on("page", capture)
            return ctx, logs

        def check_logs(logs, allow_document_404=False):
            for key in ("page_errors", "missing_assets", "unexpected_requests", "mutations"):
                assert not logs[key], (key, logs[key])
            console = logs["console_errors"]
            if allow_document_404:
                console = [message for message in console if "404" not in message]
            assert not console, console

        def photos(page):
            count = 0
            for image in page.locator("img[src]").all():
                if not image.is_visible():
                    continue
                image.scroll_into_view_if_needed(timeout=8000)
                expect(image).to_have_js_property("complete", True)
                info = image.evaluate("""image => ({src: image.currentSrc, nw: image.naturalWidth, nh: image.naturalHeight,
                    width: image.getAttribute('width'), height: image.getAttribute('height'), alt: image.getAttribute('alt')})""")
                assert info["nw"] > 0 and info["nh"] > 0, info
                assert info["width"] and info["height"] and info["alt"] is not None, info
                assert abs(float(info["width"]) / float(info["height"]) - info["nw"] / info["nh"]) < 0.03, info
                count += 1
            return count

        for width, height in ((320, 844), (1366, 900)):
            ctx, logs = context(width, height)
            page = ctx.new_page()
            try:
                for filename in pages:
                    def render(filename=filename):
                        expected_url = base + clean_path(filename)
                        response = page.goto(expected_url, wait_until="networkidle")
                        assert response.status == 200, response.status
                        assert page.url == expected_url, page.url
                        expect(page.locator("h1").first).to_be_visible()
                        expect(page.locator('link[rel="canonical"]')).to_have_attribute("href", expected_url)
                        expect(page.locator('meta[property="og:url"]')).to_have_attribute("content", expected_url)
                        loaded = photos(page)
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), "horizontal overflow"
                        if filename == "index.html":
                            source = page.locator(".hero-frame img").evaluate("image => image.currentSrc")
                            relative = source.removeprefix(base + "/")
                            assert hero_sources.get(relative) == "assets/images/yusuke.gallery_09.jpg", source
                            expect(page.locator("[data-news-list] .news-item")).to_have_count(min(3, len(articles)))
                        if filename == "news.html":
                            expect(page.locator("[data-news-list] .news-item")).to_have_count(len(articles))
                        if filename.startswith("article-"):
                            slug = filename.removeprefix("article-").removesuffix(".html")
                            article = next(item for item in articles if item["slug"] == slug)
                            expect(page.locator("[data-article-slug] h1")).to_have_text(article["title"])
                        if filename == "contact.html":
                            frame = page.locator("iframe.contact-frame")
                            frame.scroll_into_view_if_needed()
                            expect(page.frame_locator("iframe.contact-frame").locator("main")).to_contain_text("ローカル")
                            assert logs["google_fixtures"] > 0
                        check_logs(logs)
                        return {"photos_loaded": loaded, "route": clean_path(filename)}

                    case(f"clean route {filename} at {width}px", render, width=width, height=height)
            finally:
                ctx.close()

        def redirects_and_menu():
            ctx, logs = context(320, origin_base=loopback_base)
            try:
                page = ctx.new_page()
                page.goto(loopback_base + "/index.html", wait_until="networkidle")
                assert page.url == loopback_base + "/"
                page.keyboard.press("Tab")
                expect(page.locator(".skip-link")).to_be_focused()
                toggle = page.locator(".menu-toggle")
                expect(toggle).to_be_visible()
                toggle.click()
                expect(toggle).to_have_attribute("aria-expanded", "true")
                page.locator('#primary-navigation a[href="news.html"]').click()
                page.wait_for_url(loopback_base + "/news", wait_until="networkidle")
                expect(page.locator("[data-news-list] .news-item")).to_have_count(len(articles))
                page.locator(".news-item h3 a").first.click()
                page.wait_for_url(loopback_base + "/article-" + articles[0]["slug"], wait_until="networkidle")
                expect(page.locator("[data-article-slug] h1")).to_have_text(articles[0]["title"])
                page.locator(".article-back a").click()
                page.wait_for_url(loopback_base + "/news", wait_until="networkidle")
                assert {"/index.html", "/news.html", "/article-" + articles[0]["slug"] + ".html"}.issubset({entry["from"] for entry in logs["redirects"]})
                check_logs(logs)
                return {"redirects": logs["redirects"], "scope": "Loopback fixture 302 only; real Cloudflare redirect status unverified"}
            finally:
                ctx.close()

        case("HTML links, mobile menu, keyboard and article round trip", redirects_and_menu)

        def static_article():
            ctx, logs = context(javascript=False, origin_base=loopback_base)
            try:
                page = ctx.new_page()
                page.goto(loopback_base + "/news", wait_until="networkidle")
                expect(page.locator(".news-item")).to_have_count(len(articles))
                page.locator(".news-item h3 a").first.click()
                page.wait_for_url(loopback_base + "/article-" + articles[0]["slug"], wait_until="networkidle")
                expect(page.locator("[data-article-slug] h1")).to_have_text(articles[0]["title"])
                assert page.locator(".article-body").inner_text().strip()
                check_logs(logs)
                return {"javascript_enabled": False, "scope": "Generated list and detail HTML at extensionless routes"}
            finally:
                ctx.close()

        case("JavaScript-disabled activity list and detail", static_article)

        def article_photos():
            local_news = deepcopy(news)
            item = next(item for item in local_news["items"] if item["slug"] == articles[0]["slug"])
            item["title"] = "ローカル経路確認用の写真付き記事"
            item["blocks"] = [{"type": "text", "text": "写真の前の文章"}]
            for index, photo in enumerate(gallery[:2], 1):
                size = variants[photo["image"]]
                item["blocks"].append({"type": "image", "image": photo["image"], "alt": f"本文写真{index}の代替テキスト", "caption": f"本文写真{index}の説明", "width": size["width"], "height": size["height"]})
            ctx, logs = context(news_override=local_news, origin_base=loopback_base)
            try:
                page = ctx.new_page()
                page.goto(loopback_base + "/news", wait_until="networkidle")
                page.locator(".news-item h3 a").filter(has_text=item["title"]).click()
                page.wait_for_url(loopback_base + "/article-" + item["slug"], wait_until="networkidle")
                expect(page.locator("[data-article-slug] h1")).to_have_text(item["title"])
                expect(page.locator(".article-body .article-photo")).to_have_count(2)
                for index in range(2):
                    expect(page.locator(".article-body img").nth(index)).to_have_attribute("alt", f"本文写真{index + 1}の代替テキスト")
                    expect(page.locator(".article-body figcaption").nth(index)).to_have_text(f"本文写真{index + 1}の説明")
                loaded = photos(page)
                check_logs(logs)
                return {"photos_loaded": loaded, "scope": "Local CMS-format JSON fixture, not a real CMS save"}
            finally:
                ctx.close()

        case("Multiple inline article photos on extensionless detail route", article_photos)

        def nested_not_found():
            ctx, logs = context(320)
            try:
                page = ctx.new_page()
                missing = base + "/local-route-test/missing/nested/"
                response = page.goto(missing, wait_until="networkidle")
                assert response.status == 404 and page.url == missing
                expect(page.locator("body")).to_have_attribute("data-page", "404")
                expect(page.locator("h1").first).to_be_visible()
                assert not any("/local-route-test/" in request["path"] for request in logs["requests"] if request["type"] in {"image", "stylesheet", "script", "fetch"}), logs["requests"]
                assert any(request["path"].startswith("/assets/css/") for request in logs["requests"])
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                check_logs(logs, allow_document_404=True)
                return {"status": "PASS", "http_fixture_status": 404, "scope": "Local missing-path response; absolute root assets verified"}
            finally:
                ctx.close()

        case("Nested missing URL retains 404 and root assets", nested_not_found)
        redirect_server.shutdown()
        redirect_server.server_close()
        browser.close()

    return finish(1 if any(case["status"] == "FAIL" for case in report["cases"]) else 0)


if __name__ == "__main__":
    raise SystemExit(main())
