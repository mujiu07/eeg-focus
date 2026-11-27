/* ============================================================
   专注小蛙 · 档案桥
   ------------------------------------------------------------
   SQLite 是个人数据的权威存储；localStorage 仅作为当前档案的
   页面缓存。选择档案时把服务端快照写入缓存，离开页面时把缓存
   同步回本地后端。这样现有钱包/成就/装扮模块不需要重写。
   ============================================================ */
(function () {
  "use strict";

  const ACTIVE_KEY = "bf-active-user";
  const LIVE_KEY = "bf-live-session";
  const KEYS = [
    "bf-wallet", "bf-achievements", "bf-owned", "bf-owned-at", "bf-outfit",
    "bf-checkin", "bf-heart", "bf-heart-rest", "bf-heart-weight",
    "bf-duration-sec", "bf-calib", "bf-tutorial-done", "bf-dev-tutorial-done",
    "bf-sky", "bf-music-on", "bf-music-index", "bf-music-state", "bf-music-vol",
    "bf-osc-ports",
  ];
  let syncing = null;

  function readJson(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw == null ? fallback : JSON.parse(raw);
    } catch (_) { return fallback; }
  }

  function writeJson(key, value) {
    try {
      if (value == null) localStorage.removeItem(key);
      else localStorage.setItem(key, JSON.stringify(value));
    } catch (_) { /* 隐私模式 */ }
  }

  function active() {
    return readJson(ACTIVE_KEY, null);
  }

  function userId() {
    const p = active();
    return p && typeof p.user_id === "string" ? p.user_id : null;
  }

  function clearProfileCache() {
    KEYS.forEach(key => { try { localStorage.removeItem(key); } catch (_) {} });
    try { sessionStorage.removeItem("bf-dev-calib"); sessionStorage.removeItem("bf-dev-session"); } catch (_) {}
  }

  function applyBootstrap(data) {
    const user = data.user;
    clearProfileCache();
    writeJson(ACTIVE_KEY, {
      user_id: user.user_id, nickname: user.nickname, avatar: user.avatar,
      selected_at: Date.now(),
    });
    const settings = data.settings && typeof data.settings === "object" ? data.settings : {};
    Object.keys(settings).forEach(key => {
      if (KEYS.indexOf(key) >= 0) writeJson(key, settings[key]);
    });
    // 旧浏览器缓存里可能只有 owned 数组/成就数组；服务端表是权威，补齐。
    if (!settings["bf-owned"] && Array.isArray(data.owned)) writeJson("bf-owned", data.owned);
    if (!settings["bf-achievements"] && Array.isArray(data.achievements)) {
      const unlocked = {};
      data.achievements.forEach(row => {
        if (row && row.achievement_id) {
          const t = Date.parse(row.unlocked_at || "");
          unlocked[row.achievement_id] = Number.isFinite(t) ? t : Date.now();
        }
      });
      writeJson("bf-achievements", { v: 2, calibAt: null, playedSec: 0, bestSec: 0, days: [], unlocked, seen: 0 });
    }
    if (data.wallet) writeJson("bf-wallet", data.wallet);
    if (data.calibration && data.calibration.baseline != null) {
      writeJson("bf-calib", {
        baseline: data.calibration.baseline,
        quantiles: data.calibration.quantiles,
        range: data.calibration.range,
        at: data.calibration.at,
        calibration_id: data.calibration.id,
      });
    } else {
      try { localStorage.removeItem("bf-calib"); } catch (_) {}
    }
    window.dispatchEvent(new CustomEvent("bf:profile", { detail: user }));
    return user;
  }

  function collect() {
    const settings = {};
    KEYS.forEach(key => {
      const raw = localStorage.getItem(key);
      if (raw != null) {
        try { settings[key] = JSON.parse(raw); } catch (_) { settings[key] = raw; }
      }
    });
    return {
      settings,
      wallet: readJson("bf-wallet", null),
      owned: readJson("bf-owned", []),
      achievements: readJson("bf-achievements", {}),
    };
  }

  function legacySnapshot() {
    const data = collect();
    const has = data.wallet && Number(data.wallet.points) > 0
      || (Array.isArray(data.owned) && data.owned.length > 0)
      || (data.achievements && Object.keys(data.achievements.unlocked || {}).length > 0)
      || !!localStorage.getItem("bf-calib");
    data.has_data = !!has;
    return data;
  }

  async function syncNow(keepalive) {
    const uid = userId();
    if (!uid) return null;
    const body = collect();
    // 没有实际个人数据时不建立会话同步请求。
    if (!body.wallet && !body.settings["bf-achievements"] && !(body.owned || []).length
        && !body.settings["bf-checkin"] && !body.settings["bf-calib"]) return null;
    if (syncing) return syncing;
    syncing = fetch(`/api/profiles/${encodeURIComponent(uid)}/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-User-Id": uid },
      body: JSON.stringify(body),
      keepalive: !!keepalive,
    }).then(r => r.ok ? r.json() : null).catch(() => null).finally(() => { syncing = null; });
    return syncing;
  }

  function require(next) {
    if (userId()) return true;
    const target = next || (location.pathname.split("/").pop() || "index.html") + location.search;
    location.replace("profiles.html?next=" + encodeURIComponent(target));
    return false;
  }

  function markGame(sessionId) {
    const uid = userId();
    if (!uid || !sessionId) return;
    writeJson(LIVE_KEY, { user_id: uid, session_id: sessionId, at: Date.now() });
  }

  function clearGame() {
    try { localStorage.removeItem(LIVE_KEY); } catch (_) {}
  }

  function liveGame() {
    const live = readJson(LIVE_KEY, null);
    if (!live || !live.user_id || !live.session_id) return null;
    // 24 小时兜底，避免异常退出永久阻止切换档案。
    if (Date.now() - Number(live.at || 0) > 24 * 3600 * 1000) {
      clearGame();
      return null;
    }
    return live;
  }

  function setProfile(user) {
    writeJson(ACTIVE_KEY, {
      user_id: user.user_id, nickname: user.nickname, avatar: user.avatar,
      selected_at: Date.now(),
    });
  }

  window.Profile = {
    active, userId, applyBootstrap, collect, legacySnapshot, syncNow, require,
    clearProfileCache, setProfile, markGame, clearGame, liveGame,
    keys: KEYS.slice(),
  };

  // 离开页面时尽力落盘；失败不阻塞页面切换。
  window.addEventListener("pagehide", () => { syncNow(true); });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") syncNow(true);
  });
})();
