#!/usr/bin/env python3
"""Regression tests for canonical social profiles and static/runtime parity."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest

from social_links import normalize_social_links, update_social_html
from build import update_page

ROOT = Path(__file__).resolve().parents[1]


def entry(platform="instagram", url=None, handle="@xxx", **extra):
    return {"platform": platform, "url": url, "handle": handle, **extra}


def normalized(platform, name, url, handle=None):
    return {"platform": platform, "label": {"instagram": "Instagram", "x": "X", "facebook": "Facebook"}[platform],
            "handle": handle or "@" + name, "url": url}


CASES = [
    ([entry(url="https://instagram.com/Example_42/?igsh=tracking#bio", handle="@stale")], [normalized("instagram", "Example_42", "https://www.instagram.com/Example_42/")]),
    ([entry(url="https://m.instagram.com/example.name")], [normalized("instagram", "example.name", "https://www.instagram.com/example.name/")]),
    ([entry("x", "https://mobile.twitter.com/Example_42?ref=web", "@stale")], [normalized("x", "Example_42", "https://x.com/Example_42")]),
    ([entry("x", "", "@Example_42")], [normalized("x", "Example_42", "https://x.com/Example_42")]),
    ([entry(url="xxx", handle="Example_42")], [normalized("instagram", "Example_42", "https://www.instagram.com/Example_42/")]),
    ([entry(url="https://instagram.com/xxx", handle="@Example_42")], [normalized("instagram", "Example_42", "https://www.instagram.com/Example_42/")]),
    ([entry("x", "https://x.com/xxx", "@local_test_29")], [normalized("x", "local_test_29", "https://x.com/local_test_29")]),
    ([entry("x", "https://mobile.twitter.com/XXX/?ref=old", "@local_test_29")], [normalized("x", "local_test_29", "https://x.com/local_test_29")]),
    ([entry("facebook", "https://www.facebook.com/xxx", "@Example.Name")], [normalized("facebook", "Example.Name", "https://www.facebook.com/Example.Name/", "@Example.Name")]),
    ([entry(url="https://evil.example/xxx", handle="@Example_42")], []),
    ([entry(url="https://instagram.com.evil.example/xxx", handle="@Example_42")], []),
    ([entry(url="https://user:password@instagram.com/xxx", handle="@Example_42")], []),
    ([entry("x", "https://@x.com/xxx", "@local_test_29")], []),
    ([entry("x", "https://x.com:444/xxx", "@local_test_29")], []),
    ([entry("x", "http://x.com/xxx", "@local_test_29")], []),
    ([entry("x", "https://x.com/xxx/status/123", "@local_test_29")], []),
    ([entry(url="https://instagram.com/abcxxx")], [normalized("instagram", "abcxxx", "https://www.instagram.com/abcxxx/")]),
    ([entry("x", "https://x.com/abcxxx")], [normalized("x", "abcxxx", "https://x.com/abcxxx")]),
    ([entry(url="https://www.instagram.com/Example_42:443")], []),
    ([entry(url="https://www.instagram.com:443/Example_42")], [normalized("instagram", "Example_42", "https://www.instagram.com/Example_42/")]),
    ([entry(url="https://instagram.com/xxx"), entry("x", "https://x.com/xxx"), entry("facebook", "https://facebook.com/xxx")], []),
    ([entry(handle="@xxx"), entry("x", "TBA", "TBA")], []),
    ([entry(url="javascript:alert(1)", handle="@Example_42")], []),
    ([entry(url="https://evil.example/Example_42", handle="@Example_42")], []),
    ([entry(url="https://user:password@instagram.com/Example_42", handle="@Example_42")], []),
    ([entry(url="http://instagram.com/Example_42", handle="@Example_42")], []),
    ([entry(url="//instagram.com/Example_42", handle="@Example_42")], []),
    ([entry(url="https:instagram.com/Example_42")], []),
    ([entry(url="https:///instagram.com/Example_42")], []),
    ([entry(url="https://%69nstagram.com/Example_42")], []),
    ([entry(url="https://instagram.com/名前")], []),
    ([entry(url="https://instagram.com/%45xample_42")], []),
    ([entry(url="https://instagram.com/foo/../Example_42")], []),
    ([entry(url="https://instagram.com/p"), entry("x", "https://x.com/HOME")], []),
    ([entry(url="https://instagram.com/reel/123")], []),
    ([entry("x", "https://x.com/intent/follow?screen_name=Example_42")], []),
    ([entry("x", "https://x.com/" + "a" * 16)], []),
    ([entry(url="https://instagram.com/" + "a" * 31)], []),
    ([entry(handle="."), entry("x", "", "..")], []),
    ([entry(url=42, handle="@Example_42")], []),
    ([entry("facebook", "https://m.facebook.com/profile.php?id=123456&tracking=1", "池田優介")], [normalized("facebook", "123456", "https://www.facebook.com/profile.php?id=123456", "池田優介")]),
    ([entry("facebook", "https://facebook.com/people/Example-Name/123456/?ref=1")], [normalized("facebook", "Example-Name", "https://www.facebook.com/people/Example-Name/123456/")]),
    ([entry("facebook", "https://facebook.com/profile.php?id=123&id=")], []),
    ([entry("facebook", "https://facebook.com/profile.php?id=abc")], []),
    ([entry("facebook", "https://facebook.com/Example.Name", "<script>")], [normalized("facebook", "Example.Name", "https://www.facebook.com/Example.Name/")]),
    ([entry("facebook", "https://facebook.com/login")], []),
    ([entry("instagram", "https://instagram.com/First", label="wrong"), entry("instagram", "https://instagram.com/Second")], [normalized("instagram", "First", "https://www.instagram.com/First/")]),
    ([None, False, {}, entry("unsupported", "https://example.test/")], []),
    ({"items": []}, []),
]


class SocialLinksTests(unittest.TestCase):
    def test_normalization(self):
        for items, expected in CASES:
            with self.subTest(items=items):
                self.assertEqual(normalize_social_links(items), expected)

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional for JavaScript parity tests")
    def test_javascript_python_parity(self):
        script = r'''const fs=require('fs');const vm=require('vm');const context={window:{},URL};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const inputs=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(inputs.map(input=>context.window.RacingSocialLinks.normalize(input))));'''
        process = subprocess.run(["node", "-e", script, str(ROOT / "assets/js/social-links.js")],
                                 input=json.dumps([items for items, _ in CASES], ensure_ascii=False),
                                 text=True, capture_output=True, check=True)
        results = json.loads(process.stdout)
        self.assertEqual(results, [expected for _, expected in CASES])

    def test_static_rows_replace_stale_links_and_handle(self):
        template = '<div class="header-socials" data-socials="icons"><a href="https://x.com/xxx">old</a></div><section><div data-socials="full"><a>@xxx</a></div></section>'
        items = normalize_social_links([entry("x", "https://twitter.com/Example_42?ref=old", "@old")])
        rendered = update_social_html(template, items)
        self.assertNotIn("xxx", rendered)
        self.assertNotIn("@old", rendered)
        self.assertEqual(rendered.count('href="https://x.com/Example_42"'), 2)
        self.assertIn("@Example_42", rendered)
        self.assertIn('rel="noopener noreferrer"', rendered)
        self.assertIn('assets/icons/brands.svg#x', rendered)
        empty = update_social_html(template, [])
        self.assertNotIn("<a", empty)
        self.assertIn("SNS情報は準備中です。", empty)

    def test_build_normalizes_without_runtime_javascript(self):
        template = '<div data-socials="full"><a href="https://instagram.com/xxx">@xxx</a></div>'
        rendered = update_page(template, "https://example.test/", {"socials": [entry(url="https://instagram.com/Example_42", handle="@wrong")]})
        self.assertIn('href="https://www.instagram.com/Example_42/"', rendered)
        self.assertIn("@Example_42", rendered)
        self.assertNotIn("@wrong", rendered)
        self.assertNotIn("xxx", rendered)
        self.assertNotIn("<a", update_page(template, "https://example.test/", {"socials": []}))


if __name__ == "__main__":
    unittest.main()
