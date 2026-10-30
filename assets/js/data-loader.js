/* =================================
   CMS CONTENT
   Data stays plain text. URLs are allowlisted; CMS never injects HTML.
================================= */
(() => {
  "use strict";
  const fileNames = ["site", "profile", "races", "sponsors", "gallery"];
  const content = {};
  const placeholderImage = "assets/images/image-unavailable.svg";
  // Preserve dimensions already calculated from the originals during the build.
  const authoredSizes = new Map(
    [...document.querySelectorAll("img[src][width][height]")].map((image) => [
      image.src, { width: Number(image.getAttribute("width")), height: Number(image.getAttribute("height")) },
    ]),
  );
  const isPlaceholder = (value) => !value || /xxx|^TBA$/i.test(String(value));
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  };
  const safeUrl = (value, localOnly = false) => {
    if (typeof value !== "string" || !value.trim()) return null;
    try {
      const url = new URL(value, document.baseURI);
      if (!["https:", "http:"].includes(url.protocol)) return null;
      if (url.username || url.password) return null;
      if (localOnly && url.origin !== location.origin) return null;
      // Never downgrade visitors to an external unencrypted destination.
      if (url.origin !== location.origin && url.protocol !== "https:")
        return null;
      return url.href;
    } catch {
      return null;
    }
  };
  const setLink = (anchor, value, track) => {
    const url = safeUrl(value);
    if (!url) return false;
    anchor.href = url;
    if (new URL(url).origin !== location.origin) {
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
    }
    if (track) anchor.dataset.track = track;
    return true;
  };
  const getValue = (key) =>
    key.split(".").reduce((value, part) => value?.[part], content);
  const imageSource = (value) => {
    if (isPlaceholder(value)) return null;
    const url = safeUrl(value, true);
    // Images uploaded through the configured CMS media folder only.
    return url && ["/assets/images/", "/assets/optimized/"].some((prefix) => new URL(url).pathname.includes(prefix))
      ? url
      : null;
  };
  const loadPhoto = (figure, source, mobileSource) => {
    const image =
      figure.querySelector("[data-photo-image]") || figure.querySelector("img");
    if (!image) return;
    // An authored HTML photo still works while its CMS field is an xxx slot.
    // A real CMS path takes precedence; unsafe URLs never become image sources.
    const actual = isPlaceholder(source)
      ? imageSource(image.getAttribute("src"))
      : imageSource(source);
    const mobile = imageSource(mobileSource);
    const picture = image.closest("picture");
    const hero = figure.closest(".hero-photo");
    const setLoaded = (loaded) => {
      figure.classList.toggle("is-loaded", loaded);
      hero?.classList.toggle("is-loaded", loaded);
    };
    figure.dataset.photo = actual || source || "";
    const label = figure.querySelector(".photo-label > span");
    if (label)
      label.textContent = String(actual || source || "xxx")
        .split("/")
        .pop();
    if (!actual) {
      setLoaded(false);
      return;
    }
    // A placeholder load can finish after handlers are installed. Check the
    // actual selected resource before hiding labels or showing the photo overlay.
    const markLoaded = () => {
      const selected = image.currentSrc || image.src;
      if (image.complete && image.naturalWidth > 0 &&
          (selected === actual || selected === mobile)) setLoaded(true);
    };
    setLoaded(false);
    image.onload = markLoaded;
    image.onerror = () => {
      // A missing mobile crop must not hide an otherwise valid desktop photo.
      if (mobile && picture?.querySelector("source") &&
          (image.currentSrc === mobile || window.matchMedia("(max-width: 767px)").matches)) {
        picture.querySelectorAll("source").forEach((entry) => entry.remove());
        image.removeAttribute("srcset");
        if (image.src !== actual) image.src = actual;
        // Removing <source> starts resource selection even if img.src is unchanged.
        return;
      }
      image.onload = null;
      image.onerror = null;
      image.removeAttribute("srcset");
      picture?.querySelectorAll("source").forEach((entry) => entry.remove());
      image.src = placeholderImage;
      image.alt = "写真を表示できませんでした";
      setLoaded(false);
    };
    picture?.querySelectorAll("source[data-photo-source]").forEach((entry) => entry.remove());
    if (mobile) {
      const sourceNode = node("source");
      sourceNode.media = "(max-width: 767px)";
      sourceNode.srcset = mobile;
      sourceNode.dataset.photoSource = "";
      picture?.prepend(sourceNode);
    }
    // Do not assign an already-loaded src again: the initial HTML and warm cache
    // use this same path, and may have fired load before the JSON request ended.
    if (image.src !== actual) image.src = actual;
    markLoaded();
  };
  const photoNode = (source, alt = "池田優介のレース活動", mobileSource, dimensions = {}) => {
    const figure = node("figure", "photo-slot");
    const picture = node("picture");
    const image = node("img");
    image.src = placeholderImage;
    image.alt = String(alt || "池田優介のレース活動");
    const validSize = (width, height) =>
      Number.isInteger(Number(width)) &&
      Number.isInteger(Number(height)) &&
      Number(width) > 0 &&
      Number(height) > 0 &&
      Number(width) <= 30000 &&
      Number(height) <= 30000;
    const reserved = validSize(dimensions.width, dimensions.height)
      ? dimensions
      : authoredSizes.get(imageSource(source));
    if (reserved && validSize(reserved.width, reserved.height)) {
      image.width = Number(reserved.width);
      image.height = Number(reserved.height);
    } else {
      image.width = 1600;
      image.height = 1067;
    }
    image.loading = "lazy";
    image.decoding = "async";
    image.dataset.photoImage = "";
    picture.append(image);
    const mark = node("span", "photo-mark", "+");
    mark.setAttribute("aria-hidden", "true");
    const label = node("span", "photo-label", "写真を読み込み中です");
    label.append(
      node(
        "span",
        "",
        String(source || "xxx")
          .split("/")
          .pop(),
      ),
    );
    figure.append(picture, mark, label);
    loadPhoto(figure, source, mobileSource);
    if (validSize(dimensions.mobileWidth, dimensions.mobileHeight)) {
      picture.querySelectorAll("source").forEach((entry) => {
        entry.width = Number(dimensions.mobileWidth);
        entry.height = Number(dimensions.mobileHeight);
      });
    }
    return figure;
  };
  const bindText = () => {
    document.querySelectorAll("[data-bind]").forEach((element) => {
      const value = getValue(element.dataset.bind);
      if (value !== undefined && value !== null)
        element.textContent = String(value);
    });
    document.querySelectorAll("[data-photo-bind]").forEach((figure) => {
      const key = figure.dataset.photoBind;
      if (key === "site.heroImage")
        figure.querySelector("img").alt = content.site?.heroAlt || "xxx";
      else if (figure.querySelector("img")?.alt === "xxx")
        figure.querySelector("img").alt = "池田優介のレース活動";
      loadPhoto(
        figure,
        getValue(key),
        key === "site.heroImage" ? content.site?.heroMobileImage : null,
      );
    });
    // Slots with no CMS binding remain explicit xxx placeholders.
    document
      .querySelectorAll(".photo-slot[data-photo]:not([data-photo-bind])")
      .forEach((figure) => {
        loadPhoto(figure, figure.dataset.photo);
      });
  };
  const renderCareer = () => {
    if (!Array.isArray(content.profile?.career)) return;
    document.querySelectorAll("[data-career]").forEach((list) => {
      list.replaceChildren(
        ...content.profile.career.map((item) => {
          const row = node("li");
          const body = node("div");
          body.append(
            node("h3", "", item.title || "xxx"),
            node("p", "", item.description || "xxx"),
          );
          row.append(node("span", "career-year", item.year || "xxx"), body);
          return row;
        }),
      );
    });
  };
  const renderRiderMessage = () => {
    if (!content.profile) return;
    const message = content.profile.message;
    document.querySelectorAll("[data-profile-message]").forEach((section) => {
      section.hidden = typeof message !== "string" || !message.trim();
      section.querySelectorAll("[data-profile-message-note]").forEach((note) => {
        note.hidden = content.profile.messageIsSample !== true;
      });
    });
  };
  const renderStories = () => {
    if (!Array.isArray(content.profile?.stories)) return;
    document.querySelectorAll("[data-stories]").forEach((list) => {
      list.replaceChildren(
        ...content.profile.stories.map((item, index) => {
          const article = node("article", "story-row");
          const photo = photoNode(item.image, item.title);
          photo.classList.add("reveal-image");
          const body = node(
            "div",
            `story-copy ${index % 2 ? "reveal-left" : "reveal-right"}`,
          );
          body.append(
            node(
              "span",
              "story-number",
              item.number || String(index + 1).padStart(2, "0"),
            ),
            node("h3", "", item.title || "xxx"),
            node("p", "", item.body || "xxx"),
          );
          article.append(photo, body);
          return article;
        }),
      );
    });
  };
  const renderRaces = () => {
    const data = content.races;
    if (!data) return;
    document.querySelectorAll("[data-next]").forEach((element) => {
      element.textContent = String(data.next?.[element.dataset.next] || "TBA");
    });
    document.querySelectorAll("[data-next-pending]").forEach((element) => {
      element.hidden =
        !isPlaceholder(data.next?.date) && !isPlaceholder(data.next?.circuit);
    });
    document.querySelectorAll("[data-race-table]").forEach((table) => {
      const items = data[table.dataset.raceTable];
      if (!Array.isArray(items) || !items.length) return;
      table.replaceChildren(
        ...items.map((item) => {
          const row = node("tr");
          ["round", "date", "circuit", "qualify", "race", "point"].forEach(
            (key) => {
              const cell = node("td", "", item[key] ?? "—");
              if (key === "circuit" && !isPlaceholder(item.url)) {
                const anchor = node("a", "", item[key] || "TBA");
                if (setLink(anchor, item.url)) cell.replaceChildren(anchor);
              }
              row.append(cell);
            },
          );
          return row;
        }),
      );
    });
  };
  const renderGallery = () => {
    if (!Array.isArray(content.gallery?.items)) return;
    document.querySelectorAll("[data-gallery]").forEach((grid) => {
      grid.replaceChildren(
        ...content.gallery.items.map((item, index) => {
          const button = node("button", "gallery-item reveal-image");
          button.type = "button";
          button.dataset.lightbox = "";
          button.dataset.src = imageSource(item.image) || "xxx";
          button.dataset.caption = item.caption || `フォトギャラリー ${index + 1}`;
          button.setAttribute(
            "aria-label",
            `ギャラリー ${index + 1} を拡大：${item.alt || `池田優介 フォトギャラリー ${index + 1}`}`,
          );
          const marker = node(
            "span",
            "gallery-index",
            String(index + 1).padStart(2, "0"),
          );
          const arrow = node("span", "", "↗");
          arrow.setAttribute("aria-hidden", "true");
          marker.append(arrow);
          const photo = photoNode(item.image, item.alt, item.mobileImage, item);
          const image = photo.querySelector("img");
          // Uploaded photos also fit without manually entered dimensions.
          const fitPhoto = () => {
            if (!imageSource(image.currentSrc) || !image.naturalWidth) return;
            image.width = image.naturalWidth;
            image.height = image.naturalHeight;
          };
          image.addEventListener("load", fitPhoto);
          if (image.complete) fitPhoto();
          button.append(photo, marker);
          return button;
        }),
      );
    });
  };
  const renderSponsors = () => {
    if (!Array.isArray(content.sponsors?.items)) return;
    document.querySelectorAll("[data-sponsors]").forEach((list) => {
      if (!content.sponsors.items.length) return;
      list.replaceChildren(
        ...content.sponsors.items.map((item) => {
          const card = node("div", "sponsor-logo");
          const name = node("p", "", item.name || "xxx");
          const logo = imageSource(item.logo);
          if (logo) {
            const image = node("img");
            image.src = logo;
            image.alt = item.name || "xxx";
            image.width = Number.isInteger(item.logoWidth) && item.logoWidth > 0 ? item.logoWidth : 240;
            image.height = Number.isInteger(item.logoHeight) && item.logoHeight > 0 ? item.logoHeight : 100;
            image.loading = "lazy";
            image.decoding = "async";
            card.append(image);
          }
          card.append(name);
          if (item.category)
            card.append(node("p", "fine-print", item.category));
          const anchor = node("a");
          if (
            !isPlaceholder(item.url) &&
            setLink(anchor, item.url, "sponsor_click")
          ) {
            anchor.append(card);
            return anchor;
          }
          return card;
        }),
      );
    });
  };
  const renderSocials = () => {
    if (!Array.isArray(content.site?.socials)) return;
    const normalize = window.RacingSocialLinks?.normalize;
    if (typeof normalize !== "function") return;
    const profiles = normalize(content.site.socials);
    document.querySelectorAll("[data-socials]").forEach((list) => {
      const full = list.dataset.socials === "full";
      list.replaceChildren(
        ...profiles.map((item) => {
            const anchor = node("a");
            const valid = setLink(anchor, item.url, "social_click");
            if (!valid) anchor.removeAttribute("href");
            anchor.target = "_blank";
            anchor.rel = "noopener noreferrer";
            anchor.dataset.socialPlatform = item.platform;
            const pending = item.platform === "facebook" && item.url === "https://www.facebook.com/";
            const destination = `${item.label} ${item.handle}（${pending ? "Facebookトップ・" : ""}新しいタブで開く）`;
            anchor.title = destination;
            anchor.setAttribute(
              "aria-label",
              destination,
            );
            const svg = document.createElementNS(
              "http://www.w3.org/2000/svg",
              "svg",
            );
            svg.setAttribute("aria-hidden", "true");
            const use = document.createElementNS(
              "http://www.w3.org/2000/svg",
              "use",
            );
            use.setAttribute(
              "href",
              `assets/icons/brands.svg#${item.platform}`,
            );
            svg.append(use);
            anchor.append(svg);
            if (full) {
              const label = node("span", "", item.label || item.platform);
              label.append(
                document.createTextNode(" "),
                node("small", "", item.handle || "xxx"),
              );
              const arrow = node("span", "", "↗");
              arrow.setAttribute("aria-hidden", "true");
              anchor.append(label, arrow);
            }
            return anchor;
        }),
      );
      if (full && !profiles.length) {
        list.append(node("p", "social-unavailable", "SNS情報は準備中です。"));
      }
    });
  };
  const configureServices = () => {
    const site = content.site;
    if (!site) return;
    let hasDirectContact = false;
    let hasForm = false;
    document.querySelectorAll("[data-contact]").forEach((element) => {
      const key = element.dataset.contact;
      const value = site[key];
      if (isPlaceholder(value)) return;
      const valid =
        key === "email"
          ? /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)
          : /^[+\d\s()-]{6,30}$/.test(value);
      if (!valid) return;
      hasDirectContact = true;
      const anchor = node("a", "", value);
      anchor.href =
        (key === "email" ? "mailto:" : "tel:") + value.replace(/[\r\n]/g, "");
      element.replaceChildren(anchor);
    });
    const formContainer = document.querySelector("[data-contact-form]");
    const formUrl = safeUrl(site.googleFormUrl);
    if (formContainer && !isPlaceholder(site.googleFormUrl) && formUrl) {
      const url = new URL(formUrl);
      if (
        url.protocol === "https:" &&
        url.hostname === "docs.google.com" &&
        /^\/forms\/(?:d\/e\/|d\/)[\w-]+\/viewform$/.test(url.pathname)
      ) {
        url.searchParams.set("embedded", "true");
        const iframe = formContainer.querySelector("iframe.contact-frame") || node("iframe", "contact-frame");
        if (iframe.src !== url.href) iframe.src = url.href;
        const formHeight = Number(site.googleFormHeight);
        iframe.height = String(Number.isInteger(formHeight) && formHeight >= 500 && formHeight <= 6000 ? formHeight : 2081);
        iframe.width = "640";
        iframe.title = "池田優介 お問い合わせフォーム（Google Forms）";
        iframe.loading = "lazy";
        iframe.referrerPolicy = "strict-origin-when-cross-origin";
        if (!iframe.isConnected) formContainer.replaceChildren(iframe);
        document.querySelectorAll("[data-form-link]").forEach((anchor) => {
          const external = new URL(url);
          external.searchParams.delete("embedded");
          anchor.href = external.href;
          anchor.hidden = false;
        });
        hasForm = true;
      }
    }
    if (formContainer && !hasForm) {
      formContainer.replaceChildren(node("p", "form-placeholder", "お問い合わせフォームは現在準備中です。公開中の連絡先がある場合は、そちらからお問い合わせください。"));
      document.querySelectorAll("[data-form-link]").forEach((anchor) => { anchor.hidden = true; });
    }
    const contactNotice = document.querySelector("[data-contact-notice]");
    if (contactNotice && hasForm) contactNotice.hidden = true;
    else if (contactNotice && hasDirectContact)
      contactNotice.textContent =
        "フォームは準備中です。公開中の連絡先からお問い合わせください。";
    if (hasForm || hasDirectContact) {
      document.querySelectorAll(".contact-direct dd").forEach((element) => {
        if (!element.querySelector("a")) element.closest("div").hidden = true;
      });
    }
    document.querySelectorAll(".contact-direct").forEach((list) => {
      list.hidden = !list.querySelector("a");
    });
    document.querySelectorAll("[data-sponsor-pdf]").forEach((element) => {
      if (isPlaceholder(site.sponsorPdf)) return;
      const anchor = node("a", "text-link", "スポンサー資料を見る ↗");
      if (setLink(anchor, site.sponsorPdf, "sponsor_click"))
        element.replaceChildren(anchor);
    });
    // xxx GA4 ID: only a real public measurement ID enables external analytics.
    if (
      /^G-[A-Z0-9]{6,20}$/.test(site.ga4Id) &&
      !site.ga4Id.includes("XXXXX")
    ) {
      window.dataLayer = window.dataLayer || [];
      window.gtag = function () {
        window.dataLayer.push(arguments);
      };
      window.gtag("js", new Date());
      window.gtag("config", site.ga4Id);
      const script = node("script");
      script.async = true;
      script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(site.ga4Id)}`;
      document.head.append(script);
      if (document.body.dataset.page === "contact")
        window.gtag("event", "contact_page_view");
    }
  };
  Promise.allSettled(
    fileNames.map(async (name) => {
      const version = document.querySelector('meta[name="publication-id"]')?.content;
      const query = version ? `?v=${encodeURIComponent(version)}` : "";
      const response = await fetch(`data/${name}.json${query}`, { cache: "no-cache" });
      if (!response.ok) throw new Error(`Content unavailable: ${name}`);
      content[name] = await response.json();
    }),
  )
    .then((results) => {
      bindText();
      renderRiderMessage();
      renderCareer();
      renderStories();
      renderRaces();
      renderGallery();
      renderSponsors();
      renderSocials();
      configureServices();
      if (results.some((result) => result.status === "rejected")) {
        const notice = node(
          "p",
          "data-notice",
          "一部の最新情報を取得できませんでした。時間をおいて再読み込みしてください。",
        );
        notice.setAttribute("role", "status");
        document.querySelector("main")?.append(notice);
      }
      document.dispatchEvent(new Event("content:updated"));
    })
    .catch(() => {
      // Keep authored static content readable if a malformed CMS entry interrupts enhancements.
      document.documentElement.classList.remove("motion-ready");
      console.warn(
        "コンテンツの更新に失敗しました。公開データの形式を確認してください。",
      );
    });
})();
