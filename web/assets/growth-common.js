/* v1.9.0 成长中心共用工具：所有数据来自本地 API，不依赖 CDN。 */
(function () {
  "use strict";

  function qs(params) {
    const out = new URLSearchParams();
    Object.keys(params || {}).forEach(key => {
      const value = params[key];
      if (value !== undefined && value !== null && value !== "") out.set(key, value);
    });
    return out.toString();
  }

  async function api(path, params) {
    const uid = window.Profile && window.Profile.userId ? window.Profile.userId() : null;
    const suffix = qs(Object.assign({ user_id: uid }, params || {}));
    const response = await fetch(path + (suffix ? "?" + suffix : ""), {
      headers: uid ? { "X-User-Id": uid } : {},
      cache: "no-store",
    });
    let body = null;
    try { body = await response.json(); } catch (_) { body = {}; }
    if (!response.ok) {
      const detail = body && (body.detail || body.message);
      throw new Error(detail || ("请求失败：" + response.status));
    }
    return body;
  }

  function tz() {
    try { return new Date().getTimezoneOffset(); } catch (_) { return undefined; }
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  function num(value, digits) {
    if (value === null || value === undefined || value === "") return "数据不足";
    const n = Number(value);
    if (!Number.isFinite(n)) return "数据不足";
    const d = digits === undefined ? 0 : digits;
    const fixed = n.toFixed(d);
    return d ? fixed.replace(/\.?0+$/, "") : fixed;
  }

  function pct(value) {
    if (value === null || value === undefined) return "数据不足";
    const n = Number(value);
    return Number.isFinite(n) ? (n * 100).toFixed(1).replace(".0", "") + "%" : "数据不足";
  }

  function duration(seconds) {
    if (seconds === null || seconds === undefined) return "数据不足";
    let total = Math.max(0, Math.round(Number(seconds) || 0));
    if (total < 60) return total + " 秒";
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    if (h) return h + " 小时 " + m + " 分";
    return m + " 分钟";
  }

  function minutes(seconds) {
    if (seconds === null || seconds === undefined) return "数据不足";
    return (Math.max(0, Number(seconds) || 0) / 60).toFixed(1).replace(".0", "");
  }

  function dateText(value) {
    return value ? String(value).replace("T", " ").slice(0, 16) : "数据不足";
  }

  function badge(kind, label) {
    return '<span class="growth-badge growth-badge--' + esc(kind) + '">' + esc(label) + "</span>";
  }

  async function download(fmt, range, start, end) {
    const uid = window.Profile && window.Profile.userId ? window.Profile.userId() : null;
    const suffix = qs({ user_id: uid, range: range, start: start, end: end,
      tz_offset_min: tz() });
    const response = await fetch("/api/growth/export/" + fmt + "?" + suffix, {
      headers: uid ? { "X-User-Id": uid } : {},
    });
    if (!response.ok) {
      let detail = "导出失败";
      try { detail = (await response.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    const blob = await response.blob();
    const disp = response.headers.get("Content-Disposition") || "";
    let filename = "专注小蛙_成长报告." + fmt;
    const star = /filename\*=UTF-8''([^;]+)/i.exec(disp);
    const plain = /filename=\"?([^\";]+)\"?/i.exec(disp);
    if (star) filename = decodeURIComponent(star[1]);
    else if (plain) filename = plain[1];
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 3000);
    return {
      filename: filename,
      saved: response.headers.get("X-Report-Relative-Path")
        ? decodeURIComponent(response.headers.get("X-Report-Relative-Path")) : "",
    };
  }

  window.GrowthCommon = { qs, api, tz, esc, num, pct, duration, minutes, dateText,
    badge, download };
})();
