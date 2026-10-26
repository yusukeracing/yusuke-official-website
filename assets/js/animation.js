/* =================================
   ONE INTRO PER SESSION
   No JavaScript or reduced motion: the page is immediately available.
================================= */
(() => {
  "use strict";

  const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
  const intro = document.querySelector("#intro");
  if (intro) {
    let viewed = false;
    try {
      viewed = sessionStorage.getItem("yusuke-intro-viewed") === "1";
      sessionStorage.setItem("yusuke-intro-viewed", "1");
    } catch {
      // Storage can be unavailable in private or embedded contexts.
      // Skip the intro rather than showing it repeatedly during navigation.
      viewed = true;
    }
    if (!viewed && !preference.matches) {
      intro.hidden = false;
      window.setTimeout(() => intro.classList.add("is-leaving"), 850);
      window.setTimeout(() => {
        intro.hidden = true;
      }, 1350);
    }
  }

  /* =================================
     SCROLL REVEAL
     IntersectionObserver only signals visibility; CSS does the animation.
  ================================= */
  const selector =
    ".reveal, .reveal-left, .reveal-right, .reveal-scale, .reveal-image";
  if (!("IntersectionObserver" in window) || preference.matches) return;

  const observed = new WeakSet();
  const makeVisible = (element) => element.classList.add("is-visible");
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const element = entry.target;
        observer.unobserve(element);
        const images = [...element.querySelectorAll("img")].filter(
          (image) =>
            image.hasAttribute("src") &&
            !image.complete &&
            !image.closest(".is-placeholder"),
        );
        if (!images.length) {
          makeVisible(element);
          return;
        }
        const loading = Promise.all(
          images.map(
            (image) =>
              new Promise((resolve) => {
                image.addEventListener("load", resolve, { once: true });
                image.addEventListener("error", resolve, { once: true });
              }),
          ),
        );
        // Slow or unavailable media must never leave page content invisible.
        Promise.race([
          loading,
          new Promise((resolve) => window.setTimeout(resolve, 2500)),
        ]).then(() => makeVisible(element));
      });
    },
    { rootMargin: "0px 0px 8% 0px", threshold: 0.04 },
  );

  const observeContent = () => {
    document.querySelectorAll(selector).forEach((element) => {
      if (observed.has(element)) return;
      observed.add(element);
      observer.observe(element);
    });
  };
  document.documentElement.classList.add("motion-ready");
  observeContent();
  document.addEventListener("content:updated", observeContent);
  preference.addEventListener("change", () => {
    if (!preference.matches) return;
    document.documentElement.classList.remove("motion-ready");
    observer.disconnect();
    if (intro) intro.hidden = true;
  });
})();
