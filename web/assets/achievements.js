/* ============================================================
   专注小蛙 · 成就系统
   成就只保存在本机 localStorage（bf-achievements），不上传、不联网。
   解锁条件：
   - 池塘小卫士：第一次校准成功
   - 专注小达人 I–IV：完整玩完一局 1 / 3 / 5 / 10 分钟
   - 青蛙博士 I–V：累计游玩 30 / 60 / 150 / 300 / 600 分钟
   - 池塘守护神 I–V：连续打卡 3 / 5 / 7 / 15 / 30 天
   ============================================================ */
(function () {
  "use strict";

  const STORE_KEY = "bf-achievements";
  const RESET_KEY = "bf-ach-reset";
  const CHECKIN_MIN_SEC = 60;      // 一局满 1 分钟才算一次打卡
  const DAYS_KEEP = 400;           // 打卡记录最多保留的天数

  const GROUPS = [
    {
      id: "guardian",
      name: "池塘小卫士",
      items: [
        { id: "guardian-first", name: "池塘小卫士", desc: "第一次校准成功", icon: "shield", kind: "calib" },
      ],
    },
    {
      id: "focus",
      name: "专注小达人",
      items: [
        { id: "focus-1", name: "专注小达人 I", desc: "持续游玩 1 分钟", icon: "sprout", kind: "play", target: 60 },
        { id: "focus-2", name: "专注小达人 II", desc: "持续游玩 3 分钟", icon: "leaf", kind: "play", target: 180 },
        { id: "focus-3", name: "专注小达人 III", desc: "持续游玩 5 分钟", icon: "tree", kind: "play", target: 300 },
        { id: "focus-4", name: "专注小达人 IV", desc: "持续游玩 10 分钟", icon: "sparkles", kind: "play", target: 600 },
      ],
    },
    {
      id: "doctor",
      name: "青蛙博士",
      items: [
        { id: "doctor-1", name: "青蛙博士 I", desc: "累计游玩 30 分钟", icon: "bookBlue", kind: "total", target: 1800 },
        { id: "doctor-2", name: "青蛙博士 II", desc: "累计游玩 60 分钟", icon: "bookGreen", kind: "total", target: 3600 },
        { id: "doctor-3", name: "青蛙博士 III", desc: "累计游玩 150 分钟", icon: "bookAmber", kind: "total", target: 9000 },
        { id: "doctor-4", name: "青蛙博士 IV", desc: "累计游玩 300 分钟", icon: "bookRed", kind: "total", target: 18000 },
        { id: "doctor-5", name: "青蛙博士 V", desc: "累计游玩 600 分钟", icon: "cap", kind: "total", target: 36000 },
      ],
    },
    {
      id: "spirit",
      name: "池塘守护神",
      items: [
        { id: "spirit-1", name: "池塘守护神 I", desc: "连续打卡 3 天", icon: "frog", kind: "streak", target: 3 },
        { id: "spirit-2", name: "池塘守护神 II", desc: "连续打卡 5 天", icon: "turtle", kind: "streak", target: 5 },
        { id: "spirit-3", name: "池塘守护神 III", desc: "连续打卡 7 天", icon: "duck", kind: "streak", target: 7 },
        { id: "spirit-4", name: "池塘守护神 IV", desc: "连续打卡 15 天", icon: "swan", kind: "streak", target: 15 },
        { id: "spirit-5", name: "池塘守护神 V", desc: "连续打卡 30 天", icon: "dragon", kind: "streak", target: 30 },
      ],
    },
  ];

  const ALL = GROUPS.reduce((list, group) => list.concat(
    group.items.map(item => Object.assign({ groupName: group.name }, item))
  ), []);

  const pad = n => String(n).padStart(2, "0");

  function trophySvg(suffix) {
    return `
      <svg viewBox="0 0 48 48" aria-hidden="true" focusable="false">
        <defs>
          <linearGradient id="achGold${suffix}" x1="14" y1="6" x2="34" y2="40" gradientUnits="userSpaceOnUse">
            <stop stop-color="#ffeec0"/><stop offset=".52" stop-color="#ffd27f"/><stop offset="1" stop-color="#eda23f"/>
          </linearGradient>
          <linearGradient id="achGoldDark${suffix}" x1="16" y1="24" x2="32" y2="40" gradientUnits="userSpaceOnUse">
            <stop stop-color="#f7c274"/><stop offset="1" stop-color="#d98f33"/>
          </linearGradient>
        </defs>
        <path d="M14 6h20v10.6c0 5.5-4.5 10-10 10s-10-4.5-10-10V6Z" fill="url(#achGold${suffix})"/>
        <path d="M14 9.5H8.8c0 3.4 2.3 5.9 5.6 6.1M34 9.5h5.2c0 3.4-2.3 5.9-5.6 6.1"
              fill="none" stroke="url(#achGoldDark${suffix})" stroke-width="2.4" stroke-linecap="round"/>
        <path d="M22.3 26.4h3.4v5.4h-3.4z" fill="url(#achGoldDark${suffix})"/>
        <path d="M15.8 31.4h16.4l-1.6 4.4H17.4z" fill="url(#achGold${suffix})" stroke="#d99342" stroke-width="1" stroke-linejoin="round"/>
        <rect x="13.2" y="35.8" width="21.6" height="4.8" rx="2" fill="url(#achGoldDark${suffix})"/>
        <path d="M17.6 8.6h12.8" stroke="#fffaf0" stroke-opacity=".7" stroke-width="1.8" stroke-linecap="round"/>
        <path d="M24 9.9l1.14 2.28 2.52.37-1.83 1.78.43 2.51L24 15.66l-2.26 1.18.43-2.51-1.83-1.78 2.52-.37z"
              fill="#fff8e4" opacity=".92"/>
      </svg>`;
  }

  // ---------- 数据 ----------
  const STATE_VERSION = 2;

  function blank() {
    return { v: STATE_VERSION, calibAt: null, playedSec: 0, bestSec: 0, days: [], unlocked: {}, seen: 0 };
  }

  // v1 → v2：「池塘守护神」与「青蛙博士」名称对调，内部记录 id 随名称换位，
  // 旧存档里的已获得徽章同步交换，避免徽章错位。
  function migrateUnlocked(raw) {
    if ((Number(raw.v) || 1) >= STATE_VERSION) return;
    const source = raw.unlocked && typeof raw.unlocked === "object" ? raw.unlocked : {};
    const swapped = {};
    Object.keys(source).forEach(key => {
      if (key.indexOf("doctor-") === 0) swapped["spirit-" + key.slice(7)] = source[key];
      else if (key.indexOf("spirit-") === 0) swapped["doctor-" + key.slice(7)] = source[key];
      else swapped[key] = source[key];
    });
    raw.unlocked = swapped;
    raw.v = STATE_VERSION;
  }

  function read() {
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(STORE_KEY)) || null; } catch (_) { raw = null; }
    const state = blank();
    if (!raw || typeof raw !== "object") return state;
    migrateUnlocked(raw);
    const calibAt = Number(raw.calibAt);
    state.calibAt = Number.isFinite(calibAt) && calibAt > 0 ? calibAt : null;
    state.playedSec = Math.max(0, Number(raw.playedSec) || 0);
    state.bestSec = Math.max(0, Number(raw.bestSec) || 0);
    state.days = Array.isArray(raw.days)
      ? Array.from(new Set(raw.days.filter(d => /^\d{4}-\d{2}-\d{2}$/.test(String(d)))))
      : [];
    state.unlocked = raw.unlocked && typeof raw.unlocked === "object" ? raw.unlocked : {};
    state.seen = Math.max(0, Number(raw.seen) || 0);
    return state;
  }

  function write(state) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (_) { /* 隐私模式忽略 */ }
  }

  function dayKey(date) {
    const d = date || new Date();
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  function nextDayKey(key) {
    const parts = key.split("-").map(Number);
    const d = new Date(parts[0], parts[1] - 1, parts[2] + 1);
    return dayKey(d);
  }

  // 最长连续打卡天数（跨过的连续日期段，不要求包含今天）
  function streakStats(days) {
    const sorted = Array.from(new Set(days)).sort();
    let best = 0, run = 0, prev = null;
    for (const day of sorted) {
      run = prev && nextDayKey(prev) === day ? run + 1 : 1;
      prev = day;
      if (run > best) best = run;
    }
    return { best: best, total: sorted.length, last: prev };
  }

  function fmtClock(sec) {
    const total = Math.max(0, Math.round(sec));
    return Math.floor(total / 60) + ":" + pad(total % 60);
  }

  function fmtSpan(sec) {
    const mins = Math.max(0, Math.floor(sec / 60));
    if (mins < 1) return "0 分钟";
    if (mins < 60) return mins + " 分钟";
    const hours = Math.floor(mins / 60);
    const rest = mins % 60;
    return hours + " 小时" + (rest ? " " + rest + " 分钟" : "");
  }

  // 累计时长统一用分钟表达，和成就描述（30 / 60 / 150 / 300 / 600 分钟）保持一致
  function fmtMins(sec) {
    return Math.max(0, Math.floor(sec / 60)) + " 分钟";
  }

  function fmtDate(ts) {
    const d = new Date(ts);
    return (d.getMonth() + 1) + " 月 " + d.getDate() + " 日";
  }

  // ---------- 进度与解锁判定 ----------
  function progressOf(item, state, streak) {
    if (item.kind === "calib") {
      const done = !!state.calibAt;
      return { value: done ? 1 : 0, target: 1, done: done, text: done ? "已完成校准" : "还未校准" };
    }
    if (item.kind === "play") {
      const value = Math.min(state.bestSec, item.target);
      return {
        value: value,
        target: item.target,
        done: state.bestSec >= item.target,
        text: fmtClock(value) + " / " + fmtClock(item.target),
      };
    }
    if (item.kind === "total") {
      const value = Math.min(state.playedSec, item.target);
      return {
        value: value,
        target: item.target,
        done: state.playedSec >= item.target,
        text: fmtMins(value) + " / " + fmtMins(item.target),
      };
    }
    const value = Math.min(streak.best, item.target);
    return {
      value: value,
      target: item.target,
      done: streak.best >= item.target,
      text: value + " / " + item.target + " 天",
    };
  }

  function evaluate(state) {
    const streak = streakStats(state.days);
    const now = Date.now();
    const fresh = [];
    for (const item of ALL) {
      if (state.unlocked[item.id]) continue;
      if (progressOf(item, state, streak).done) {
        state.unlocked[item.id] = now;
        fresh.push(item);
      }
    }
    return fresh;
  }

  function unlockedCount(state) {
    return ALL.reduce((n, item) => n + (state.unlocked[item.id] ? 1 : 0), 0);
  }

  // ---------- 清空旧缓存 ----------
  // 一次性清除旧版本遗留的成就缓存与待播报队列，清完写入标记，之后正常记录新进度。
  function purgeLegacyCache() {
    try {
      if (localStorage.getItem(RESET_KEY)) return false;
      localStorage.removeItem(STORE_KEY);
      sessionStorage.removeItem("bf-ach-pending");
      localStorage.setItem(RESET_KEY, String(Date.now()));
      return true;
    } catch (_) { return false; }
  }

  // ---------- 记录入口 ----------
  // 校准成功：只记录真正的玩家校准，开发者试玩不计入
  function recordCalib() {
    const state = read();
    if (!state.calibAt) state.calibAt = Date.now();
    evaluate(state);
    write(state);
    refreshChip();
    return [];
  }

  // 一局完整玩完：记录本局时长（用于专注小达人），并补上今天的打卡
  function recordSession(options) {
    const opts = options || {};
    if (opts.demo) return [];
    const played = Math.max(0, Math.round(Number(opts.playedSec) || 0));
    if (played < CHECKIN_MIN_SEC) return [];
    const state = read();
    state.playedSec += played;
    if (played > state.bestSec) state.bestSec = played;
    const today = dayKey();
    if (state.days.indexOf(today) < 0) state.days.push(today);
    if (state.days.length > DAYS_KEEP) state.days = state.days.sort().slice(-DAYS_KEEP);
    const fresh = evaluate(state);
    write(state);
    refreshChip();
    return fresh;
  }

  // 兼容旧数据：升级前已经校准成功的玩家，也算拿到「池塘小卫士」
  function migrateCalib() {
    const state = read();
    if (state.calibAt) return;
    let calib = null;
    try {
      if (typeof Store !== "undefined") {
        const info = Store.playerCalibInfo();
        calib = info && info.calib ? info.calib : null;
      }
    } catch (_) { calib = null; }
    if (!calib) return;
    state.calibAt = Number(calib.at) || Date.now();
    evaluate(state);
    write(state);
    refreshChip();
  }

  // ---------- 界面 ----------
  let chip = null;
  let chipCount = null;
  let chipNew = null;
  let mask = null;
  let panel = null;
  let panelSub = null;
  let panelBody = null;
  let lastFocus = null;

  function buildChip(entry) {
    entry.innerHTML = `
      <button type="button" class="ach-chip" id="ach-open" aria-haspopup="dialog" aria-label="成就徽章">
        <span class="ach-chip__badge">${trophySvg("Chip")}</span>
        <span class="ach-chip__meta">
          <span class="ach-chip__title">成就</span>
          <span class="ach-chip__count" id="ach-chip-count">0 / ${ALL.length}</span>
        </span>
        <span class="ach-chip__new hidden" id="ach-chip-new" aria-hidden="true"></span>
      </button>`;
    chip = entry.querySelector("#ach-open");
    chipCount = entry.querySelector("#ach-chip-count");
    chipNew = entry.querySelector("#ach-chip-new");
    chip.addEventListener("click", openPanel);
  }

  function buildPanel() {
    mask = document.createElement("div");
    mask.className = "ach-mask hidden";
    mask.id = "ach-mask";
    mask.innerHTML = `
      <div class="ach-card" role="dialog" aria-modal="true" aria-labelledby="ach-title">
        <button type="button" class="ach-close" id="ach-close" aria-label="关闭成就面板">
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5.5 5.5l9 9M14.5 5.5l-9 9" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>
        </button>
        <div class="ach-head">
          <div class="ach-head__icon">${trophySvg("Head")}</div>
          <div class="ach-head__text">
            <h2 id="ach-title">成就徽章</h2>
            <p id="ach-sub">已收集 0 / ${ALL.length} 枚徽章</p>
          </div>
        </div>
        <div class="ach-body" id="ach-body"></div>
        <p class="ach-foot">每天完整玩完一局专注训练，就算一次打卡；累计时长和单局时长都按完整玩完的那一局计算。</p>
      </div>`;
    document.body.appendChild(mask);
    panel = mask.querySelector(".ach-card");
    panelSub = mask.querySelector("#ach-sub");
    panelBody = mask.querySelector("#ach-body");
    mask.querySelector("#ach-close").addEventListener("click", closePanel);
    mask.addEventListener("click", event => { if (event.target === mask) closePanel(); });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && mask && !mask.classList.contains("hidden")) closePanel();
    });
  }

  function achievementIcon(item) {
    if (item.icon === "frog" && window.FrogArt) return window.FrogArt.svg({ className: "ach-frog" });
    return window.Icons ? window.Icons.markup(item.icon, "ach-glyph") : "";
  }

  function itemHtml(item, state, streak) {
    const progress = progressOf(item, state, streak);
    const got = !!state.unlocked[item.id];
    const pct = Math.max(0, Math.min(100, Math.round(progress.value / progress.target * 100)));
    const tag = got
      ? '<span class="ach-item__tag">已获得</span>'
      : '<span class="ach-item__tag ach-item__tag--locked">未解锁</span>';
    const detail = got
      ? `<div class="ach-item__got">解锁于 ${fmtDate(state.unlocked[item.id])}</div>`
      : `<div class="ach-item__progress">
           <span class="ach-item__track"><i style="width:${pct}%"></i></span>
           <span class="ach-item__meta">${progress.text}</span>
         </div>`;
    return `
      <div class="ach-item${got ? " is-unlocked" : ""}">
        <div class="ach-item__icon" aria-hidden="true">${achievementIcon(item)}</div>
        <div class="ach-item__main">
          <div class="ach-item__title">${item.name}${tag}</div>
          <div class="ach-item__desc">${item.desc}</div>
          ${detail}
        </div>
      </div>`;
  }

  function renderPanel() {
    const state = read();
    const streak = streakStats(state.days);
    const got = unlockedCount(state);
    panelSub.textContent = "已收集 " + got + " / " + ALL.length + " 枚徽章 · 累计专注 " + fmtSpan(state.playedSec);
    panelBody.innerHTML = GROUPS.map(group => {
      const groupGot = group.items.reduce((n, item) => n + (state.unlocked[item.id] ? 1 : 0), 0);
      const pct = Math.round(groupGot / group.items.length * 100);
      return `
        <section class="ach-group">
          <div class="ach-group__head">
            <span class="ach-group__name">${group.name}</span>
            <span class="ach-group__bar"><i style="width:${pct}%"></i></span>
            <span class="ach-group__count">${groupGot}/${group.items.length}</span>
          </div>
          ${group.items.map(item => itemHtml(item, state, streak)).join("")}
        </section>`;
    }).join("");
    if (state.seen !== got) {
      state.seen = got;
      write(state);
    }
    refreshChip();
  }

  function openPanel() {
    if (!mask) buildPanel();
    if (!mask.classList.contains("hidden")) return;
    lastFocus = document.activeElement;
    renderPanel();
    mask.classList.remove("hidden");
    const closeBtn = mask.querySelector("#ach-close");
    if (closeBtn) closeBtn.focus({ preventScroll: true });
    document.addEventListener("keydown", trapFocus);
  }

  function closePanel() {
    if (!mask) return;
    mask.classList.add("hidden");
    document.removeEventListener("keydown", trapFocus);
    if (lastFocus && typeof lastFocus.focus === "function") {
      lastFocus.focus({ preventScroll: true });
    }
  }

  function trapFocus(event) {
    if (event.key !== "Tab" || !panel) return;
    const focusables = panel.querySelectorAll("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])");
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function refreshChip() {
    if (!chip) return;
    const state = read();
    const got = unlockedCount(state);
    chipCount.textContent = got + " / " + ALL.length;
    chip.setAttribute("aria-label", "成就徽章，已获得 " + got + " / " + ALL.length);
    chipNew.classList.toggle("hidden", got <= (state.seen || 0));
  }

  function init() {
    const purged = purgeLegacyCache();
    // 解锁播报已移除，旧的待播报队列不再使用，每次加载都顺手清掉
    try { sessionStorage.removeItem("bf-ach-pending"); } catch (_) { /* 忽略 */ }
    const entry = document.getElementById("achievement-entry");
    if (entry) buildChip(entry);
    // 缓存刚被重置时不再从旧校准数据回填成就，避免清空后又被恢复
    if (!purged) migrateCalib();
    refreshChip();
  }

  window.Achievements = {
    recordCalib: recordCalib,
    recordSession: recordSession,
    list: function () { return ALL.slice(); },
    status: function () {
      const state = read();
      return {
        unlocked: Object.keys(state.unlocked),
        // 每枚徽章的解锁时间戳，装扮图鉴用来展示获得时间
        unlockedAt: Object.assign({}, state.unlocked),
        playedSec: state.playedSec,
        bestSec: state.bestSec,
        bestStreak: streakStats(state.days).best,
        days: state.days.slice(),
      };
    },
    open: function () {
      if (!document.getElementById("achievement-entry")) return;
      if (!chip) {
        const entry = document.getElementById("achievement-entry");
        if (entry) buildChip(entry);
      }
      openPanel();
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
