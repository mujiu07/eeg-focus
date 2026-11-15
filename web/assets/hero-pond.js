/* ============================================================
 * 专注小蛙 · 首页梦境池塘
 * 青蛙在三片大荷叶之间来回跳，复用游戏页的跳跃节奏、
 * 荷叶弹簧下沉/回弹与落水水花；不做视角平移，荷叶保持原位。
 * ============================================================ */
(function () {
  "use strict";

  var frog = document.getElementById("heroFrog");
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
    return {
      el: el,
      cx: parseFloat(el.getAttribute("data-cx")) || 0,
      cy: parseFloat(el.getAttribute("data-cy")) || 0,
      ax: parseFloat(el.getAttribute("data-ax")) || 0,
      ay: parseFloat(el.getAttribute("data-ay")) || 0,
      sp: parseFloat(el.getAttribute("data-sp")) || 0.25,
      s: parseFloat(el.getAttribute("data-scale")) || 1,
      ph: parseFloat(el.getAttribute("data-phase")) || 0,
    };
  });

  var motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  var raf = 0;
  var visible = true;

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
  }

  // 小鱼沿平缓的正弦轨迹在水下游动，掉头时水平翻转
  function setFish(t) {
    for (var i = 0; i < fishes.length; i++) {
      var f = fishes[i];
      var a = t * f.sp + f.ph;
      var x = f.cx + Math.sin(a) * f.ax;
      var y = f.cy + Math.sin(a * 1.6 + f.ph) * f.ay;
      var flip = Math.cos(a) >= 0 ? 1 : -1;
      var wob = Math.sin(a * 5.5 + i * 0.9) * 3.2;
      f.el.setAttribute(
        "transform",
        "translate(" + x.toFixed(2) + " " + y.toFixed(2) + ") rotate(" +
          wob.toFixed(2) + ") scale(" + (f.s * flip).toFixed(3) + " " + f.s.toFixed(3) + ")"
      );
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
  }

  function land() {
    cur = jumping.to;
    jumping = null;
    mode = "settle";
    var p = pads[cur];
    dipLily(p, PondEffects.landingImpulse);            // 落地：目标荷叶被压下
    spawnSplash(p.x, p.y + 6);  // 落水水花
    HeroWater?.disturb(p.x, p.y + 7, 2.8);
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
    setFish(t);
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
  setFish(startT);

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
