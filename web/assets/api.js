// Brain-Focusing Game MVP - 前端 API 封装
const API = {
  async json(url, options = {}) {
    const r = await fetch(url, options);
    if (!r.ok) {
      let msg = r.statusText;
      try {
        const e = await r.json();
        msg = e.detail || msg;
      } catch (_) { /* ignore */ }
      throw new Error(msg);
    }
    return r.json();
  },

  post(url, body) {
    return this.json(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  },

  get(url) { return this.json(url); },

  // SSE 会话流：onFrame(entry), onHello(meta), onEnd(), onError(err), onStatus("live"|"reconnecting")
  // 自愈机制：6 秒内收不到任何数据（连接挂起/keep-alive 复用竞态）→ 自动重建，最多重试 4 次
  stream(sessionId, { onFrame, onHello, onEnd, onError, onStatus }) {
    let es = null;
    let alive = false;
    let attempts = 0;
    let firstTimer = null;

    function connect() {
      es = new EventSource(`/api/session/${sessionId}/stream`);
      firstTimer = setTimeout(() => {
        if (alive) return;
        onStatus && onStatus("reconnecting");
        try { es.close(); } catch (_) { /* ignore */ }
        if (attempts < 4) { attempts += 1; connect(); }
        else onError && onError(new Error("实时连接不稳定，已停止自动重试"));
      }, 6000);

      es.addEventListener("hello", (e) => {
        alive = true;
        attempts = 0;
        onStatus && onStatus("live");
        onHello && onHello(JSON.parse(e.data));
      });
      es.addEventListener("frame", (e) => {
        alive = true;
        onFrame && onFrame(JSON.parse(e.data));
      });
      es.addEventListener("end", (e) => {
        clearTimeout(firstTimer);
        es.close();
        onEnd && onEnd(JSON.parse(e.data));
      });
      es.onerror = () => {
        // 收到过数据后断线：立即重连；首次连接失败交给 firstTimer 统一处理
        if (!alive) return;
        onStatus && onStatus("reconnecting");
        try { es.close(); } catch (_) { /* ignore */ }
        if (attempts < 4) { attempts += 1; connect(); }
        else onError && onError(new Error("实时连接已断开"));
      };
    }
    connect();

    return {
      close() { clearTimeout(firstTimer); if (es) es.close(); },
      get state() { return es ? es.readyState : -1; },
    };
  },
};

// 跨页共享：会话参数与校准基线都存 localStorage。
// 校准基线有效期 1 小时：期间刷新、关闭页面/标签页甚至浏览器都无需重新校准；
// 超过 1 小时自动失效，必须回到校准页重新校准。
const Store = {
  CALIB_KEY: "bf-calib",
  CALIB_TTL_MS: 60 * 60 * 1000,   // 1 小时

  save(sid, baseline, source) {
    localStorage.setItem("bf-session", JSON.stringify({
      session_id: sid, baseline, source, at: Date.now(),
    }));
  },
  load() {
    try { return JSON.parse(localStorage.getItem("bf-session")) || null; }
    catch (_) { return null; }
  },
  clear() {
    localStorage.removeItem("bf-session");
    this.clearCalib();
  },

  // 读取校准记录并判断是否仍在有效期内。
  // 返回 { calib, expired, remainMs }：calib 为 null 表示不可用。
  calibInfo() {
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(this.CALIB_KEY)) || null; }
    catch (_) { raw = null; }

    // 兼容旧版本（曾经写在 sessionStorage，且没有时间戳）：迁移一次，按当前时间起算
    if (!raw) {
      try {
        const legacy = JSON.parse(sessionStorage.getItem(this.CALIB_KEY)) || null;
        if (legacy && legacy.baseline != null) {
          raw = { baseline: legacy.baseline, quantiles: legacy.quantiles, at: Date.now() };
          localStorage.setItem(this.CALIB_KEY, JSON.stringify(raw));
        }
        sessionStorage.removeItem(this.CALIB_KEY);
      } catch (_) { /* ignore */ }
    }

    if (!raw || raw.baseline == null) return { calib: null, expired: false, remainMs: 0 };
    const at = Number(raw.at);
    if (!Number.isFinite(at)) return { calib: null, expired: true, remainMs: 0 };
    const remainMs = this.CALIB_TTL_MS - (Date.now() - at);
    if (remainMs <= 0) return { calib: null, expired: true, remainMs: 0 };
    return { calib: raw, expired: false, remainMs };
  },

  saveCalib(baseline, quantiles) {
    const payload = { baseline, quantiles, at: Date.now() };
    localStorage.setItem(this.CALIB_KEY, JSON.stringify(payload));
    try { sessionStorage.removeItem(this.CALIB_KEY); } catch (_) { /* ignore */ }
    return payload;
  },

  // 只返回仍在有效期内的校准；过期的会被清理掉
  loadCalib() {
    const info = this.calibInfo();
    if (info.expired) this.clearCalib();
    return info.calib;
  },

  // 距离校准失效还剩多少毫秒（无有效校准时为 0）
  calibRemainMs() {
    return this.calibInfo().remainMs;
  },

  clearCalib() {
    localStorage.removeItem(this.CALIB_KEY);
    try { sessionStorage.removeItem(this.CALIB_KEY); } catch (_) { /* ignore */ }
  },
};

function toast(msg) {
  let el = document.querySelector(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 2600);
}
