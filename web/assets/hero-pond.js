/* ============================================================
 * 专注小蛙 · 首页梦境池塘
 * 青蛙在三片大荷叶之间来回跳，复用游戏页的跳跃节奏、
 * 荷叶弹簧下沉/回弹与落水水花；不做视角平移，荷叶保持原位。
 * ============================================================ */
(function () {
  "use strict";

  var frog = document.getElementById("heroFrog");
  var frogTouch = document.getElementById("pond-frog-touch");
  var frogArtwork = document.getElementById("pondFrogArtwork");
  var splashLayer = document.getElementById("heroSplashes");
  var dropletLayer = document.getElementById("heroDroplets");
  var padEls = [0, 1, 2].map(function (i) { return document.getElementById("heroLily" + i); });
  var fishEls = Array.prototype.slice.call(
    document.querySelectorAll("#heroFish .pond-fish")
  );

  if (!frog || !frogArtwork || !splashLayer || !dropletLayer || padEls.some(function (el) { return !el; })) return;

  var NS = "http://www.w3.org/2000/svg";
  var FROG_OFFSET = 28;       // 青蛙中心相对荷叶中心的偏移（与游戏一致）
  var JUMP_DUR = 0.55;        // 单次跳跃时长（秒）
  var JUMP_ARC = 66;          // 跳跃抛物线高度
  var START_DELAY = 0.9;      // 首跳前停顿
  var TURN_PAUSE = 0.45;      // 每次落地稳定后的停顿
  var FISH_TURN_DUR = 0.46;   // 小鱼原地转身时长（秒）
  var FISH_TURN_SLOW = 0.14;  // 转身期间游速衰减，保证“原地”

  var pads = padEls.map(function (el, i) {
    return {
      el: el,
      x: parseFloat(el.getAttribute("data-x")) || 0,
      y: parseFloat(el.getAttribute("data-y")) || 0,
      s: parseFloat(el.getAttribute("data-scale")) || 1,
      phase: i * 2.1 + 0.8,
      dip: 0,
      dipVel: 0,
      hl: i === 1 ? 1 : 0,
    };
  });

  var cur = 1;          // 当前荷叶：中间
  var dir = 1;          // 先往右跳
  var jumping = null;   // { t, from, to }
  var mode = "pause";   // pause | jumping | settle
  var pause = START_DELAY;
  var splashes = [];    // 涟漪 { el, x, y, r0, r1, t, life }
  var droplets = [];    // 水珠 { el, x, y, vx, vy, r, t, life }
  var lastTs = 0;

  var fishes = fishEls.map(function (el) {
    var ph = parseFloat(el.getAttribute("data-phase")) || 0;
    return {
      el: el,
      cx: parseFloat(el.getAttribute("data-cx")) || 0,
      cy: parseFloat(el.getAttribute("data-cy")) || 0,
      ax: parseFloat(el.getAttribute("data-ax")) || 0,
      ay: parseFloat(el.getAttribute("data-ay")) || 0,
      sp: parseFloat(el.getAttribute("data-sp")) || 0.25,
      s: parseFloat(el.getAttribute("data-scale")) || 1,
      ph: ph,
      a: 0,                                    // 累积相位：转身时会慢下来
      dir: Math.cos(ph) >= 0 ? 1 : -1,         // 当前朝向
      turning: false,
      turnT: 0,
      turnFrom: 1,
    };
  });

  var motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  var raf = 0;
  var visible = true;

  // 首页的跳跃尾迹：只有穿戴「星星尾迹」时生成，配色读装扮面板当前选择
  var trailLayer = document.getElementById("heroTrail");
  var trail = {
    on: false,
    el: null,
    pts: [],
    stars: [],
    palette: null,
    lastStar: 0,
    fade: 0,
  };

  function appendShape(parent, tag, attributes) {
    var shape = document.createElementNS(NS, tag);
    Object.entries(attributes).forEach(([name, value]) => shape.setAttribute(name, value));
    parent.appendChild(shape);
    return shape;
  }

  PondEffects.frogEllipses.forEach(([cx, cy, rx, ry, fill]) => {
    appendShape(frogArtwork, "ellipse", { cx, cy, rx, ry, fill });
  });
  var mouth = PondEffects.frogMouth;
  appendShape(frogArtwork, "path", {
    d: "M " + mouth.start.join(" ") + " Q " + mouth.curve.join(" "),
    fill: "none", stroke: mouth.color, "stroke-width": mouth.width,
  });

  function setPad(p, i, t, dt) {
    var bob = Math.sin(t * 1.4 + p.phase) * 2.5;
    var squash = Math.max(-0.075, Math.min(0.13, p.dip * 0.013));
    var target = i === cur ? 1 : 0;
    p.hl += (target - p.hl) * Math.min(1, dt * 8);
    var s = p.s * (1 + 0.08 * p.hl);
    var y = p.y + bob + p.dip;
    p.el.setAttribute(
      "transform",
      "translate(" + p.x.toFixed(2) + " " + y.toFixed(2) + ") scale(" +
        (s * (1 + squash * 0.5)).toFixed(4) + " " + (s * (1 - squash)).toFixed(4) + ")"
    );
  }

  function setFrog(t) {
    var x, y;
    if (jumping) {
      var k = Math.min(jumping.t / JUMP_DUR, 1);
      var a = pads[jumping.from];
      var b = pads[jumping.to];
      x = a.x + (b.x - a.x) * k;
      y = (a.y - FROG_OFFSET) + ((b.y - FROG_OFFSET) - (a.y - FROG_OFFSET)) * k
        - Math.sin(k * Math.PI) * JUMP_ARC;
    } else {
      var p = pads[cur];
      x = p.x;
      y = p.y + p.dip - FROG_OFFSET + Math.sin(t * 2.2) * 2;
    }
    frog.setAttribute("transform", "translate(" + x.toFixed(2) + " " + y.toFixed(2) + ")");
    if (frogTouch) {
      const { width, height } = frog.ownerSVGElement.viewBox.baseVal;
      frogTouch.style.left = (x / width * 100) + "%";
      frogTouch.style.top = (y / height * 100) + "%";
    }
    if (jumping) pushTrail(x, y + 4, t);
  }

  // ---------- 跳跃尾迹：线条光 + 星屑 ----------
  // 读取「当前穿戴的光效 + 当前颜色」；没穿星星尾迹就返回 null
  function trailPaletteNow() {
    if (!window.DressUp || typeof DressUp.wearing !== "function") return null;
    var set = DressUp.wearing();
    if (!set || set.aura !== "aura-trail") return null;
    var palettes = DressUp.palettes ? DressUp.palettes() : null;
    var colors = DressUp.colors ? DressUp.colors() : null;
    var list = (palettes && palettes.trail) || [];
    var picked = list[0];
    for (var i = 0; i < list.length; i++) {
      if (colors && list[i].id === colors.trail) { picked = list[i]; break; }
    }
    return picked ? picked.colors : null;
  }

  // 用中点二次曲线把采样点连成顺滑光带
  function trailPath(pts) {
    if (pts.length < 2) return "";
    var d = "M" + pts[0][0].toFixed(1) + " " + pts[0][1].toFixed(1);
    for (var i = 1; i < pts.length - 1; i++) {
      var mx = (pts[i][0] + pts[i + 1][0]) / 2;
      var my = (pts[i][1] + pts[i + 1][1]) / 2;
      d += " Q" + pts[i][0].toFixed(1) + " " + pts[i][1].toFixed(1) +
        " " + mx.toFixed(1) + " " + my.toFixed(1);
    }
    var last = pts[pts.length - 1];
    d += " L" + last[0].toFixed(1) + " " + last[1].toFixed(1);
    return d;
  }

  function beginTrail() {
    if (!trailLayer || motion.matches) return;
    var palette = trailPaletteNow();
    if (!palette) return;
    trailLayer.innerHTML = "";
    trailLayer.setAttribute("opacity", "1");
    var line = function (stroke, width, opacity) {
      return appendShape(trailLayer, "path", {
        fill: "none",
        stroke: stroke,
        "stroke-width": width,
        "stroke-linecap": "round",
        "stroke-linejoin": "round",
        opacity: opacity,
      });
    };
    trail.el = {
      glow: line(palette[2] || palette[0], 14, 0.14),
      mid: line(palette[0], 7, 0.32),
      core: line(palette[0], 2.6, 0.9),
      stars: appendShape(trailLayer, "g", {}),
    };
    trail.pts = [];
    trail.stars = [];
    trail.palette = palette;
    trail.on = true;
    trail.lastStar = 0;
    trail.fade = 0;
  }

  function endTrail() {
    trail.on = false;
    trail.fade = 0;
  }

  // 跳跃中每帧把青蛙位置接到光带上；落地后由 updateTrail 淡出
  function pushTrail(x, y, t) {
    if (!trail.on || !trail.el) return;
    var pts = trail.pts;
    var last = pts[pts.length - 1];
    if (last && Math.hypot(x - last[0], y - last[1]) < 1.2) {
      last[0] = x;
      last[1] = y;
    } else {
      pts.push([x, y]);
      if (pts.length > 26) pts.shift();
    }
    if (pts.length > 1) {
      var d = trailPath(pts);
      trail.el.glow.setAttribute("d", d);
      trail.el.mid.setAttribute("d", d);
      trail.el.core.setAttribute("d", d);
    }

    // 星屑：沿光带落下一串小星，颜色同样来自当前选择
    if (t - trail.lastStar > 0.055) {
      trail.lastStar = t;
      var pal = trail.palette;
      var ci = Math.random() < 0.55 ? 0 : (Math.random() < 0.8 ? 1 : 2);
      var sx = x + (Math.random() - 0.5) * 18;
      var sy = y + (Math.random() - 0.5) * 14;
      var r = 1.3 + Math.random() * 1.5;
      var star = appendShape(trail.el.stars, "circle", {
        cx: sx.toFixed(1),
        cy: sy.toFixed(1),
        r: r.toFixed(2),
        fill: pal[ci % pal.length],
        opacity: 0.9,
      });
      trail.stars.push({
        el: star,
        x: sx,
        y: sy,
        vx: (Math.random() - 0.5) * 28,
        vy: -14 - Math.random() * 20,
        r: r,
        born: t,
        life: 0.45 + Math.random() * 0.4,
      });
    }
  }

  function updateTrail(dt, t) {
    if (!trail.el) return;
    var alive = [];
    trail.stars.forEach(function (s) {
      var age = t - s.born;
      if (age >= s.life) { s.el.remove(); return; }
      s.x += s.vx * dt;
      s.y += s.vy * dt;
      s.vy += 20 * dt;
      var k = age / s.life;
      s.el.setAttribute("cx", s.x.toFixed(1));
      s.el.setAttribute("cy", s.y.toFixed(1));
      s.el.setAttribute("r", (s.r * (1 - k * 0.55)).toFixed(2));
      s.el.setAttribute("opacity", (0.9 * (1 - k)).toFixed(3));
      alive.push(s);
    });
    trail.stars = alive;

    // 光带在落地后 0.45 s 内整体淡出，避免突然消失
    if (!trail.on) {
      trail.fade += dt;
      var a = Math.max(0, 1 - trail.fade / 0.45);
      trailLayer.setAttribute("opacity", a.toFixed(3));
      if (a <= 0) {
        trailLayer.innerHTML = "";
        trail.el = null;
        trail.pts = [];
        trail.stars = [];
      }
    }
  }

  // 小鱼沿平缓的正弦轨迹在水下游动；到达轨迹端点换向时，
  // 不再瞬间镜像翻转，而是原地做一个“绕纵轴”的转身：
  // 身体横向压扁到接近正对镜头，再朝新方向展开，同时微微侧倾、上浮。
  function setFish(dt) {
    for (var i = 0; i < fishes.length; i++) {
      var f = fishes[i];

      // 转身时几乎停在原地，转身结束后恢复正常游速
      f.a += dt * f.sp * (f.turning ? FISH_TURN_SLOW : 1);

      var a = f.a + f.ph;
      var turning = f.turning;
      var p = 0;
      if (turning) {
        f.turnT += dt;
        p = Math.min(f.turnT / FISH_TURN_DUR, 1);
        if (p >= 1) {                 // 转身完成：朝向彻底翻转
          f.dir = -f.turnFrom;
          f.turning = false;
          turning = false;
          p = 0;
        }
      }

      var x = f.cx + Math.sin(a) * f.ax;
      var y = f.cy + Math.sin(a * 1.6 + f.ph) * f.ay;
      var sx, sy, tilt = 0;
      var wob = Math.sin(a * 5.5 + i * 0.9) * 3.2;

      if (turning) {
        var arc = Math.sin(p * Math.PI);       // 转身中段最大
        var sweep = Math.cos(p * Math.PI);     // +1 → -1：身体绕纵轴转过半圈
        sx = f.s * f.turnFrom * sweep;
        sy = f.s * (1 + 0.1 * arc);            // 侧身时略微“立”起来
        tilt = -f.turnFrom * 5 * arc;          // 抬头顶水，转身更灵动
        y -= arc * 1.6;                        // 原地轻轻上浮
        wob += Math.sin(p * Math.PI * 4) * 1.8 * f.turnFrom;
      } else {
        sx = f.s * f.dir;
        sy = f.s;
      }

      f.el.setAttribute(
        "transform",
        "translate(" + x.toFixed(2) + " " + y.toFixed(2) + ") rotate(" +
          (wob + tilt).toFixed(2) + ") scale(" + sx.toFixed(3) + " " + sy.toFixed(4) + ")"
      );

      // 轨迹走到端点（cos 变号）时触发原地转身
      if (!f.turning) {
        var desired = Math.cos(a) >= 0 ? 1 : -1;
        if (desired !== f.dir) {
          f.turning = true;
          f.turnT = 0;
          f.turnFrom = f.dir;
        }
      }
    }
  }

  function dipLily(p, impulse) {
    if (!p) return;
    p.dipVel += impulse;
  }

  function spawnSplash(x, y) {
    var effect = PondEffects.landing(x, y);
    splashes = effect.ripples;
    droplets = effect.droplets;
    splashes.forEach(p => {
      p.el = appendShape(splashLayer, "ellipse", { fill: "none", stroke: "#fff", opacity: 0 });
    });
    droplets.forEach(p => {
      p.el = appendShape(dropletLayer, "ellipse", { fill: "#fff", opacity: 0 });
    });
  }

  function updateParticles(particles, dt, style, advance) {
    return particles.filter(p => {
      p.t += dt;
      if (p.t >= p.life) {
        p.el.remove();
        return false;
      }
      if (advance) advance(p, dt);
      var shape = style(p);
      p.el.setAttribute("cx", p.x);
      p.el.setAttribute("cy", p.y);
      p.el.setAttribute("rx", shape.rx);
      p.el.setAttribute("ry", shape.ry);
      p.el.setAttribute("opacity", shape.opacity);
      if (shape.width !== undefined) p.el.setAttribute("stroke-width", shape.width);
      return true;
    });
  }

  function startJump() {
    var next = cur + dir;
    if (next < 0 || next >= pads.length) {
      dir = -dir;
      next = cur + dir;
    }
    dipLily(pads[cur], 170);   // 蹬水起跳：起跳荷叶轻微下沉
    jumping = { t: 0, from: cur, to: next };
    mode = "jumping";
    beginTrail();
    PondAudio.play("jump", 2);   // 首页起跳音效为原来的 2 倍音量
  }

  function land() {
    cur = jumping.to;
    jumping = null;
    mode = "settle";
    endTrail();
    var p = pads[cur];
    dipLily(p, PondEffects.landingImpulse);            // 落地：目标荷叶被压下
    spawnSplash(p.x, p.y + 6);  // 落水水花
    HeroWater?.disturb(p.x, p.y + 7, 2.8);
    PondAudio.play("land", 2);   // 首页落地水声为原来的 2 倍音量
  }

  function step(dt, t) {
    pads.forEach(p => PondEffects.advancePad(p, dt));
    splashes = updateParticles(splashes, dt, PondEffects.rippleStyle);
    droplets = updateParticles(droplets, dt, PondEffects.dropletStyle, PondEffects.advanceDroplet);

    if (jumping) {
      jumping.t += dt;
      if (jumping.t >= JUMP_DUR) land();
    } else if (mode === "settle") {
      var p = pads[cur];
      var calm = Math.abs(p.dip) < 0.4 && Math.abs(p.dipVel) < 2;
      if (!splashes.length && !droplets.length && calm) {
        mode = "pause";
        pause = TURN_PAUSE;
      }
    } else if (mode === "pause") {
      pause -= dt;
      if (pause <= 0) startJump();
    }

    for (var i = 0; i < pads.length; i++) setPad(pads[i], i, t, dt);
    setFrog(t);
    updateTrail(dt, t);
    setFish(dt);
  }

  function tick(ts) {
    if (!lastTs) lastTs = ts;
    var dt = Math.min((ts - lastTs) / 1000, 0.05);
    lastTs = ts;
    var time = ts / 1000;
    step(dt, time);
    HeroWater?.step(dt, time);
    raf = requestAnimationFrame(tick);
  }

  function syncAnimation() {
    if (motion.matches || !visible || document.hidden) {
      cancelAnimationFrame(raf);
      raf = 0;
      lastTs = 0;
    } else if (!raf) {
      raf = requestAnimationFrame(tick);
    }
  }

  // 首帧先摆好位置，再开始动画
  var startT = performance.now() / 1000;
  for (var i = 0; i < pads.length; i++) setPad(pads[i], i, startT, 0.016);
  setFrog(startT);
  setFish(0);
  if (frogTouch && PondAudio.supported) {
    frogTouch.classList.remove("hidden");
    frogTouch.addEventListener("click", () => PondAudio.play("croak"));
  }

  if ("IntersectionObserver" in window) {
    new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      syncAnimation();
    }).observe(frog.ownerSVGElement);
  }
  document.addEventListener("visibilitychange", syncAnimation);
  motion.addEventListener("change", syncAnimation);
  syncAnimation();
})();
