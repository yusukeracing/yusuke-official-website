/* Social profile URLs are authoritative; placeholder accounts never become links. */
(() => {
  "use strict";
  const labels = { instagram: "Instagram", x: "X", facebook: "Facebook" };
  const hosts = {
    instagram: ["instagram.com", "www.instagram.com", "m.instagram.com"],
    x: ["x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"],
    facebook: ["facebook.com", "www.facebook.com", "m.facebook.com", "mbasic.facebook.com"],
  };
  const reserved = {
    instagram: ["p", "reel", "reels", "stories", "direct", "explore", "accounts"],
    x: ["home", "intent", "i", "search", "settings", "compose", "hashtag", "messages", "notifications", "explore", "login", "signup", "share"],
    facebook: ["login", "login.php", "share", "sharer.php", "dialog", "reel", "reels", "groups", "messages", "events", "plugins", "watch", "help", "reg", "settings"],
  };
  const patterns = { instagram: /^[A-Za-z0-9._]{1,30}$/, x: /^[A-Za-z0-9_]{1,15}$/, facebook: /^[A-Za-z0-9._-]{1,100}$/ };
  const placeholder = (value) => value == null || typeof value === "string" && ["", "xxx", "@xxx", "tba"].includes(value.trim().toLowerCase());
  const username = (platform, value) => patterns[platform].test(value) && ![".", ".."].includes(value) && !placeholder(value) && !reserved[platform].includes(value.toLowerCase());
  const facebookHandle = (value) => {
    if (typeof value !== "string") return "";
    value = value.trim();
    return placeholder(value) || Array.from(value).length > 100 || /[\x00-\x1f\x7f<>]/.test(value) || value.includes("://") ? "" : value;
  };
  const officialPlaceholderURL = (platform, value) => {
    if (typeof value !== "string") return false;
    value = value.trim();
    const authority = value.match(/^https:\/\/([^/?#]+)/i);
    if (!authority || /[%@]/.test(authority[1]) || /[^\x00-\x7f]|[\x00-\x20\x7f\\]/.test(value) || /\/(?:\.|\.\.)(?:\/|[?#]|$)/.test(value)) return false;
    let url;
    try { url = new URL(value); } catch { return false; }
    return url.protocol === "https:" && hosts[platform].includes(url.hostname) &&
      !url.username && !url.password && !url.port &&
      url.pathname.replace(/^\/+|\/+$/g, "").toLowerCase() === "xxx";
  };
  const normalize = (items) => {
    const result = [];
    const seen = new Set();
    if (!Array.isArray(items)) return result;
    for (const item of items) {
      if (!item || typeof item !== "object" || typeof item.platform !== "string") continue;
      const platform = item.platform.trim().toLowerCase();
      if (!Object.hasOwn(labels, platform) || seen.has(platform)) continue;
      let raw = item.url;
      if (placeholder(raw) || officialPlaceholderURL(platform, raw)) {
        if (typeof item.handle !== "string") continue;
        const name = item.handle.trim().replace(/^@/, "");
        if (!username(platform, name)) continue;
        raw = `https://${platform}.com/${name}`;
      }
      if (typeof raw !== "string") continue;
      raw = raw.trim();
      const authority = raw.match(/^https:\/\/([^/?#]+)/i);
      if (!authority || /[%@]/.test(authority[1]) || /[^\x00-\x7f]|[\x00-\x20\x7f\\]/.test(raw) || /\/(?:\.|\.\.)(?:\/|[?#]|$)/.test(raw)) continue;
      let url;
      try { url = new URL(raw); } catch { continue; }
      if (url.protocol !== "https:" || !hosts[platform].includes(url.hostname) || url.username || url.password || url.port) continue;
      const path = url.pathname.replace(/^\/+|\/+$/g, "");
      let name, canonical;
      if (platform === "facebook" && path === "profile.php") {
        const values = url.searchParams.getAll("id");
        if (values.length !== 1 || !/^[0-9]+$/.test(values[0])) continue;
        name = values[0];
        canonical = `https://www.facebook.com/profile.php?id=${name}`;
      } else if (platform === "facebook" && /^people\/[A-Za-z0-9._-]+\/[0-9]+$/.test(path)) {
        name = path.split("/")[1];
        if (placeholder(name)) continue;
        canonical = `https://www.facebook.com/${path}/`;
      } else {
        if (!username(platform, path)) continue;
        name = path;
        canonical = platform === "instagram" ? `https://www.instagram.com/${name}/` : platform === "x" ? `https://x.com/${name}` : `https://www.facebook.com/${name}/`;
      }
      const handle = platform === "facebook" ? facebookHandle(item.handle) : "";
      result.push({ platform, label: labels[platform], handle: handle || `@${name}`, url: canonical });
      seen.add(platform);
    }
    return result;
  };
  window.RacingSocialLinks = Object.freeze({ normalize });
})();
