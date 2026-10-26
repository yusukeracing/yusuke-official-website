/* =================================
   HEADER / MOBILE NAVIGATION
   All interactions are enhancements; links work without JavaScript.
================================= */
(() => {
  "use strict";

  const header = document.querySelector("#site-header");
  const sentinel = document.querySelector("#header-sentinel");
  if (header && sentinel && "IntersectionObserver" in window) {
    new IntersectionObserver(([entry]) => {
      header.classList.toggle("is-scrolled", !entry.isIntersecting);
    }).observe(sentinel);
  }

  const toggle = document.querySelector(".menu-toggle");
  const navigation = document.querySelector("#primary-navigation");
  if (toggle && navigation) {
    const isOpen = () => toggle.getAttribute("aria-expanded") === "true";
    const setOpen = (open, restoreFocus = false) => {
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute(
        "aria-label",
        open ? "MENU メニューを閉じる" : "MENU メニューを開く",
      );
      navigation.classList.toggle("is-open", open);
      document.body.classList.toggle("menu-open", open);
      if (open) navigation.querySelector("a, button")?.focus();
      if (!open && restoreFocus) toggle.focus();
    };
    toggle.addEventListener("click", () => setOpen(!isOpen()));
    navigation.addEventListener("click", (event) => {
      if (event.target.closest("a")) setOpen(false);
    });
    document.addEventListener("click", (event) => {
      if (
        isOpen() &&
        !navigation.contains(event.target) &&
        !toggle.contains(event.target)
      ) {
        setOpen(false);
      }
    });
    document.addEventListener("keydown", (event) => {
      if (!isOpen()) return;
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false, true);
      }
      if (event.key !== "Tab") return;
      const controls = [
        toggle,
        ...navigation.querySelectorAll("a[href], button:not([disabled])"),
      ].filter((element) => element.getClientRects().length);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    });
    window.addEventListener(
      "resize",
      () => {
        if (isOpen() && getComputedStyle(toggle).display === "none")
          setOpen(false);
      },
      { passive: true },
    );
  }

  /* =================================
     GALLERY LIGHTBOX
     Native dialog supplies modal focus containment and Escape support.
  ================================= */
  const dialog = document.querySelector("#lightbox");
  if (dialog && typeof dialog.showModal === "function") {
    const image = dialog.querySelector(".lightbox-image");
    const photo = dialog.querySelector(".lightbox-photo");
    const caption = dialog.querySelector(".lightbox-caption");
    const count = dialog.querySelector(".lightbox-count");
    const placeholder = dialog.querySelector("[data-lightbox-placeholder]");
    let items = [];
    let index = 0;
    let trigger = null;
    let request = 0;

    const showImage = () => {
      const item = items[index];
      if (!item || !image) return;
      const currentRequest = ++request;
      const source = item.dataset.src || "";
      const description =
        item.dataset.caption || item.getAttribute("aria-label") || "xxx";
      if (caption) caption.textContent = description;
      if (count)
        count.textContent = `${String(index + 1).padStart(2, "0")} / ${String(items.length).padStart(2, "0")}`;
      photo?.classList.add("is-placeholder");
      image.hidden = true;
      image.removeAttribute("src");
      image.alt = description;
      if (placeholder)
        placeholder.textContent = source.split("/").pop() || "xxx PHOTO";
      let url;
      try {
        url = new URL(source, document.baseURI);
      } catch {
        return;
      }
      // An unfilled xxx slot is intentionally not a real photograph.
      if (
        !source ||
        source.includes("xxx") ||
        !/^https?:$/.test(url.protocol) ||
        url.origin !== location.origin
      )
        return;
      image.onload = () => {
        if (request !== currentRequest) return;
        image.hidden = false;
        photo?.classList.remove("is-placeholder");
      };
      image.onerror = () => {
        if (request !== currentRequest) return;
        image.hidden = true;
        photo?.classList.add("is-placeholder");
      };
      image.loading = "eager";
      image.src = url.href;
    };
    const move = (direction) => {
      if (!items.length) return;
      index = (index + direction + items.length) % items.length;
      showImage();
    };
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-lightbox]");
      if (!button) return;
      event.preventDefault();
      items = [...document.querySelectorAll("[data-lightbox]")];
      index = items.indexOf(button);
      trigger = button;
      showImage();
      dialog.showModal();
      document.body.classList.add("lightbox-open");
    });
    dialog
      .querySelector("[data-lightbox-close]")
      ?.addEventListener("click", () => dialog.close());
    dialog
      .querySelector("[data-lightbox-prev]")
      ?.addEventListener("click", () => move(-1));
    dialog
      .querySelector("[data-lightbox-next]")
      ?.addEventListener("click", () => move(1));
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        move(event.key === "ArrowLeft" ? -1 : 1);
      }
    });
    dialog.addEventListener("click", (event) => {
      if (event.target !== dialog) return;
      const bounds = dialog.getBoundingClientRect();
      if (
        event.clientX < bounds.left ||
        event.clientX > bounds.right ||
        event.clientY < bounds.top ||
        event.clientY > bounds.bottom
      )
        dialog.close();
    });
    dialog.addEventListener("close", () => {
      request += 1;
      document.body.classList.remove("lightbox-open");
      image?.removeAttribute("src");
      trigger?.focus({ preventScroll: true });
    });
  }

  /* =================================
     ANALYTICS EVENTS
     GA4 is loaded only after a valid public measurement ID is configured.
  ================================= */
  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-track]");
    if (!target || typeof window.gtag !== "function") return;
    window.gtag("event", target.dataset.track, {
      event_label:
        target.getAttribute("aria-label") ||
        target.textContent.trim().slice(0, 100),
      link_url: target.href || "",
      transport_type: "beacon",
    });
  });
})();
