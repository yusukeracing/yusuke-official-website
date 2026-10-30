/* Plain text and ordered photo blocks from Pages CMS; no HTML is executed. */
(() => {
  "use strict";
  const lists = [...document.querySelectorAll("[data-news-list]")];
  const detail = document.querySelector("[data-article-slug]");
  if (!lists.length && !detail) return;
  const base = new URL("../../", document.currentScript.src);
  const labels = { ACTIVITY: "活動報告", RACE: "レース", INFORMATION: "お知らせ", MEDIA: "メディア" };
  const slugPattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
  const status = document.querySelector("[data-news-load-status]");
  const announce = (text) => { if (status) status.textContent = text; };
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text != null) element.textContent = String(text);
    return element;
  };
  const text = (value) => typeof value === "string" ? value.trim() : "";
  const imagePath = (value) => {
    value = text(value);
    let decoded;
    try { decoded = decodeURIComponent(value); } catch { return ""; }
    if (!/^(?:assets\/images\/|assets\/optimized\/)/.test(value) || /[?#]/.test(value) ||
        /[\x00-\x1f\x7f\\]/.test(decoded) || decoded.split("/").some(part => ["", ".", ".."].includes(part)) ||
        !/\.(?:jpe?g|png|webp|avif|gif)$/i.test(value)) return "";
    return value;
  };
  const link = (value) => {
    value = text(value);
    if (!value || /[\x00-\x20\x7f\\]/.test(value)) return null;
    try {
      const url = new URL(value, base);
      if (url.username || url.password || !["http:", "https:"].includes(url.protocol) ||
          url.origin !== base.origin && url.protocol !== "https:" || value.startsWith("/") ||
          decodeURIComponent(value).split("/").includes("..")) return null;
      return url;
    } catch { return null; }
  };
  const filename = (item) => `article-${item.slug}.html`;
  const normalize = (data) => {
    if (!data || !Array.isArray(data.items)) throw new Error("Invalid news data");
    const seen = new Set();
    return data.items.filter(item => item && item.published !== false).map((item) => {
      if (typeof item.slug !== "string" || item.slug.length > 80 || !slugPattern.test(item.slug) || seen.has(item.slug) ||
          !text(item.title) || !/^\d{4}-\d{2}-\d{2}$/.test(text(item.date)) ||
          item.published != null && typeof item.published !== "boolean") throw new Error("Invalid article");
      seen.add(item.slug);
      const blocks = Array.isArray(item.blocks) ? item.blocks : [];
      return { ...item, title: text(item.title), description: text(item.description),
        category: text(item.category).toUpperCase() || "ACTIVITY", image: imagePath(item.image),
        imageAlt: text(item.imageAlt), imageCaption: text(item.imageCaption),
        blocks: blocks.filter(block => block && ["text", "image"].includes(block.type)) };
    }).sort((a, b) => b.date.localeCompare(a.date));
  };
  const photo = (source, alt, caption, className, width, height) => {
    const image = imagePath(source);
    if (!image || !text(alt)) return null;
    const figure = node("figure", className);
    const img = node("img");
    img.src = new URL(image, base).href;
    img.alt = text(alt);
    const validDimensions = [width, height].every(value => typeof value !== "boolean" && Number.isInteger(Number(value)) && Number(value) > 0 && Number(value) <= 30000);
    img.width = validDimensions ? Number(width) : 1600;
    img.height = validDimensions ? Number(height) : 1067;
    img.loading = "lazy";
    img.decoding = "async";
    // Actual published dimensions may be supplied by the media build pipeline.
    img.addEventListener("load", () => {
      if (img.naturalWidth && img.naturalHeight) {
        img.width = img.naturalWidth;
        img.height = img.naturalHeight;
      }
    }, { once: true });
    figure.append(img);
    if (text(caption)) figure.append(node("figcaption", "", caption));
    return figure;
  };
  const paragraphs = (container, value) => {
    text(value).split(/\n\s*\n/).filter(Boolean).forEach(part => {
      container.append(node("p", "article-paragraph", part));
    });
  };
  let items = null;
  let selected = "all";
  const listItem = (item) => {
    const article = node("article", "news-item");
    article.dataset.newsCategory = item.category;
    const time = node("time", "", item.date.replaceAll("-", "."));
    time.dateTime = item.date;
    const heading = node("h3");
    const anchor = node("a", "", item.title);
    anchor.href = new URL(filename(item), base).href;
    heading.append(anchor);
    article.append(time, node("span", "news-category", labels[item.category] || item.category), heading);
    if (item.isSample === true) article.append(node("p", "news-sample-note", "仮原稿"));
    if (item.description) article.append(node("p", "news-description", item.description.split(/\n\s*\n/)[0]));
    const thumbnail = photo(item.image, item.imageAlt, item.imageCaption, "news-thumbnail", item.imageWidth, item.imageHeight);
    if (thumbnail) article.append(thumbnail);
    const more = node("a", "news-read-more", "記事を読む →");
    more.href = anchor.href;
    article.append(more);
    return article;
  };
  const renderLists = () => {
    if (!items) return;
    const filtered = items.filter(item => selected === "all" || item.category === selected);
    lists.forEach(list => {
      const limit = Number(list.dataset.limit) || 0;
      const visible = limit ? filtered.slice(0, limit) : filtered;
      if (visible.length) list.replaceChildren(...visible.map(listItem));
      else {
        const empty = node("div", "empty-state");
        empty.append(node("p", "", selected === "all" ? "新しいお知らせを準備しています。" : "このカテゴリーのお知らせはまだありません。"));
        list.replaceChildren(empty);
      }
    });
    document.querySelectorAll("[data-news-status]").forEach(element => {
      element.textContent = `${filtered.length}件の記事`;
    });
  };
  const renderDetail = () => {
    if (!detail || !items) return;
    const item = items.find(item => item.slug === detail.dataset.articleSlug);
    if (!item) {
      const title = node("h1", "", "記事が見つかりません。");
      const explanation = node("p", "article-paragraph", "この記事は公開を終了したか、公開準備中です。");
      const back = node("a", "text-link", "活動報告一覧へ戻る ←");
      back.href = new URL("news.html", base).href;
      detail.replaceChildren(title, explanation, back);
      document.title = "記事が見つかりません | 池田優介";
      let robots = document.querySelector('meta[name="robots"]');
      if (!robots) { robots = document.createElement("meta"); robots.name = "robots"; document.head.append(robots); }
      robots.content = "noindex, follow";
      announce("この記事は公開を終了したか、公開準備中です。活動報告一覧をご確認ください。");
      return;
    }
    const heading = node("header", "article-heading");
    const meta = node("p", "article-meta");
    const time = node("time", "", item.date.replaceAll("-", "."));
    time.dateTime = item.date;
    meta.append(time, document.createTextNode(` / ${labels[item.category] || item.category}`));
    heading.append(node("p", "eyebrow", "ACTIVITY & NEWS"), meta, node("h1", "", item.title));
    const body = node("div", "article-body");
    paragraphs(body, item.description);
    item.blocks.forEach(block => {
      if (block.type === "text") paragraphs(body, block.text);
      else {
        const figure = photo(block.image, block.alt, block.caption, "article-photo", block.width, block.height);
        if (figure) body.append(figure);
      }
    });
    const content = [heading];
    if (item.isSample === true) content.push(node("p", "news-sample-note", "仮原稿"));
    const thumbnail = photo(item.image, item.imageAlt, item.imageCaption, "article-photo", item.imageWidth, item.imageHeight);
    if (thumbnail) content.push(thumbnail);
    content.push(body);
    const destination = link(item.url);
    if (destination) {
      const related = node("p");
      const anchor = node("a", "text-link", "関連ページを見る ↗");
      anchor.href = destination.href;
      if (destination.origin !== base.origin) { anchor.target = "_blank"; anchor.rel = "noopener noreferrer"; }
      related.append(anchor);
      content.push(related);
    }
    const back = node("p", "article-back");
    const anchor = node("a", "text-link", "活動報告一覧へ戻る ←");
    anchor.href = new URL("news.html", base).href;
    back.append(anchor);
    content.push(back);
    detail.replaceChildren(...content);
    document.title = `${item.title} | 池田優介`;
  };
  document.querySelectorAll("[data-news-filter]").forEach(button => {
    button.addEventListener("click", () => {
      selected = button.dataset.newsFilter;
      document.querySelectorAll("[data-news-filter]").forEach(other => {
        const active = other === button;
        other.classList.toggle("is-active", active);
        other.setAttribute("aria-pressed", String(active));
      });
      renderLists();
    });
  });
  announce("最新の記事を確認しています…");
  const dataURL = new URL("data/news.json", base);
  const publicationID = document.querySelector('meta[name="publication-id"]')?.content;
  if (publicationID) dataURL.searchParams.set("v", publicationID);
  fetch(dataURL, { cache: "no-cache" })
    .then(response => {
      if (!response.ok) throw new Error("News unavailable");
      return response.json();
    }).then(data => {
      items = normalize(data);
      renderLists();
      renderDetail();
      if (!detail || items.some(item => item.slug === detail.dataset.articleSlug)) announce("最新の記事を表示しています。");
      document.dispatchEvent(new Event("content:updated"));
    }).catch(() => {
      announce("最新情報を確認できませんでした。掲載済みの記事を表示しています。時間をおいて再読み込みしてください。");
    });
})();
