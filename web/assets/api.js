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

// 跨页共享：会话参数存 localStorage，校准基线存 sessionStorage
const Store = {
  save(sid, baseline, source) {
    localStorage.setItem("bf-session", JSON.stringify({
      session_id: sid, baseline, source, at: Date.now(),
    }));
  },
  load() {
    try { return JSON.parse(localStorage.getItem("bf-session")) || null; }
    catch (_) { return null; }
  },
  clear() { localStorage.removeItem("bf-session"); },

  saveCalib(baseline, quantiles) {
    sessionStorage.setItem("bf-calib", JSON.stringify({ baseline, quantiles }));
  },
  loadCalib() {
    try { return JSON.parse(sessionStorage.getItem("bf-calib")) || null; }
    catch (_) { return null; }
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
