/* ============================================================
 * 专注小蛙 · 全站天空模式
 * 黎明 / 白天 / 傍晚 / 黑夜 / 跟随系统时间（按日出日落自动切换）
 * 所有页面共用同一份模式设置与配色变量；首页额外驱动池塘场景
 * ============================================================ */
(function () {
  "use strict";

  var STORE_KEY = "bf-sky-mode";
  var MODES = ["dawn", "day", "dusk", "night", "auto"];
  var DEFAULT_MODE = "auto";
  var MODE_NAMES = { dawn: "黎明", day: "白天", dusk: "傍晚", night: "黑夜", auto: "跟随系统时间" };
  var SKY_NAMES = { dawn: "黎明", day: "白天", dusk: "傍晚", night: "黑夜" };
  var SKY_ICONS = {
    dawn: "\uD83C\uDF04",
    day: "\uD83C\uDF05",
    dusk: "\uD83C\uDF07",
    night: "\uD83C\uDF19",
  };

  // 四档天空的完整配色：首页 SVG 场景与游戏画布共用同一份色板，
  // 保证「游戏界面」和「初始界面」的黎明 / 白天 / 傍晚 / 黑夜完全同步。
  // sky / water 为渐变，hills / trees 为实色，glow / mist 为晨昏地平线光。
  var PALETTES = {
    day: {
      sky: ["#dff4fb", "#c9edf4", "#b3e3e8"],
      water: ["#9fd8e2", "#6fb8c9"],
      hills: ["rgba(201, 233, 223, .86)", "rgba(179, 221, 214, .92)"],
      trees: "rgba(88, 178, 128, .8)",
      waves: 1,
      cloud: { fill: "rgba(255, 255, 255, .92)", alpha: .88 },
      mist: { color: "255, 233, 216", alpha: 0 },
      glow: null,
      sun: { x: 828, y: 62, core: "#ffdf8e", mid: "#ffe9b8", halo: "#ffe9b8" },
      moon: null,
      stars: false,
      flora: "none",
      frog: "none",
      energy: ["#8fe3a0", "#2f9c93"],
      hud: { pill: "rgba(255, 255, 255, .92)", ink: "#23464f", inkSoft: "rgba(35, 70, 79, .75)" },
    },
    dawn: {
      sky: ["#9fb0e6", "#e7b6d4", "#ffd7a4"],
      water: ["#f5c0ad", "#6f9fbd"],
      hills: ["rgba(169, 178, 201, .84)", "rgba(143, 154, 180, .9)"],
      trees: "rgba(96, 142, 133, .8)",
      waves: .86,
      cloud: { fill: "rgba(255, 223, 213, .9)", alpha: .7 },
      mist: { color: "255, 217, 198", alpha: .42 },
      glow: { x: 327, y: 300, rx: 120, ry: 18, color: "255, 210, 168" },
      sun: { x: 327, y: 136, core: "#fff3cf", mid: "#ffe1b0", halo: "#ffd2ac" },
      moon: null,
      stars: false,
      flora: "brightness(.9) saturate(.95) sepia(.08)",
      frog: "brightness(.92) sepia(.06)",
      energy: ["#e0a8c0", "#8f4d6b"],
      hud: { pill: "rgba(255, 250, 252, .9)", ink: "#4a3c4c", inkSoft: "rgba(74, 60, 76, .74)" },
    },
    dusk: {
      sky: ["#4f5590", "#d97e83", "#ffb968"],
      water: ["#e39482", "#4a6684"],
      hills: ["rgba(134, 119, 154, .88)", "rgba(108, 95, 128, .92)"],
      trees: "rgba(92, 104, 122, .82)",
      waves: .7,
      cloud: { fill: "rgba(255, 201, 186, .9)", alpha: .75 },
      mist: { color: "255, 208, 180", alpha: .36 },
      glow: { x: 744, y: 302, rx: 136, ry: 19, color: "255, 184, 122" },
      sun: { x: 744, y: 152, core: "#ffd08a", mid: "#ffb066", halo: "#ff9f6a" },
      moon: null,
      stars: false,
      flora: "brightness(.8) saturate(.9) sepia(.14)",
      frog: "brightness(.85) sepia(.12)",
      energy: ["#ffb496", "#ff8d68"],
      hud: { pill: "rgba(255, 255, 255, .14)", ink: "#f7eae8", inkSoft: "rgba(247, 234, 232, .8)" },
    },
    night: {
      sky: ["#0a1730", "#142a4d", "#244a70"],
      water: ["#16405a", "#0d2a3e"],
      hills: ["rgba(26, 56, 84, .95)", "rgba(19, 45, 70, .97)"],
      trees: "rgba(38, 74, 96, .82)",
      waves: .52,
      cloud: null,
      mist: { color: "188, 214, 255", alpha: 0 },
      glow: null,
      sun: null,
      moon: { x: 808, y: 66, core: "#f4f8ff", halo: "#cfe0ff" },
      stars: true,
      flora: "brightness(.62) saturate(.85)",
      frog: "brightness(.8)",
      energy: ["#8fdbea", "#58b6d4"],
      hud: { pill: "rgba(255, 255, 255, .13)", ink: "#e6f0f8", inkSoft: "rgba(230, 240, 248, .8)" },
    },
  };

  // 供 canvas 页面读取（game.html）：与 CSS 的 data-sky 保持同一份状态
  window.SkyTheme = {
    sky: function () {
      var sky = root.getAttribute("data-sky");
      return PALETTES[sky] ? sky : "day";
    },
    palette: function (name) {
      return PALETTES[name] || PALETTES.day;
    },
    palettes: PALETTES,
    names: SKY_NAMES
  };

  // 黎明 / 傍晚的过渡窗口（以日出、日落为基准，单位：分钟）
  var DAWN_LEAD = 40;   // 日出前 40 分钟进入黎明
  var DAWN_TAIL = 32;   // 日出后 32 分钟结束黎明
  var DUSK_LEAD = 38;   // 日落前 38 分钟进入傍晚
  var DUSK_TAIL = 42;   // 日落后 42 分钟结束傍晚

  // 日出日落估算用纬度（北半球中纬度）；经度按系统时区自动估算
  var EST_LAT = 32;

  var root = document.documentElement;

  function readMode() {
    try {
      var saved = localStorage.getItem(STORE_KEY);
      if (MODES.indexOf(saved) !== -1) return saved;
    } catch (e) { /* 隐私模式下 localStorage 不可用 */ }
    return DEFAULT_MODE;
  }

  function saveMode(mode) {
    try { localStorage.setItem(STORE_KEY, mode); } catch (e) { /* ignore */ }
  }

  function tzOffsetMinutes() {
    return -new Date().getTimezoneOffset(); // 东八区 = 480
  }

  function estimateLongitude() {
    var lon = tzOffsetMinutes() / 4; // 每 4 分钟对应 1 经度
    return Math.max(-180, Math.min(180, lon));
  }

  function dayOfYear(date) {
    var start = new Date(date.getFullYear(), 0, 0);
    return Math.floor((date - start) / 86400000);
  }

  // NOAA 简化算法：返回本地时间的日出 / 日落（分钟数）
  function sunTimes(date) {
    var rad = Math.PI / 180;
    var gamma = (2 * Math.PI / 365) * (dayOfYear(date) - 1);

    var eqtime = 229.18 * (0.000075
      + 0.001868 * Math.cos(gamma) - 0.032077 * Math.sin(gamma)
      - 0.014615 * Math.cos(2 * gamma) - 0.040849 * Math.sin(2 * gamma));

    var decl = 0.006918
      - 0.399912 * Math.cos(gamma) + 0.070257 * Math.sin(gamma)
      - 0.006758 * Math.cos(2 * gamma) + 0.000907 * Math.sin(2 * gamma)
      - 0.002697 * Math.cos(3 * gamma) + 0.00148 * Math.sin(3 * gamma);

    var lat = EST_LAT * rad;
    var lon = estimateLongitude();
    var cosH = Math.cos(90.833 * rad) / (Math.cos(lat) * Math.cos(decl))
      - Math.tan(lat) * Math.tan(decl);

    // 极昼 / 极夜：退化为固定时段，避免 NaN
    if (cosH >= 1) return { sunrise: 720, sunset: 720, polar: "night" };   // 太阳全天不升起
    if (cosH <= -1) return { sunrise: 0, sunset: 1440, polar: "day" };     // 太阳全天不落下

    var H = Math.acos(cosH) / rad;
    var tz = tzOffsetMinutes();
    var sunrise = 720 - 4 * (lon + H) - eqtime + tz;
    var sunset = 720 - 4 * (lon - H) - eqtime + tz;
    var norm = function (m) { return ((m % 1440) + 1440) % 1440; };

    return { sunrise: norm(sunrise), sunset: norm(sunset) };
  }

  function resolveSky(mode, date) {
    if (mode !== "auto") return mode;

    var t = sunTimes(date);
    if (t.polar === "day") return "day";
    if (t.polar === "night") return "night";

    var now = date.getHours() * 60 + date.getMinutes() + date.getSeconds() / 60;
    var dawnStart = t.sunrise - DAWN_LEAD;
    var dayStart = t.sunrise + DAWN_TAIL;
    var duskStart = t.sunset - DUSK_LEAD;
    var duskEnd = t.sunset + DUSK_TAIL;

    if (now >= dawnStart && now < dayStart) return "dawn";
    if (now >= dayStart && now < duskStart) return "day";
    if (now >= duskStart && now < duskEnd) return "dusk";
    return "night";
  }

  function fmtTime(minutes) {
    var m = Math.round(minutes) % 1440;
    if (m < 0) m += 1440;
    var h = Math.floor(m / 60);
    var mm = m % 60;
    return (h < 10 ? "0" : "") + h + ":" + (mm < 10 ? "0" : "") + mm;
  }

  function syncUI(mode, sky, times) {
    var box = document.getElementById("sky-switch");
    if (box) {
      var opts = box.querySelectorAll(".sky-opt");
      for (var i = 0; i < opts.length; i++) {
        opts[i].setAttribute("aria-pressed", opts[i].getAttribute("data-mode") === mode ? "true" : "false");
      }
      var autoBtn = box.querySelector('[data-mode="auto"]');
      if (autoBtn) {
        var label = "日出 " + fmtTime(times.sunrise) + " · 日落 " + fmtTime(times.sunset);
        autoBtn.title = "跟随系统时间（今日" + label + "，含黎明与傍晚）";
        autoBtn.setAttribute("aria-label", "跟随系统时间，今日" + label);
      }
    }

    var icon = document.getElementById("hero-sky-icon");
    if (icon) icon.textContent = SKY_ICONS[sky] || SKY_ICONS.day;
  }

  function apply() {
    var mode = readMode();
    var now = new Date();
    var sky = resolveSky(mode, now);
    var times = sunTimes(now);

    root.setAttribute("data-sky", sky);
    root.setAttribute("data-sky-mode", mode);
    syncUI(mode, sky, times);

    // 通知各页面重绘随主题变化的 canvas 图表等
    try {
      document.dispatchEvent(new CustomEvent("skychange", {
        detail: { mode: mode, sky: sky }
      }));
    } catch (e) { /* 极旧浏览器忽略 */ }

    return sky;
  }

  // 生成一层星星（固定随机种子，保证每次打开星图一致）
  function buildStars() {
    var group = document.getElementById("heroStars");
    if (!group || group.childNodes.length) return;

    var seed = 20261112;
    var rnd = function () {
      seed = (seed * 1664525 + 1013904223) % 4294967296;
      return seed / 4294967296;
    };

    var frag = document.createDocumentFragment();
    for (var i = 0; i < 64; i++) {
      var cx = 16 + rnd() * 848;
      var cy = 8 + rnd() * 116;
      // 避开月亮周围，留出干净的月光
      if (Math.pow(cx - 790, 2) + Math.pow(cy - 46, 2) < 52 * 52) continue;

      var star = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      star.setAttribute("cx", cx.toFixed(1));
      star.setAttribute("cy", cy.toFixed(1));
      star.setAttribute("r", (0.6 + rnd() * 1.5).toFixed(2));
      star.setAttribute("fill", "#ffffff");
      star.style.setProperty("--tw-dur", (2.6 + rnd() * 2.8).toFixed(2) + "s");
      star.style.setProperty("--tw-delay", (rnd() * 5).toFixed(2) + "s");
      star.style.opacity = (0.4 + rnd() * 0.55).toFixed(2);
      frag.appendChild(star);
    }
    group.appendChild(frag);
  }

  var timer = null;
  function startTimer() {
    if (timer) return;
    // 每分钟刷新一次：跨过日出 / 日落时自动切换，并更新今日时间提示
    timer = setInterval(apply, 60000);
  }

  function boot() {
    buildStars();

    var box = document.getElementById("sky-switch");
    if (box && !box.dataset.wired) {
      box.dataset.wired = "1";
      box.addEventListener("click", function (e) {
        var btn = e.target && e.target.closest ? e.target.closest(".sky-opt") : null;
        if (!btn || MODES.indexOf(btn.dataset.mode) === -1) return;

        saveMode(btn.dataset.mode);
        var sky = apply();
        if (typeof toast === "function") {
          var extra = btn.dataset.mode === "auto"
            ? "，当前是" + (SKY_NAMES[sky] || "白天")
            : "";
          toast("已切换到「" + MODE_NAMES[btn.dataset.mode] + "」" + extra);
        }
      });
    }

    apply();
    startTimer();
  }

  // 首屏渲染前先定好天空，避免白天 / 黑夜闪一下
  apply();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
