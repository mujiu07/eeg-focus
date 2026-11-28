/* ============================================================
 * 专注小蛙 · 平静校准池塘 v1.9.4
 *
 * 用于每日校准的「自然观察」阶段：固定、低刺激、睁眼观察。
 * 复用 PondEffects 的同一套荷叶/小蛙几何（与首页和游戏一致），
 * 只做轻微水波、缓慢漂浮和自然眨眼；没有剧情、奖励、闪光、
 * 突然变化或追踪任务，也不加载任何外部视频。
 * ============================================================ */
(function () {
  "use strict";

  function palette() {
    if (window.SkyTheme && window.SkyTheme.palette) {
      try {
        return window.SkyTheme.palette(window.SkyTheme.sky());
      } catch (_) { /* 回退到固定日间色 */ }
    }
    return {
      sky: ["#e7f7f4", "#d6f0ea", "#c6e9e2"],
      water: ["#a9dfe3", "#78c3cf"],
      hills: ["rgba(184, 224, 211, .72)", "rgba(157, 207, 197, .84)"],
      flora: "none", frog: "none",
    };
  }

  function create(canvas, options) {
    if (!canvas || !canvas.getContext) return null;
    var opts = options || {};
    var ctx = canvas.getContext("2d");
    // pond-effects.js 用 const 声明，挂在全局词法作用域而不是 window 上。
    var PE = window.PondEffects || (typeof PondEffects !== "undefined" ? PondEffects : null);
    var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    var raf = 0;
    var running = false;
    var lastTick = 0;
    var clock = 0;
    var blinkT = -1;
    var nextBlink = 4.5;
    var hopT = -1;
    var rippleT = -1;
    var w = 0, h = 0, dpr = 1;

    function resize() {
      var rect = canvas.getBoundingClientRect();
      var cssW = Math.max(280, rect.width || 640);
      var cssH = Math.max(160, rect.height || cssW * 9 / 16);
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
      w = cssW;
      h = cssH;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function lily(cx, cy, scale) {
      ctx.save();
      ctx.translate(cx, cy);
      ctx.scale(scale, scale);
      if (PE && PE.paintLily) PE.paintLily(ctx);
      ctx.restore();
    }

    function frog(cx, cy, scale, lifted) {
      if (!PE || !PE.paintFrog) return;
      var shapes = window.DressUp && DressUp.skinEllipses
        ? DressUp.skinEllipses(null, PE.frogEllipses)
        : PE.frogEllipses;
      var mouth = window.DressUp && DressUp.skinMouth
        ? DressUp.skinMouth()
        : PE.frogMouth;
      ctx.save();
      ctx.translate(cx, cy - (lifted || 0));
      ctx.scale(scale, scale);
      // 贴着荷叶的柔和阴影
      ctx.save();
      ctx.globalAlpha = 0.16;
      ctx.fillStyle = "#1d6f86";
      ctx.beginPath();
      ctx.ellipse(0, 30 + (lifted || 0), 25, 8, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
      if (window.DressUp) DressUp.drawCanvas(ctx, "back", 0);
      PE.paintFrog(ctx, shapes, mouth);
      if (blinkT >= 0 && blinkT < 0.16) {
        // 轻眨眼：用体色椭圆盖住眼白，不做夸张表情或突然睁大。
        ctx.fillStyle = "#609b68";
        [-14, 14].forEach(function (x) {
          ctx.beginPath();
          ctx.ellipse(x, -12, 10, 10, 0, 0, Math.PI * 2);
          ctx.fill();
        });
        ctx.strokeStyle = "#346951";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(-20, -12); ctx.quadraticCurveTo(-14, -8, -8, -12);
        ctx.moveTo(8, -12); ctx.quadraticCurveTo(14, -8, 20, -12);
        ctx.stroke();
      }
      if (window.DressUp) DressUp.drawCanvas(ctx, "front", 0);
      ctx.restore();
    }

    function draw() {
      var p = palette();
      var sky = ctx.createLinearGradient(0, 0, 0, h * 0.62);
      sky.addColorStop(0, p.sky[0]);
      sky.addColorStop(0.55, p.sky[1]);
      sky.addColorStop(1, p.sky[2]);
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, w, h);

      // 远山只保留两三层很淡的轮廓，避免强对比。
      var hillBase = h * 0.56;
      for (var i = 0; i < 2; i++) {
        ctx.fillStyle = (p.hills && p.hills[i]) || "rgba(170, 214, 202, .7)";
        ctx.beginPath();
        ctx.moveTo(-20, hillBase + i * 12);
        ctx.quadraticCurveTo(w * 0.22, hillBase - 34 + i * 12, w * 0.46, hillBase + 2 + i * 10);
        ctx.quadraticCurveTo(w * 0.72, hillBase - 22 + i * 12, w + 20, hillBase + 8 + i * 10);
        ctx.lineTo(w + 20, h);
        ctx.lineTo(-20, h);
        ctx.closePath();
        ctx.fill();
      }

      var waterTop = hillBase + 10;
      var water = ctx.createLinearGradient(0, waterTop, 0, h);
      water.addColorStop(0, (p.water && p.water[0]) || "#a9dfe3");
      water.addColorStop(1, (p.water && p.water[1]) || "#78c3cf");
      ctx.fillStyle = water;
      ctx.fillRect(0, waterTop, w, h - waterTop);

      // 极轻的水波：三条低对比正弦线，缓慢横移。
      var wavePhase = reduced.matches ? 0 : clock * 0.18;
      ctx.lineWidth = 1.2;
      for (var k = 0; k < 3; k++) {
        ctx.strokeStyle = "rgba(255,255,255," + (0.16 - k * 0.04) + ")";
        ctx.beginPath();
        for (var x = -20; x <= w + 20; x += 12) {
          var y = waterTop + 34 + k * 34 + Math.sin((x / 90) + wavePhase + k * 1.7) * 3.2;
          if (x === -20) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      var bob = reduced.matches ? 0 : Math.sin(clock * 1.15) * 1.6;
      var lilyX = w * 0.5;
      var lilyY = h * 0.78 + bob;
      var lilyScale = Math.min(1.15, Math.max(0.78, w / 720));

      // 远处的小荷叶，只做静态点景。
      lily(w * 0.19, h * 0.69, lilyScale * 0.56);
      lily(w * 0.82, h * 0.72, lilyScale * 0.48);

      // 偶发的一圈很淡的涟漪（每 6 秒最多一次，不闪烁）。
      if (rippleT >= 0 && !reduced.matches) {
        var rt = rippleT / 2.6;
        if (rt <= 1) {
          ctx.save();
          ctx.strokeStyle = "rgba(255,255,255," + (0.22 * (1 - rt)) + ")";
          ctx.lineWidth = 1.4;
          ctx.beginPath();
          ctx.ellipse(lilyX, lilyY + 8, 58 + rt * 34, 18 + rt * 11, 0, 0, Math.PI * 2);
          ctx.stroke();
          ctx.restore();
        }
      }

      lily(lilyX, lilyY, lilyScale);
      var lift = 0;
      if (hopT >= 0) {
        var hp = Math.min(1, hopT / 0.62);
        lift = Math.sin(hp * Math.PI) * 28;
      }
      frog(lilyX, lilyY - 28 * lilyScale, lilyScale * 0.92, lift);
    }

    function tick(ts) {
      if (!running) return;
      raf = requestAnimationFrame(tick);
      // 30fps 足够表现轻微漂浮，也避免校准页占用过多资源。
      if (ts - lastTick < 30) return;
      var dt = Math.min(0.1, (ts - lastTick) / 1000);
      lastTick = ts;
      clock += dt;
      if (!reduced.matches) {
        nextBlink -= dt;
        if (nextBlink <= 0) {
          blinkT = 0;
          nextBlink = 5.2 + Math.random() * 2.6;
        }
        if (blinkT >= 0) {
          blinkT += dt;
          if (blinkT > 0.2) blinkT = -1;
        }
        if (rippleT >= 0) {
          rippleT += dt;
          if (rippleT > 2.7) rippleT = -1;
        } else if (Math.random() < dt / 6) {
          rippleT = 0;
        }
        if (hopT >= 0) {
          hopT += dt;
          if (hopT > 0.66) hopT = -1;
        }
      }
      draw();
    }

    function start() {
      if (running) return api;
      running = true;
      resize();
      draw();
      lastTick = 0;
      if (!reduced.matches) raf = requestAnimationFrame(tick);
      return api;
    }

    function stop() {
      running = false;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      return api;
    }

    function hop() {
      if (reduced.matches) {
        draw();
        return api;
      }
      hopT = 0;
      rippleT = 0;
      return api;
    }

    function setReduced() {
      if (reduced.matches) {
        if (raf) cancelAnimationFrame(raf);
        raf = 0;
        draw();
      } else if (running && !raf) {
        lastTick = 0;
        raf = requestAnimationFrame(tick);
      }
    }

    if (window.ResizeObserver) {
      var ro = new ResizeObserver(function () { resize(); draw(); });
      ro.observe(canvas);
    } else {
      window.addEventListener("resize", function () { resize(); draw(); });
    }
    if (reduced.addEventListener) reduced.addEventListener("change", setReduced);

    var api = { start: start, stop: stop, hop: hop, resize: resize };
    return api;
  }

  window.CalmPond = { create: create };
})();
