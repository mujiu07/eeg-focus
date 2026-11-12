/* ============================================================
 * 专注小蛙 · 首页梦境池塘
 * 青蛙在三片大荷叶之间来回跳，复用游戏页的跳跃节奏、
 * 荷叶弹簧下沉/回弹与落水水花；不做视角平移，荷叶保持原位。
 * ============================================================ */
(function () {
  "use strict";

  var frog = document.getElementById("heroFrog");
  var splashLayer = document.getElementById("heroSplashes");
  var dropletLayer = document.getElementById("heroDroplets");
  var padEls = [0, 1, 2].map(function (i) { return document.getElementById("heroLily" + i); });
  var fishEls = Array.prototype.slice.call(
    document.querySelectorAll("#heroFish .pond-fish")
  );

  if (!frog || !splashLayer || !dropletLayer || padEls.some(function (el) { return !el; })) return;

  var NS = "http://www.w3.org/2000/svg";
  var FROG_OFFSET = 28;       // 青蛙中心相对荷叶中心的偏移（与游戏一致）
  var JUMP_DUR = 0.55;        // 单次跳跃时长（秒）
  var JUMP_ARC = 66;          // 跳跃抛物线高度
  var SPRING_K = 150;         // 荷叶弹簧刚度
  var SPRING_C = 9;           // 弹簧阻尼
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

  var reduceMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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
    frog.setAttribute("x", x.toFixed(2));
    frog.setAttribute("y", y.toFixed(2));
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

  function updateDips(dt) {
    for (var i = 0; i < pads.length; i++) {
      var p = pads[i];
      var acc = -SPRING_K * p.dip - SPRING_C * p.dipVel;
      p.dipVel += acc * dt;
      p.dip += p.dipVel * dt;
      if (Math.abs(p.dip) < 0.02 && Math.abs(p.dipVel) < 0.4) {
        p.dip = 0;
        p.dipVel = 0;
      }
    }
  }

  function spawnSplash(x, y) {
    // 三圈错开的涟漪（尺寸与游戏内一致）
    for (var i = 0; i < 3; i++) {
      var ripple = document.createElementNS(NS, "ellipse");
      ripple.setAttribute("fill", "none");
      ripple.setAttribute("stroke", "#ffffff");
      splashLayer.appendChild(ripple);
      splashes.push({
        el: ripple,
        x: x,
        y: y + 2,
        r0: 44 + i * 7,
        r1: 82 + i * 18,
        t: -i * 0.07,
        life: 0.75 + i * 0.14,
      });
    }

    // 一圈向外上方飞溅的水珠（与游戏一致）
    for (var j = 0; j < 14; j++) {
      var a = (Math.PI * 2 * j) / 14 + (Math.random() - 0.5) * 0.45;
      var drop = document.createElementNS(NS, "ellipse");
      drop.setAttribute("fill", "#ffffff");
      dropletLayer.appendChild(drop);
      droplets.push({
        el: drop,
        x: x + Math.cos(a) * 34,
        y: y + Math.sin(a) * 12 - 2,
        vx: Math.cos(a) * (50 + Math.random() * 75),
        vy: -(185 + Math.random() * 135) + Math.sin(a) * 35,
        r: 2 + Math.random() * 2.3,
        t: 0,
        life: 0.5 + Math.random() * 0.42,
      });
    }
  }

  function removeNode(el) {
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  function updateSplashes(dt) {
    splashes = splashes.filter(function (p) {
      p.t += dt;
      if (p.t >= p.life) {
        removeNode(p.el);
        return false;
      }
      if (p.t < 0) {
        p.el.setAttribute("opacity", "0");
        return true;
      }
      var k = p.t / p.life;
      var r = p.r0 + (p.r1 - p.r0) * k;
      p.el.setAttribute("cx", p.x.toFixed(2));
      p.el.setAttribute("cy", p.y.toFixed(2));
      p.el.setAttribute("rx", r.toFixed(2));
      p.el.setAttribute("ry", (r * 0.42).toFixed(2));
      p.el.setAttribute("stroke-opacity", (0.78 * (1 - k)).toFixed(3));
      p.el.setAttribute("stroke-width", (3 * (1 - k) + 0.8).toFixed(2));
      p.el.setAttribute("opacity", "1");
      return true;
    });

    droplets = droplets.filter(function (d) {
      d.t += dt;
      if (d.t >= d.life) {
        removeNode(d.el);
        return false;
      }
      d.vy += 700 * dt;   // 水珠受重力回落
      d.x += d.vx * dt;
      d.y += d.vy * dt;
      var k = d.t / d.life;
      var stretch = 1 + Math.min(1.1, Math.abs(d.vy) / 520);
      d.el.setAttribute("cx", d.x.toFixed(2));
      d.el.setAttribute("cy", d.y.toFixed(2));
      d.el.setAttribute("rx", d.r.toFixed(2));
      d.el.setAttribute("ry", (d.r * stretch).toFixed(2));
      d.el.setAttribute("fill-opacity", (0.92 * (1 - k * k)).toFixed(3));
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
    dipLily(p, 250);            // 落地：目标荷叶被压下
    spawnSplash(p.x, p.y + 6);  // 落水水花
  }

  function step(dt, t) {
    updateDips(dt);
    updateSplashes(dt);

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
    step(dt, ts / 1000);
    requestAnimationFrame(tick);
  }

  // 首帧先摆好位置，再开始动画
  var startT = performance.now() / 1000;
  for (var i = 0; i < pads.length; i++) setPad(pads[i], i, startT, 0.016);
  setFrog(startT);
  setFish(startT);

  if (!reduceMotion) requestAnimationFrame(tick);
})();
