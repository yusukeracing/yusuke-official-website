/* =================================
   PUBLIC PARTNERS / APPROVED SUPPORT MESSAGES
   JSON contains published information only. CMS values stay plain text.
================================= */
(() => {
  "use strict";
  const directory = document.querySelector("[data-partner-directory]");
  const messages = document.querySelector("[data-message-list]");
  const container = directory || messages;
  if (!container) return;

  const text = (value) => typeof value === "string" ? value.trim() : "";
  const element = (tag, className, value) => {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (value !== undefined) item.textContent = value;
    return item;
  };
  const safeLink = (value) => {
    if (!text(value) || /xxx/i.test(value)) return null;
    try {
      const url = new URL(value, document.baseURI);
      if (url.username || url.password) return null;
      if (url.protocol !== "https:" && !(url.protocol === "http:" && url.origin === location.origin)) return null;
      return url;
    } catch { return null; }
  };
  const safeImage = (value) => {
    const url = safeLink(value);
    if (!url || url.origin !== location.origin) return null;
    try {
      const path = decodeURIComponent(url.pathname);
      const folders = ["assets/images/", "assets/optimized/"].map((folder) => new URL(folder, document.baseURI).pathname);
      if (!folders.some((folder) => path.startsWith(folder)) || path.split("/").includes("..")) return null;
      if (!/\.(?:avif|webp|png|jpe?g|svg)$/i.test(path)) return null;
      return url.href;
    } catch { return null; }
  };
  const dateValue = (value) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(text(value))) return null;
    const date = new Date(value + "T00:00:00Z");
    if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== value) return null;
    return value;
  };
  const updateStatus = (count) => {
    const status = document.querySelector("[data-community-status]");
    if (status) status.textContent = directory ? `${count}件のパートナー情報` : `${count}件の応援メッセージ`;
    document.dispatchEvent(new Event("content:updated"));
  };
  const emptyState = () => {
    const notice = element("div", "community-empty");
    notice.append(
      element("h2", "", directory ? "パートナー情報は準備中です。" : "応援メッセージをお待ちしています。"),
      element("p", "", directory ? "掲載する情報が決まり次第、こちらでご紹介します。" : "掲載のご了承をいただいたメッセージを、こちらでご紹介します。"),
    );
    return notice;
  };
  const renderPartners = (items) => items.map((item) => {
    const name = text(item?.name);
    if (!name || name === "xxx") return null;
    const article = element("article", "partner-entry reveal");
    const logoArea = element("div", "partner-logo-area");
    const logo = safeImage(item.logo);
    if (logo) {
      const image = element("img");
      image.src = logo;
      image.alt = `${name} ロゴ`;
      image.width = Number.isInteger(item.logoWidth) && item.logoWidth > 0 ? item.logoWidth : 480;
      image.height = Number.isInteger(item.logoHeight) && item.logoHeight > 0 ? item.logoHeight : 240;
      image.loading = "lazy";
      image.decoding = "async";
      image.addEventListener("error", () => {
        image.remove();
        logoArea.append(element("span", "partner-logo-fallback", name));
      }, { once: true });
      logoArea.append(image);
    } else logoArea.append(element("span", "partner-logo-fallback", name));
    const copy = element("div", "partner-copy");
    if (text(item.category)) copy.append(element("p", "eyebrow", text(item.category)));
    copy.append(element("h2", "", name));
    if (text(item.description)) copy.append(element("p", "partner-description", text(item.description)));
    const url = safeLink(item.url);
    if (url) {
      const link = element("a", "text-link", "公式サイトを見る ");
      link.href = url.href;
      link.dataset.track = "sponsor_click";
      const arrow = element("span", "", "↗");
      arrow.setAttribute("aria-hidden", "true");
      link.append(arrow);
      if (url.origin !== location.origin) {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.setAttribute("aria-label", `${name} 公式サイトを見る（新しいタブで開く）`);
      }
      copy.append(link);
    }
    article.append(logoArea, copy);
    return article;
  }).filter(Boolean);
  const renderMessages = (items) => items.map((item, index) => {
    const name = text(item?.name);
    const message = text(item?.message);
    if (!name || !message || name === "xxx" || message === "xxx") return null;
    const article = element("article", "support-message reveal");
    const number = element("span", "message-number", String(index + 1).padStart(2, "0"));
    number.setAttribute("aria-hidden", "true");
    const heading = element("h2", "message-name", name);
    const body = element("p", "message-text", message);
    article.append(number, heading, body);
    const publishedDate = dateValue(item.date);
    if (publishedDate) {
      const time = element("time", "message-date", publishedDate.replaceAll("-", "."));
      time.dateTime = publishedDate;
      article.append(time);
    }
    return article;
  }).filter(Boolean);

  const file = directory ? "sponsors" : "messages";
  const version = document.querySelector('meta[name="publication-id"]')?.content;
  const query = version ? `?v=${encodeURIComponent(version)}` : "";
  fetch(`data/${file}.json${query}`, { cache: "no-cache" })
    .then((response) => {
      if (!response.ok) throw new Error("Content unavailable");
      return response.json();
    })
    .then((data) => {
      if (!Array.isArray(data?.items)) throw new Error("Invalid public content");
      const entries = directory ? renderPartners(data.items) : renderMessages(data.items);
      // A successful empty response is a real deletion, including when the
      // document was cached before the CMS entry was removed.
      container.replaceChildren(...(entries.length ? entries : [emptyState()]));
      updateStatus(entries.length);
    })
    .catch(() => {
      // A failed request is not an empty list. Keep the compiled information
      // readable and explain that its freshness could not be checked.
      const notice = element("p", "data-notice", "最新情報を確認できませんでした。掲載済みの情報を表示しています。時間をおいて再読み込みしてください。");
      container.before(notice);
      const status = document.querySelector("[data-community-status]");
      if (status) status.textContent = "最新情報の確認に失敗しました。掲載済みの情報は引き続き表示しています。";
    });
})();
