/* ============================================================
   专注小蛙 · 每日签到
   ------------------------------------------------------------
   · 位置：首页右侧入口最左边（成就的左侧）
   · 规则：每天只能签到一次，每次 +2 积分；0 点刷新（按本机时间）
   · 积分记到 Wallet（bf-wallet），签到日期记到 bf-checkin
   · 只保存在本机 localStorage，不上传、不联网
   ============================================================ */
(function () {
  "use strict";

  const STORE_KEY = "bf-checkin";
  const VERSION = 1;
  const DAILY_POINTS = 2;
  const TOAST_MS = 4200;

  let chip = null;
  let chipBadge = null;
  let chipCount = null;
  let chipDot = null;
  let toast = null;
  let toastIcon = null;
  let toastTitle = null;
  let toastSub = null;
  let toastTimer = 0;
  let midnightTimer = 0;
  let lastRenderedDay = "";

  // ---------- 日期 ----------
  function dayKey(date) {
    const d = date || new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  function yesterdayKey() {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return dayKey(d);
  }

  // ---------- 存档 ----------
  function blank() {
    return { v: VERSION, lastDate: "", streak: 0, total: 0, days: 0 };
  }

  function read() {
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(STORE_KEY)); } catch (_) { raw = null; }
    const out = blank();
    if (!raw || typeof raw !== "object") return out;
    if (typeof raw.lastDate === "string" && /^\d{4}-\d{2}-\d{2}$/.test(raw.lastDate)) {
      out.lastDate = raw.lastDate;
    }
    ["streak", "total", "days"].forEach(key => {
      const n = Number(raw[key]);
      if (Number.isFinite(n) && n > 0) out[key] = Math.floor(n);
    });
    return out;
  }

  function save(state) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (_) { /* 隐私模式忽略 */ }
  }

  function isSignedToday() {
    return read().lastDate === dayKey();
  }

  function walletPoints() {
    return window.Wallet ? window.Wallet.points() : 0;
  }

  // ---------- 入口 chip ----------
  function giftSvg() {
    return `<svg viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <rect x="10.4" y="21" width="27.2" height="17.4" rx="3.2"
            fill="#ffdc9f" stroke="#c98b2e" stroke-width="2.2"/>
      <rect x="8.6" y="15.2" width="30.8" height="7.6" rx="2.6"
            fill="#ffe8bb" stroke="#c98b2e" stroke-width="2.2"/>
      <path d="M24 15.2V38" stroke="#c98b2e" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M24 15.2c-1.9-5.6-9.8-6.4-9.8-1.5 0 2.2 3.4 1.5 9.8 1.5Z"
            fill="#ffefd2" stroke="#c98b2e" stroke-width="2.1" stroke-linejoin="round"/>
      <path d="M24 15.2c1.9-5.6 9.8-6.4 9.8-1.5 0 2.2-3.4 1.5-9.8 1.5Z"
            fill="#ffefd2" stroke="#c98b2e" stroke-width="2.1" stroke-linejoin="round"/>
      <circle cx="24" cy="30.2" r="3.4" fill="#f8bd63" stroke="#c98b2e" stroke-width="1.8"/>
    </svg>`;
  }

  function checkSvg() {
    return `<svg viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <circle cx="24" cy="24" r="14.4" fill="none" stroke="#3aa7a0" stroke-width="2.6" opacity=".32"/>
      <path d="M16.6 24.7 22.2 30.2 31.6 18.6" fill="none"
            stroke="#2f948c" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;
  }

  function buildChip(entry) {
    entry.innerHTML = `
      <button type="button" class="checkin-chip" id="checkin-open" aria-label="每日签到">
        <span class="checkin-chip__badge" id="checkin-chip-badge">${giftSvg()}</span>
        <span class="checkin-chip__meta">
          <span class="checkin-chip__title">签到</span>
          <span class="checkin-chip__count" id="checkin-chip-count">今日 +${DAILY_POINTS} 积分</span>
        </span>
        <span class="checkin-chip__dot" id="checkin-chip-dot" aria-hidden="true">可领 ${DAILY_POINTS} 分</span>
      </button>`;
    chip = entry.querySelector("#checkin-open");
    chipBadge = entry.querySelector("#checkin-chip-badge");
    chipCount = entry.querySelector("#checkin-chip-count");
    chipDot = entry.querySelector("#checkin-chip-dot");
    chip.addEventListener("click", onChipClick);
    lastRenderedDay = dayKey();
    paintChip(false);
  }

  // 按当前是否已签到重画 chip
  function paintChip(animate) {
    if (!chip) return;
    const signed = isSignedToday();
    chip.classList.toggle("is-ready", !signed);
    chip.classList.toggle("is-done", signed);
    if (chipBadge) chipBadge.innerHTML = signed ? checkSvg() : giftSvg();
    if (chipCount) {
      chipCount.textContent = signed
        ? "今日已签"
        : "今日 +" + DAILY_POINTS + " 积分";
    }
    if (chipDot) chipDot.hidden = signed;
    chip.setAttribute(
      "aria-label",
      signed
        ? "每日签到，今天已签到，明天 0 点后可再领 " + DAILY_POINTS + " 积分"
        : "每日签到，点击领取 " + DAILY_POINTS + " 积分"
    );
    if (animate) {
      chip.classList.remove("is-pop");
      // 强制重排，让动画能重复触发
      void chip.offsetWidth;
      chip.classList.add("is-pop");
    }
    lastRenderedDay = dayKey();
  }

  // ---------- 提示条 ----------
  function buildToast() {
    toast = document.createElement("div");
    toast.className = "checkin-toast";
    toast.id = "checkin-toast";
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");
    toast.innerHTML = `
      <span class="checkin-toast__icon" id="checkin-toast-icon" data-icon="gift"></span>
      <span class="checkin-toast__main">
        <strong id="checkin-toast-title"></strong>
        <span id="checkin-toast-sub"></span>
      </span>`;
    document.body.appendChild(toast);
    toastIcon = toast.querySelector("#checkin-toast-icon");
    toastTitle = toast.querySelector("#checkin-toast-title");
    toastSub = toast.querySelector("#checkin-toast-sub");
  }

  function showToast(opts) {
    if (!toast) buildToast();
    toast.classList.toggle("is-muted", !opts.gold);
    toastIcon.innerHTML = window.Icons ? window.Icons.svg(opts.icon || (opts.gold ? "gift" : "moon")) : "";
    toastTitle.innerHTML = opts.title;
    toastSub.textContent = opts.sub || "";
    toast.classList.add("is-show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(hideToast, opts.duration || TOAST_MS);
  }

  function hideToast() {
    clearTimeout(toastTimer);
    if (toast) toast.classList.remove("is-show");
  }

  // 从 chip 位置飞出一个「+2 积分」
  function floatGain() {
    if (!chip) return;
    const rect = chip.getBoundingClientRect();
    // 窄屏 chip 占满整行、上方就是品牌标题，飘字会盖住标题，只撒金币
    if (window.innerWidth > 560) {
      const el = document.createElement("span");
      el.className = "checkin-float";
      el.textContent = "+" + DAILY_POINTS + " 积分";
      el.style.left = (rect.left + rect.width / 2) + "px";
      el.style.top = (rect.top + rect.height / 2 - 12) + "px";
      document.body.appendChild(el);
      setTimeout(() => el.remove(), 1300);
    }

    // 撒几枚小金币
    for (let i = 0; i < 8; i += 1) {
      const coin = document.createElement("i");
      coin.className = "checkin-coin";
      const angle = (-Math.PI / 2) + (i - 3.5) * 0.42;
      const dist = 52 + Math.random() * 34;
      coin.style.left = (rect.left + rect.width / 2 - 7) + "px";
      coin.style.top = (rect.top + rect.height / 2 - 7) + "px";
      coin.style.setProperty("--dx", Math.cos(angle) * dist + "px");
      coin.style.setProperty("--dy", Math.sin(angle) * dist + "px");
      coin.style.animationDelay = (i * 26) + "ms";
      document.body.appendChild(coin);
      setTimeout(() => coin.remove(), 1300);
    }
  }

  // ---------- 签到 ----------
  function onChipClick() {
    if (isSignedToday()) {
      showToast({
        gold: false,
        icon: "moon",
        title: "今天已经签到过啦",
        sub: "明天 0 点刷新后可以再领 " + DAILY_POINTS + " 积分（当前 " + walletPoints() + " 积分）",
      });
      paintChip(true);
      return;
    }

    const state = read();
    const today = dayKey();
    const streak = state.lastDate === yesterdayKey() ? state.streak + 1 : 1;

    const gain = window.Wallet
      ? window.Wallet.add(DAILY_POINTS)
      : DAILY_POINTS;

    save({
      v: VERSION,
      lastDate: today,
      streak: streak,
      total: state.total + (gain || DAILY_POINTS),
      days: state.days + 1,
    });

    paintChip(false);
    floatGain();
    showToast({
      gold: true,
      icon: "gift",
      title: "签到成功，积分 <b>+" + (gain || DAILY_POINTS) + "</b>",
      sub: "已连续签到 " + streak + " 天 · 共 " + walletPoints() +
           " 积分 · 明天 0 点后再领",
      duration: 4800,
    });

    try {
      window.dispatchEvent(new CustomEvent("bf:checkin", {
        detail: { date: today, gain: gain || DAILY_POINTS, streak: streak, points: walletPoints() },
      }));
    } catch (_) { /* 老浏览器忽略 */ }

    scheduleMidnight();
  }

  // ---------- 0 点刷新 ----------
  function scheduleMidnight() {
    clearTimeout(midnightTimer);
    const now = new Date();
    const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 2, 0);
    let wait = next.getTime() - now.getTime();
    if (!Number.isFinite(wait) || wait < 1000) wait = 1000;
    // setTimeout 上限约 24.8 天，这里最多等一天，安全
    midnightTimer = setTimeout(function () {
      if (dayKey() !== lastRenderedDay) {
        paintChip(false);
        if (!isSignedToday()) {
          showToast({
            gold: true,
            icon: "sun",
            title: "新的一天，签到领 " + DAILY_POINTS + " 积分",
            sub: "0 点已刷新，点一下「签到」就能拿到手",
            duration: 5200,
          });
        }
      }
      scheduleMidnight();
    }, Math.min(wait, 86400000));
  }

  // 切回标签页 / 系统唤醒后补一次跨天检查
  function checkRollover() {
    if (dayKey() !== lastRenderedDay) paintChip(false);
    scheduleMidnight();
  }

  function init() {
    const entry = document.getElementById("checkin-entry");
    if (!entry) return;
    buildChip(entry);
    scheduleMidnight();
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) checkRollover();
    });
    window.addEventListener("focus", checkRollover);
    window.addEventListener("pageshow", checkRollover);
  }

  window.CheckIn = {
    key: STORE_KEY,
    todayKey: function () { return dayKey(); },
    isSignedToday: isSignedToday,
    streak: function () { return read().streak; },
    refresh: function () { paintChip(false); },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
