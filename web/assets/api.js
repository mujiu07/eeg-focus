// Brain-Focusing Game MVP - 前端 API 封装
function activeUserId() {
  try {
    const raw = JSON.parse(localStorage.getItem("bf-active-user") || "null");
    return raw && typeof raw.user_id === "string" ? raw.user_id : null;
  } catch (_) { return null; }
}

function withUserHeader(headers) {
  const h = Object.assign({}, headers || {});
  const uid = activeUserId();
  if (uid && !h["X-User-Id"] && !h["x-user-id"]) h["X-User-Id"] = uid;
  return h;
}

const API = {
  async json(url, options = {}) {
    const opts = Object.assign({}, options, {
      headers: withUserHeader(options.headers),
    });
    const r = await fetch(url, opts);
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

  endAbandonedSession(sessionId) {
    return fetch(`/api/session/${sessionId}/finish`, {
      method: "POST",
      headers: withUserHeader({ "Content-Type": "application/json" }),
      body: JSON.stringify({ played_sec: 0, notes: "abandoned" }),
      keepalive: true,
    }).catch(() => {});
  },

  async replayPairs() {
    const { edf_files: files = [] } = await this.get("/api/player/replay");
    const tasks = new Map(files.filter(file => file.segment === 2)
      .map(file => [file.subject, file]));
    return files.filter(file => file.segment === 1 && tasks.has(file.subject))
      .map(rest => ({ rest, task: tasks.get(rest.subject) }));
  },

  // SSE 会话流：onFrame(entry), onHello(meta), onEnd(), onError(err), onStatus("live"|"reconnecting")
  // 连接和数据流分别计时，连续失败最多重试 4 次。
  stream(sessionId, { onFrame, onHello, onEnd, onError, onStatus }) {
    let es = null;
    let attempts = 0;
    let timer = null;

    function disconnect() {
      clearTimeout(timer);
      if (es) es.close();
      es = null;
    }

    function reconnect(connection) {
      if (es !== connection) return;
      disconnect();
      if (attempts >= 4) {
        onError?.(new Error("实时连接不稳定，已停止自动重试"));
        return;
      }
      attempts += 1;
      timer = setTimeout(connect, 500 * attempts);
      onStatus?.("reconnecting");
    }

    function connect() {
      const uid = activeUserId();
      const streamUrl = `/api/session/${sessionId}/stream` + (uid ? `?user_id=${encodeURIComponent(uid)}` : "");
      const connection = new EventSource(streamUrl);
      es = connection;

      function watchForData(timeout) {
        clearTimeout(timer);
        timer = setTimeout(() => reconnect(connection), timeout);
      }

      watchForData(6000);
      connection.addEventListener("hello", (e) => {
        if (es !== connection) return;
        // OSC 等待窗口超时需要 8 秒，留出余量接收后端的异常帧。
        watchForData(10000);
        onStatus?.("live");
        onHello?.(JSON.parse(e.data));
      });
      connection.addEventListener("frame", (e) => {
        if (es !== connection) return;
        attempts = 0;
        watchForData(10000);
        onFrame?.(JSON.parse(e.data));
      });
      connection.addEventListener("end", (e) => {
        if (es !== connection) return;
        disconnect();
        onEnd?.(JSON.parse(e.data));
      });
      connection.onerror = () => reconnect(connection);
    }
    connect();

    return {
      close: disconnect,
      get state() { return es ? es.readyState : EventSource.CLOSED; },
    };
  },
};

// 本地界面分流：试玩入口只从开发者页启动，授权仅在当前标签页有效。
const DeveloperTools = {
  key: "bf-dev-testing",
  enable() { sessionStorage.setItem(this.key, "1"); },
  disable() { sessionStorage.removeItem(this.key); },
  get canTest() { return sessionStorage.getItem(this.key) === "1"; },
};

function describeSignal(source = {}) {
  const file = source.file?.split(/[/\\]/).pop();
  const match = file?.match(/^Subject(\d+)_([12])\.edf$/i);
  if (match) return "脑电回放 · 被试 " + match[1] + " · " + (match[2] === "1" ? "放松段" : "心算段");
  if (file || source.name === "replay") return file ? "脑电回放 · " + file : "脑电回放";
  return ({ manual: "手动模拟", hardware: "Xmuse 脑电", heart: "心率" })[source.name] || "未知信号";
}

// 跨页共享：会话参数与校准基线都存 localStorage。
// v1.8.2：同一天、同设备、4 小时内可复用；跨本地日期或换设备必须重新校准。
// 服务端会再次校验每日校准，不能只靠这份缓存。
const Store = {
  CALIB_KEY: "bf-calib",
  SESSION_KEY: "bf-session",
  storage: localStorage,
  CALIB_TTL_MS: 4 * 60 * 60 * 1000,   // 4 小时；跨本地日期仍强制重校

  forDeveloperTest() {
    return { ...this, CALIB_KEY: "bf-dev-calib", SESSION_KEY: "bf-dev-session", storage: sessionStorage };
  },

  playerCalibInfo() {
    const info = this.calibInfo();
    const mode = this.load()?.source?.mode;
    // 旧版本可能将回放或滑块的基线存成了玩家校准。
    return ["hardware", "heart"].includes(mode) ? info : { ...info, calib: null, expired: false };
  },

  save(sid, baseline, source) {
    this.storage.setItem(this.SESSION_KEY, JSON.stringify({
      session_id: sid, baseline, source, at: Date.now(),
    }));
  },
  load() {
    try { return JSON.parse(this.storage.getItem(this.SESSION_KEY)) || null; }
    catch (_) { return null; }
  },
  clear() {
    this.storage.removeItem(this.SESSION_KEY);
    this.clearCalib();
  },

  // 读取校准记录并判断是否仍在有效期内。
  // 返回 { calib, expired, remainMs }：calib 为 null 表示不可用。
  calibInfo() {
    let raw = null;
    try { raw = JSON.parse(this.storage.getItem(this.CALIB_KEY)) || null; }
    catch (_) { raw = null; }

    // 兼容旧版本（曾经写在 sessionStorage，且没有时间戳）：迁移一次，按当前时间起算
    if (!raw && this.storage === localStorage) {
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
    const oldDate = new Date(at);
    const nowDate = new Date();
    if (oldDate.toDateString() !== nowDate.toDateString()) {
      return { calib: null, expired: true, remainMs: 0, reason: "date_changed" };
    }
    const remainMs = this.CALIB_TTL_MS - (Date.now() - at);
    if (remainMs <= 0) return { calib: null, expired: true, remainMs: 0, reason: "expired" };
    return { calib: raw, expired: false, remainMs };
  },

  saveCalib(baseline, quantiles, range, calibrationId, meta) {
    const payload = { baseline, quantiles, range: range || null, at: Date.now(), ...(meta || {}) };
    if (calibrationId) payload.calibration_id = calibrationId;
    this.storage.setItem(this.CALIB_KEY, JSON.stringify(payload));
    if (this.storage === localStorage) {
      try { sessionStorage.removeItem(this.CALIB_KEY); } catch (_) { /* ignore */ }
    }
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
    this.storage.removeItem(this.CALIB_KEY);
    if (this.storage === localStorage) {
      try { sessionStorage.removeItem(this.CALIB_KEY); } catch (_) { /* ignore */ }
    }
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
