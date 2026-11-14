/* ============================================================
 * 专注小蛙 · 全站天空模式
 * 黎明 / 白天 / 傍晚 / 黑夜 / 跟随系统时间（按日出日落自动切换）
 * 所有页面共用同一份模式设置与配色变量；首页额外驱动池塘场景
 * 切换（手动点击 / 跟随时间跨档）时按 --sky-fade 的时长做颜色渐变
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

  /* ------------------------------------------------------------
   * 颜色渐变引擎
   * 切换天空时不直接跳色，而是在 --sky-fade 的时长里把旧配色逐帧插值成新配色：
   *   1) CSS 变量逐帧写回 html 内联样式 → 背景渐变 / 卡片 / 文字同步变化；
   *   2) PALETTES 同步混合 → 首页 SVG 与游戏 canvas 一起跟着渐变；
   *   3) 渐变开始与结束各派发一次 skychange（带 progress），
   *      需要随主题重绘的图表据此刷新，其余页面靠 CSS 变量自行渐变。
   * ------------------------------------------------------------ */
  var root = document.documentElement;
  var MIXED = null;               // 渐变中的混合色板（canvas 每帧读取）
  var fadeToken = 0;              // 递增令牌，用于打断上一轮未完成的渐变
  var FADE_FALLBACK_MS = 1200;    // 读不到 --sky-fade 时的兜底时长

  // 跟随天空平滑变化的 CSS 变量（与 sky.css 中各档定义保持一致）
  var FADE_VARS = [
    "--ink", "--ink-soft", "--sky-top", "--sky-mid", "--sky-low",
    "--water-top", "--accent", "--accent-dark", "--card", "--card-border"
  ];

  var reduceMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
  function lerp(a, b, t) { return a + (b - a) * t; }

  // 支持 #rgb / #rrggbb / #rrggbbaa / rgb() / rgba()
  function parseColor(value) {
    if (!value) return null;
    var s = String(value).trim();
    if (s.charAt(0) === "#") {
      var hex = s.slice(1);
      if (hex.length === 3 || hex.length === 4) hex = hex.replace(/[0-9a-f]/gi, "$&$&");
      if (hex.length !== 6 && hex.length !== 8) return null;
      return {
        r: parseInt(hex.slice(0, 2), 16),
        g: parseInt(hex.slice(2, 4), 16),
        b: parseInt(hex.slice(4, 6), 16),
        a: hex.length === 8 ? parseInt(hex.slice(6, 8), 16) / 255 : 1
      };
    }
    var m = s.match(/^rgba?\(([^)]+)\)$/i);
    if (!m) return null;
    var parts = m[1].split(/[\s,/]+/);
    if (parts.length < 3) return null;
    var a = parts[3] === undefined || parts[3] === ""
      ? 1
      : (parts[3].indexOf("%") > -1 ? parseFloat(parts[3]) / 100 : parseFloat(parts[3]));
    var c = { r: parseFloat(parts[0]), g: parseFloat(parts[1]), b: parseFloat(parts[2]), a: isNaN(a) ? 1 : a };
    if (isNaN(c.r) || isNaN(c.g) || isNaN(c.b)) return null;
    return c;
  }

  function mixParsed(A, B, t) {
    var r = Math.round(A.r + (B.r - A.r) * t);
    var g = Math.round(A.g + (B.g - A.g) * t);
    var b = Math.round(A.b + (B.b - A.b) * t);
    var a = Math.round(clamp01(A.a + (B.a - A.a) * t) * 1000) / 1000;
    return "rgba(" + r + ", " + g + ", " + b + ", " + a + ")";
  }

  function mixColor(a, b, t) {
    if (t <= 0) return a;
    if (t >= 1) return b;
    var A = parseColor(a), B = parseColor(b);
    if (!A || !B) return t < 0.5 ? a : b;
    return mixParsed(A, B, t);
  }

  // "255, 233, 216" 这种三通道字符串（mist.color / glow.color 用）
  function mixTriplet(a, b, t) {
    var A = String(a || "").split(",");
    var B = String(b || "").split(",");
    if (A.length !== 3 || B.length !== 3) return t < 0.5 ? a : b;
    var out = [];
    for (var i = 0; i < 3; i++) {
      out.push(Math.round(lerp(parseFloat(A[i]) || 0, parseFloat(B[i]) || 0, t)));
    }
    return out.join(", ");
  }

  function mixList(a, b, t) {
    if (!a || !b) return t < 0.5 ? a : b;
    var out = [];
    var n = Math.max(a.length, b.length);
    for (var i = 0; i < n; i++) out.push(mixColor(a[i], b[i], t));
    return out;
  }

  // 太阳 / 月亮 / 地平线光晕这类小对象：数值插值、颜色插值，缺失的一侧取中点切换
  function mixObject(a, b, t) {
    if (!a && !b) return null;
    if (!a || !b) return t < 0.5 ? a : b;
    var out = {};
    var k, va, vb;
    for (k in a) {
      if (!Object.prototype.hasOwnProperty.call(a, k)) continue;
      va = a[k];
      vb = b[k];
      if (typeof va === "number" && typeof vb === "number") {
        out[k] = lerp(va, vb, t);
      } else if (typeof va === "string" && typeof vb === "string") {
        out[k] = /^[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+$/.test(va) ? mixTriplet(va, vb, t) : mixColor(va, vb, t);
      } else {
        out[k] = t < 0.5 ? va : vb;
      }
    }
    for (k in b) {
      if (!Object.prototype.hasOwnProperty.call(b, k)) continue;
      if (!Object.prototype.hasOwnProperty.call(out, k)) out[k] = b[k];
    }
    return out;
  }

  // 云只在夜晚缺席，按 alpha 淡出，避免切换瞬间整片云消失
  function mixCloud(a, b, t) {
    if (!a && !b) return null;
    var A = a || { fill: b.fill, alpha: 0 };
    var B = b || { fill: a.fill, alpha: 0 };
    var alpha = lerp(A.alpha, B.alpha, t);
    if (alpha < 0.02) return null;
    return { fill: mixColor(A.fill, B.fill, t), alpha: alpha };
  }

  function mixPalette(a, b, t) {
    if (t <= 0) return a;
    if (t >= 1) return b;
    return {
      sky: mixList(a.sky, b.sky, t),
      water: mixList(a.water, b.water, t),
      hills: mixList(a.hills, b.hills, t),
      trees: mixColor(a.trees, b.trees, t),
      waves: lerp(a.waves, b.waves, t),
      cloud: mixCloud(a.cloud, b.cloud, t),
      mist: {
        color: mixTriplet(a.mist.color, b.mist.color, t),
        alpha: lerp(a.mist.alpha, b.mist.alpha, t)
      },
      glow: mixObject(a.glow, b.glow, t),
      sun: mixObject(a.sun, b.sun, t),
      moon: mixObject(a.moon, b.moon, t),
      stars: t < 0.5 ? a.stars : b.stars,
      flora: t < 0.5 ? a.flora : b.flora,
      frog: t < 0.5 ? a.frog : b.frog,
      energy: mixList(a.energy, b.energy, t),
      hud: {
        pill: mixColor(a.hud.pill, b.hud.pill, t),
        ink: mixColor(a.hud.ink, b.hud.ink, t),
        inkSoft: mixColor(a.hud.inkSoft, b.hud.inkSoft, t)
      }
    };
  }

  // 读取当前实际生效的配色变量（渐变中读到的是中间色，可无缝接力）
  function snapshotVars() {
    var cs = window.getComputedStyle(root);
    var out = {};
    for (var i = 0; i < FADE_VARS.length; i++) {
      out[FADE_VARS[i]] = cs.getPropertyValue(FADE_VARS[i]).trim();
    }
    return out;
  }

  function clearInlineVars() {
    for (var i = 0; i < FADE_VARS.length; i++) root.style.removeProperty(FADE_VARS[i]);
  }

  function prepVars(from, to) {
    var list = [];
    for (var i = 0; i < FADE_VARS.length; i++) {
      var name = FADE_VARS[i];
      var A = parseColor(from[name]);
      var B = parseColor(to[name]);
      if (A && B) list.push({ name: name, a: A, b: B });
    }
    return list;
  }

  function writeVars(list, t) {
    for (var i = 0; i < list.length; i++) {
      root.style.setProperty(list[i].name, mixParsed(list[i].a, list[i].b, t));
    }
  }

  function readFadeMs() {
    try {
      var v = window.getComputedStyle(root).getPropertyValue("--sky-fade").trim();
      var m = v.match(/^([\d.]+)(ms|s)$/);
      if (m && parseFloat(m[1]) > 0) {
        return m[2] === "s" ? Math.round(parseFloat(m[1]) * 1000) : Math.round(parseFloat(m[1]));
      }
    } catch (e) { /* 忽略读取失败，用兜底时长 */ }
    return FADE_FALLBACK_MS;
  }

  function emitSkyChange(mode, sky, progress) {
    try {
      document.dispatchEvent(new CustomEvent("skychange", {
        detail: { mode: mode, sky: sky, progress: progress, fading: progress < 1 }
      }));
    } catch (e) { /* 极旧浏览器忽略 */ }
  }

  // 把 html 从当前档渐变到 nextSky
  function fadeTo(nextSky, mode) {
    var prevSky = root.getAttribute("data-sky") || "day";
    var dur = reduceMotion ? 0 : readFadeMs();
    var token = ++fadeToken;

    if (dur <= 0 || prevSky === nextSky || !PALETTES[prevSky] || !PALETTES[nextSky]) {
      MIXED = null;
      clearInlineVars();
      root.setAttribute("data-sky", nextSky);
      return;
    }

    var fromPal = PALETTES[prevSky];
    var toPal = PALETTES[nextSky];

    // 先记住当前视觉配色
    var fromVars = snapshotVars();

    // 同步切到新档并读出目标配色，再立刻把旧配色钉回内联样式：
    // 三段都在同一帧内完成，浏览器不会绘制中间态，所以不会闪色。
    clearInlineVars();
    root.setAttribute("data-sky", nextSky);
    var toVars = snapshotVars();

    var varList = prepVars(fromVars, toVars);
    writeVars(varList, 0);
    MIXED = mixPalette(fromPal, toPal, 0);

    var start = -1;

    function frame(ts) {
      if (token !== fadeToken) return;
      if (start < 0) start = ts;
      var k = clamp01((ts - start) / dur);
      var e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;   // easeInOutQuad

      writeVars(varList, e);
      MIXED = mixPalette(fromPal, toPal, e);

      if (k < 1) {
        requestAnimationFrame(frame);
        return;
      }

      // 收尾：清掉内联值，交还给新档的 CSS 定义（终值一致，不会跳变）
      MIXED = null;
      clearInlineVars();
      emitSkyChange(mode, nextSky, 1);
    }

    requestAnimationFrame(frame);
  }

  function setSky(nextSky, mode, animate) {
    var prevSky = root.getAttribute("data-sky");
    if (animate && prevSky && prevSky !== nextSky) {
      fadeTo(nextSky, mode);
      return;
    }
    if (prevSky !== nextSky) {
      fadeToken++;
      MIXED = null;
      clearInlineVars();
    }
    root.setAttribute("data-sky", nextSky);
  }

  // 供 canvas 页面读取（game.html）：与 CSS 的 data-sky 保持同一份状态
  window.SkyTheme = {
    sky: function () {
      var sky = root.getAttribute("data-sky");
      return PALETTES[sky] ? sky : "day";
    },
    palette: function (name) {
      // 渐变期间返回混合色板，canvas 每帧重绘即得到平滑过渡
      if (MIXED) return MIXED;
      return PALETTES[name] || PALETTES.day;
    },
    palettes: PALETTES,
    names: SKY_NAMES,
    mixing: function () { return !!MIXED; }
  };

  // 黎明 / 傍晚的过渡窗口（以日出、日落为基准，单位：分钟）
  var DAWN_LEAD = 40;   // 日出前 40 分钟进入黎明
  var DAWN_TAIL = 32;   // 日出后 32 分钟结束黎明
  var DUSK_LEAD = 38;   // 日落前 38 分钟进入傍晚
  var DUSK_TAIL = 42;   // 日落后 42 分钟结束傍晚

  // 日出日落估算用纬度（北半球中纬度）；经度按系统时区自动估算
  var EST_LAT = 32;

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

  // options.animate：天空档位发生变化时是否走颜色渐变（首屏不渐变，避免开屏闪色）
  function apply(options) {
    var animate = !!(options && options.animate);
    var mode = readMode();
    var now = new Date();
    var sky = resolveSky(mode, now);
    var times = sunTimes(now);
    var prevSky = root.getAttribute("data-sky");

    setSky(sky, mode, animate);
    root.setAttribute("data-sky-mode", mode);
    syncUI(mode, sky, times);

    // 天空档位真的变了才通知：渐变中还会按约 60ms 的间隔持续通知，
    // 让报告页、开发者页自绘的 canvas 图表跟着逐帧重绘。
    if (prevSky !== sky) emitSkyChange(mode, sky, animate ? 0 : 1);

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
    timer = setInterval(function () { apply({ animate: true }); }, 60000);
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
        var sky = apply({ animate: true });
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
