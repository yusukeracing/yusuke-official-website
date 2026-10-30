#!/usr/bin/env python3
"""Optional Chromium release checks; every request is fulfilled locally.
Run after build.py --normal-preview --output dist-preview.
No real CMS save, OAuth, external SNS navigation or Google form POST occurs.
Chromium viewport emulation is not an iPhone, Safari, Edge or branded Chrome.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import json,mimetypes,re,shutil,time
from pathlib import Path
from urllib.parse import unquote,urlsplit
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
PAGES=["index.html","profile.html","race.html","news.html","sponsor.html","support.html","contact.html","partners.html","messages.html","404.html","maintenance.html"]
PORTRAITS=[(320,568),(375,667),(390,844),(430,932),(768,1024),(1024,1366),(1366,1920),(1920,2560)]
FORM='<!doctype html><html lang="ja"><meta charset="utf-8"><title>Local form display fixture</title><main>表示確認用のローカル代替フォームです。送信処理はありません。</main></html>'

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--directory",type=Path,default=ROOT/"dist-preview")
    ap.add_argument("--report",type=Path,default=ROOT/"docs/release-browser-results.json")
    ap.add_argument("--screenshots",type=Path,default=Path("/tmp/yusuke-release-screenshots"))
    ap.add_argument("--browser",default=shutil.which("chromium"))
    ap.add_argument("--quick",action="store_true")
    args=ap.parse_args();artifact=args.directory.resolve();started=time.monotonic()
    report={"checked_at":datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),"artifact":str(artifact),
      "network":"all responses intercepted and supplied from local files; no real form POST",
      "browser":{"engine":"Chromium","binary":args.browser,"brand":"system Chromium, not Google Chrome or Edge"},"cases":[],
      "viewport_definition":"portrait pairs are CSS viewport width/height; landscape swaps each pair",
      "not_executed":[
        {"item":"Physical iPhone/Android/iPad/Android tablet/PC","reason":"No attached physical devices"},
        {"item":"Real Safari/iOS Safari/macOS Safari/Edge/branded Chrome","reason":"Only system Chromium installed; emulation is not verification of these browsers"},
        {"item":"WebKit engine","reason":"Download blocked by network proxy (403), as recorded by parent"},
        {"item":"Real Pages CMS save UI/Git commit/public CDN round trip","reason":"Browser CRUD uses local JSON fixtures"},
        {"item":"Real Google Forms acceptance and owner receipt","reason":"Non-submitting local display fixture only"},
        {"item":"Production HTTPS certificate/HTTP security headers/external SNS availability","reason":"Local intercepted responses do not verify live services"}]}
    report["cases"].extend({"name":item["item"],"status":"SKIP","reason":item["reason"]} for item in report["not_executed"])
    def finish(code):
        report["elapsed_seconds"]=round(time.monotonic()-started,2)
        report["summary"]={s:sum(c["status"]==s for c in report["cases"]) for s in ("PASS","FAIL","SKIP")}
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
        print(json.dumps(report["summary"]),flush=True);return code
    try:
        from playwright.sync_api import sync_playwright,expect
    except ImportError:
        report["cases"].append({"name":"browser suite","status":"SKIP","reason":"Python Playwright is not installed"});return finish(2)
    if not args.browser:
        report["cases"].append({"name":"browser suite","status":"SKIP","reason":"System Chromium not installed"});return finish(2)
    try:
        site=json.loads((artifact/"data/site.json").read_text())
        publication=json.loads((artifact/"data/publication.json").read_text())
        assert site.get("maintenanceEnabled") is False,"Use --normal-preview artifact"
    except Exception as e:
        report["cases"].append({"name":"artifact precondition","status":"FAIL","error":str(e)});return finish(1)
    base=site["url"].rstrip("/");origin=urlsplit(base);prefix=origin.path.rstrip("/")+"/"
    gallery=json.loads((artifact/"data/gallery.json").read_text())["items"]
    news=json.loads((artifact/"data/news.json").read_text())
    articles=[x for x in news["items"] if x.get("published",True)]
    details=publication.get("articlePages") or [f'article-{x["slug"]}.html' for x in articles]
    pages=list(dict.fromkeys(PAGES+details));report["pages"]=pages
    report["publication_id"]=publication.get("contentId",publication.get("id"))
    viewports=[(390,844,"portrait"),(1366,768,"landscape")] if args.quick else [(w,h,"portrait") for w,h in PORTRAITS]+[(h,w,"landscape") for w,h in PORTRAITS]
    report["viewports"]=[{"width":w,"height":h,"orientation":o} for w,h,o in viewports]
    args.screenshots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=args.browser,args=["--no-sandbox","--disable-dev-shm-usage"])
        report["browser"]["version"]=browser.version
        def context(width=390,height=844,javascript=True,news_override=None,html_override=None,news_failure=False,device=None):
            device_options={key:device[key] for key in ("user_agent","is_mobile","has_touch","device_scale_factor") if device and key in device}
            ctx=browser.new_context(viewport={"width":width,"height":height},java_script_enabled=javascript,reduced_motion="reduce",**device_options)
            logs={"page_errors":[],"console_errors":[],"missing_assets":[],"unexpected_requests":[],"posts":[],"google_fixtures":0,"requests":[]}
            def route(r):
                req=r.request;u=urlsplit(req.url)
                logs["requests"].append({"path":u.path,"resource_type":req.resource_type})
                if req.method not in {"GET","HEAD"}:
                    logs["posts"].append({"method":req.method,"url":req.url.split("?")[0]});r.abort();return
                if u.scheme==origin.scheme and u.netloc==origin.netloc and u.path.startswith(prefix):
                    rel=unquote(u.path[len(prefix):]) or "index.html";f=(artifact/rel).resolve()
                    if not f.is_relative_to(artifact):logs["unexpected_requests"].append("path traversal");r.abort();return
                    if rel=="data/news.json" and news_failure:
                        r.fulfill(status=503,content_type="application/json",body='{"error":"local fixture"}');return
                    if rel=="data/news.json" and news_override is not None:
                        r.fulfill(status=200,content_type="application/json; charset=utf-8",body=json.dumps(news_override,ensure_ascii=False));return
                    if html_override and rel in html_override:
                        r.fulfill(status=200,content_type="text/html; charset=utf-8",body=html_override[rel]);return
                    if f.is_dir():f=f/"index.html"
                    status=200
                    if not f.is_file():
                        if req.resource_type not in {"document","other"}:logs["missing_assets"].append(rel)
                        status=404;f=artifact/"404.html"
                    r.fulfill(status=status,content_type=mimetypes.guess_type(f)[0] or "application/octet-stream",body=f.read_bytes())
                elif u.scheme=="https" and u.netloc=="docs.google.com" and u.path.startswith("/forms/"):
                    logs["google_fixtures"]+=1;r.fulfill(status=200,content_type="text/html; charset=utf-8",body=FORM)
                else:logs["unexpected_requests"].append(req.url.split("?")[0]);r.abort()
            ctx.route("**/*",route)
            def capture(page):
                page.on("pageerror",lambda e:logs["page_errors"].append(str(e)))
                page.on("console",lambda m:logs["console_errors"].append(m.text) if m.type=="error" and not (news_failure and "503" in m.text) else None)
            ctx.on("page",capture)
            return ctx,logs
        def clean(log):
            for key in ("page_errors","console_errors","missing_assets","unexpected_requests","posts"):assert not log[key],(key,log[key])
        def case(name,test,**metadata):
            try:
                data=test() or {};entry={"name":name,"status":"PASS",**metadata,**data};print("PASS:",name,flush=True)
            except Exception as e:
                entry={"name":name,"status":"FAIL","error":str(e)[:4000],**metadata};print("FAIL:",name,str(e)[:700],flush=True)
            report["cases"].append(entry);return entry["status"]=="PASS"
        def images(page):
            count=0
            for img in page.locator("img[src]").all():
                if not img.is_visible():continue
                img.scroll_into_view_if_needed(timeout=8000)
                expect(img).to_have_js_property("complete",True,timeout=8000)
                info=img.evaluate("""e=>{const s=getComputedStyle(e);return {src:e.getAttribute('src'),alt:e.getAttribute('alt'),
                nw:e.naturalWidth,nh:e.naturalHeight,w:e.getAttribute('width'),h:e.getAttribute('height'),fit:s.objectFit,
                filter:s.filter,transform:s.transform,opacity:s.opacity,cw:e.clientWidth,ch:e.clientHeight}}""")
                assert info["nw"]>0 and info["nh"]>0,info
                assert info["alt"] is not None and info["alt"]!="xxx" and info["w"] and info["h"],info
                assert info["fit"]=="contain" and info["filter"]=="none" and info["transform"]=="none",info
                assert float(info["opacity"])==1,info
                assert abs(float(info["w"])/float(info["h"])-info["nw"]/info["nh"])<0.03,info
                count+=1
            return count
        for width,height,orientation in viewports:
            ctx,logs=context(width,height);page=ctx.new_page()
            for filename in pages:
                def render(filename=filename):
                    response=page.goto(base+"/"+filename,wait_until="networkidle",timeout=20000);assert response.status==200
                    expect(page.locator("h1").first).to_be_visible()
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"),"horizontal overflow"
                    count=images(page)
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"),"overflow after photos load"
                    assert page.locator('a[href^="javascript:"]').count()==0
                    for a in page.locator('a[target="_blank"]').all():assert {"noopener","noreferrer"}.issubset(set((a.get_attribute("rel") or "").split()))
                    if filename=="index.html":
                        assert page.locator(".hero-frame img").evaluate("e=>e.naturalWidth>0")
                        a=page.locator(".hero-photo").bounding_box();b=page.locator(".hero-content").bounding_box();assert a and b
                        overlap=max(0,min(a["x"]+a["width"],b["x"]+b["width"])-max(a["x"],b["x"]))*max(0,min(a["y"]+a["height"],b["y"]+b["height"])-max(a["y"],b["y"]))
                        assert overlap<2,("HERO text/photo overlap",overlap)
                    if filename=="contact.html":
                        frame=page.locator("iframe.contact-frame");expect(frame).to_have_attribute("title",re.compile("Google Forms"));frame.scroll_into_view_if_needed()
                        expect(page.frame_locator("iframe.contact-frame").locator("main")).to_contain_text("ローカル")
                    if filename in {"index.html","news.html"}:
                        expect(page.locator("[data-news-list] .news-item")).to_have_count(min(3,len(articles)) if filename=="index.html" else len(articles))
                    if (width,height) in {(390,844),(1366,1920),(844,390)} and filename in {"index.html","news.html",details[0] if details else "profile.html"}:
                        page.screenshot(path=str(args.screenshots/f"{Path(filename).stem}-{width}x{height}.png"),full_page=True)
                    clean(logs);return {"loaded_photos":count}
                case(f"render {filename} {width}x{height}",render,page=filename,width=width,height=height,orientation=orientation,environment="Chromium viewport emulation")
            page.close();ctx.close()
        devices=[("iPhone 13",p.devices["iPhone 13"]),("Pixel 7",p.devices["Pixel 7"]),("iPad Pro 11",p.devices["iPad Pro 11"]),
          ("Android tablet viewport/UA fixture",{"viewport":{"width":800,"height":1280},"is_mobile":True,"has_touch":True,"device_scale_factor":1,
            "user_agent":"Mozilla/5.0 (Linux; Android 13; Tablet) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"})]
        for device_name,device in devices:
            for orientation in ("portrait","landscape"):
                w,h=device["viewport"]["width"],device["viewport"]["height"]
                if orientation=="landscape":w,h=h,w
                def emulate(device=device,w=w,h=h):
                    ctx,logs=context(w,h,device=device)
                    try:
                        page=ctx.new_page()
                        for filename in ["index.html","news.html",*details]:
                            page.goto(base+"/"+filename,wait_until="networkidle")
                            expect(page.locator("h1").first).to_be_visible()
                            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                            images(page)
                        clean(logs)
                        return {"scope":"Chromium device context emulation only; no physical device or WebKit", "touch":device.get("has_touch",False)}
                    finally:ctx.close()
                case("device context "+device_name+" "+orientation,emulate,width=w,height=h,orientation=orientation,environment="Chromium UA/touch emulation")
        def interactions():
            ctx,logs=context()
            try:
                page=ctx.new_page();page.goto(base+"/index.html",wait_until="networkidle")
                first=page.locator("[data-lightbox]").first;expect(page.locator("[data-lightbox]")).to_have_count(len(gallery))
                first.click();expect(page.locator("#lightbox")).to_be_visible();expect(page.locator(".lightbox-image")).to_be_visible()
                expect(page.locator(".lightbox-caption")).to_have_text(gallery[0]["caption"])
                page.keyboard.press("ArrowRight");expect(page.locator(".lightbox-caption")).to_have_text(gallery[1]["caption"])
                page.keyboard.press("Escape");expect(page.locator("#lightbox")).to_be_hidden();expect(first).to_be_focused()
                toggle=page.locator(".menu-toggle")
                if toggle.is_visible():
                    toggle.click();expect(toggle).to_have_attribute("aria-expanded","true")
                    page.keyboard.press("Escape");expect(toggle).to_have_attribute("aria-expanded","false");expect(toggle).to_be_focused()
                    toggle.click();page.locator('#primary-navigation a[href="news.html"]').click();expect(page.locator("body")).to_have_attribute("data-page","news")
                page.goto(base+"/news.html",wait_until="networkidle");page.locator('[data-news-filter="ACTIVITY"]').click()
                expect(page.locator(".news-item")).to_have_count(sum(x.get("category")=="ACTIVITY" for x in articles))
                page.locator('[data-news-filter="all"]').click();expect(page.locator(".news-item")).to_have_count(len(articles))
                page.goto(base+"/profile.html",wait_until="networkidle");page.keyboard.press("Tab");expect(page.locator(".skip-link")).to_be_focused();page.keyboard.press("Enter")
                clean(logs);return {"checks":["lightbox next/Escape/focus","menu Escape/focus/link","filter","keyboard skip link"]}
            finally:ctx.close()
        case("keyboard, mobile menu, gallery and filters",interactions)
        def crud():
            assert details,"Need a generated article HTML as fixture template"
            slug="local-cms-crud";filename="article-"+slug+".html"
            html=re.sub(r'(data-article-slug\s*=\s*["\'])[^"\']*',r'\g<1>'+slug,(artifact/details[0]).read_text())
            state={"items":[]};ctx,logs=context(news_override=state,html_override={filename:html})
            try:
                page=ctx.new_page();page.goto(base+"/news.html",wait_until="networkidle");expect(page.locator(".news-item")).to_have_count(0)
                one,two,three=gallery[:3]
                item={"slug":slug,"published":True,"title":"ローカル写真付き記事の作成","date":"2026-10-30","category":"ACTIVITY","description":"冒頭の文章。\n\n二段落目。",
                    "image":one["image"],"imageAlt":"サムネイルの代替テキスト","imageCaption":"サムネイル説明","imageWidth":one.get("width"),"imageHeight":one.get("height"),"url":"",
                    "blocks":[{"type":"text","text":"写真の前"},{"type":"image","image":two["image"],"alt":"本文写真の代替テキスト1","caption":"本文写真説明1","width":two.get("width"),"height":two.get("height")},
                    {"type":"text","text":"写真と写真の間"},{"type":"image","image":one["image"],"alt":"本文写真の代替テキスト2","caption":"本文写真説明2","width":one.get("width"),"height":one.get("height")}]}
                state["items"].append(item);page.reload(wait_until="networkidle");expect(page.locator(".news-item")).to_have_count(1)
                expect(page.locator(".news-thumbnail img")).to_have_attribute("alt",item["imageAlt"]);page.locator(".news-item h3 a").click()
                expect(page.locator("[data-article-slug] h1")).to_have_text(item["title"]);expect(page.locator(".article-body .article-photo")).to_have_count(2)
                expect(page.locator(".article-body img").first).to_have_attribute("alt","本文写真の代替テキスト1");expect(page.locator(".article-body figcaption").last).to_have_text("本文写真説明2")
                images(page)
                item["title"]='編集 <script>window.releaseInjected=1</script>';item["description"]='<img src=x onerror="window.releaseInjected=2">'
                item["url"]="javascript:window.releaseInjected=3"
                item["blocks"][1].update(image=three["image"],alt="変更後alt",caption="<script>window.releaseInjected=4</script>",width=three.get("width"),height=three.get("height"))
                page.reload(wait_until="networkidle");expect(page.locator("[data-article-slug] h1")).to_have_text(item["title"])
                expect(page.locator(".article-body img").first).to_have_attribute("src",base+"/"+three["image"])
                expect(page.locator(".article-body figcaption").first).to_have_text(item["blocks"][1]["caption"])
                assert page.evaluate("window.releaseInjected===undefined");assert page.locator(".article-body script").count()==0
                assert page.locator('[data-article-slug] a[href^="javascript:"]').count()==0
                item["published"]=False;page.goto(base+"/news.html",wait_until="networkidle");expect(page.locator(".news-item")).to_have_count(0)
                page.goto(base+"/"+filename,wait_until="networkidle");expect(page.locator("[data-article-slug] h1")).to_have_text("記事が見つかりません。")
                expect(page.locator('meta[name="robots"]')).to_have_attribute("content",re.compile("noindex"))
                state["items"].clear();page.goto(base+"/news.html",wait_until="networkidle");expect(page.locator(".news-item")).to_have_count(0)
                page.goto(base+"/"+filename,wait_until="networkidle");expect(page.locator("[data-article-slug] h1")).to_have_text("記事が見つかりません。")
                clean(logs);return {"scope":"local JSON fixtures, not real CMS/Git/CDN","checks":["create","thumbnail","two inline photos/order","alt/caption","edit","replace photo","XSS inert","unpublish","delete"]}
            finally:ctx.close()
        case("CMS CRUD, inline photos, and unsafe text/URL (local fixtures)",crud)
        def failure():
            ctx,logs=context(news_failure=True)
            try:
                page=ctx.new_page();page.goto(base+"/news.html",wait_until="networkidle")
                expect(page.locator("[data-news-load-status]")).to_contain_text("確認できませんでした")
                expect(page.locator(".news-item")).to_have_count(len(articles));clean(logs)
                return {"scope":"503 local JSON fixture","result":"static published article retained; failure announced"}
            finally:ctx.close()
        case("failed refresh retains static content and announces failure",failure)
        def local_performance():
            ctx,logs=context(390,844)
            try:
                ctx.add_init_script("""window.releaseCLS=0; window.releaseLCP=null;
                if(window.PerformanceObserver){
                  try{new PerformanceObserver(l=>l.getEntries().forEach(e=>{if(!e.hadRecentInput)window.releaseCLS+=e.value})).observe({type:'layout-shift',buffered:true})}catch(e){}
                  try{new PerformanceObserver(l=>{const es=l.getEntries();window.releaseLCP=es[es.length-1]?.startTime}).observe({type:'largest-contentful-paint',buffered:true})}catch(e){}
                }""")
                page=ctx.new_page();page.goto(base+"/index.html",wait_until="networkidle")
                timings=page.evaluate("""()=>{const n=performance.getEntriesByType('navigation')[0];return {dom_content_loaded_ms:n.domContentLoadedEventEnd,load_ms:n.loadEventEnd,local_fixture_lcp_ms:window.releaseLCP,local_fixture_cls:window.releaseCLS}}""")
                gallery_paths={urlsplit(base+"/"+x['image']).path for x in gallery}
                initially_loaded={x['path'] for x in logs['requests'] if x['resource_type']=='image' and x['path'] in gallery_paths}
                timings.update(scope="local route-fulfilled response timings; not production Lighthouse/Core Web Vitals",initial_gallery_images=len(initially_loaded),gallery_image_paths=len(gallery_paths),initial_requests=len(logs['requests']))
                files=list((artifact/'assets/optimized').glob('*'))
                timings['largest_optimized_file_bytes']=max((f.stat().st_size for f in files if f.is_file()),default=0)
                if len(gallery_paths)>2:assert len(initially_loaded)<len(gallery_paths),'all gallery images loaded before scrolling'
                clean(logs);return timings
            finally:ctx.close()
        case("local homepage timing and lazy gallery loading (not production performance)",local_performance)
        def nojs():
            ctx,logs=context(javascript=False)
            try:
                page=ctx.new_page()
                for filename in ["index.html","news.html","profile.html",*details]:
                    page.goto(base+"/"+filename,wait_until="networkidle");expect(page.locator("h1").first).to_be_visible()
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1");images(page)
                    if filename=="index.html":expect(page.locator("[data-gallery] .gallery-item")).to_have_count(len(gallery))
                    if filename in details:expect(page.locator("[data-article-slug] h1")).to_contain_text(articles[details.index(filename)]["title"])
                clean(logs);return {"pages":["index.html","news.html","profile.html",*details]}
            finally:ctx.close()
        case("article, gallery and main content without JavaScript",nojs)
        browser.close()
    return finish(1 if any(c["status"]=="FAIL" for c in report["cases"]) else 0)

if __name__=="__main__":
    raise SystemExit(main())
