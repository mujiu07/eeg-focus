// Shared scene geometry and landing motion for the SVG and Canvas ponds.
const PondEffects = {
  frogEllipses: [
    [0, 17, 29, 9, "#346951"],
    [0, 7, 24, 22, "#609b68"],
    [0, 13, 16, 13, "#b9cf94"],
    ...[-14, 14].flatMap(x => [
      [x, -12, 10, 11, "#609b68"],
      [x, -12, 6, 7, "#fbf3d9"],
      [x + 1, -12, 3, 4, "#263b33"],
    ]),
  ],
  frogMouth: { start: [-8, 5], curve: [0, 10, 8, 5], color: "#346951", width: 2 },
  landingImpulse: 250,

  // 荷叶的形状与配色：画布（游戏池塘）和转场卡片共用同一份数据，
  // 保证开局倒数里的青蛙、荷叶与游戏里长得一模一样。
  lily: {
    rx: 47,
    ry: 26,
    gradient: [[0, "#c6f3c8"], [0.65, "#74d484"], [1, "#46b463"]],
    highlight: { color: "rgba(255,255,255,.5)", width: 2.5, radius: 34, cy: 2, from: -2.2, to: -1.1 },
    vein: {
      color: "rgba(30, 96, 56, .4)", width: 1.6,
      lines: [[-34, 0, 34, 0], [0, -19, 0, 19], [-18, -11, 18, 11], [-18, 11, 18, -11]],
    },
    shadow: { color: "#1d6f86", alpha: 0.2, rx: 24, ry: 9, dy: -24 },
  },

  // 在已 translate / scale 到荷叶中心的上下文里画一片完整荷叶
  paintLily(ctx) {
    const style = PondEffects.lily;
    const g = ctx.createRadialGradient(6, -8, 4, 0, 0, 48);
    style.gradient.forEach(([stop, color]) => g.addColorStop(stop, color));
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.ellipse(0, 0, style.rx, style.ry, 0, 0, Math.PI * 2);
    ctx.fill();

    const hl = style.highlight;
    ctx.strokeStyle = hl.color;
    ctx.lineWidth = hl.width;
    ctx.beginPath();
    ctx.arc(0, hl.cy, hl.radius, hl.from, hl.to);
    ctx.stroke();

    const vein = style.vein;
    ctx.strokeStyle = vein.color;
    ctx.lineWidth = vein.width;
    ctx.beginPath();
    vein.lines.forEach(([x1, y1, x2, y2]) => {
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
    });
    ctx.stroke();
  },

  // 在已 translate 到青蛙中心的上下文里画青蛙本体（不含装扮配饰）
  paintFrog(ctx, shapes, mouth) {
    const ellipses = shapes || PondEffects.frogEllipses;
    const smile = mouth || PondEffects.frogMouth;
    ellipses.forEach(([x, y, rx, ry, color]) => {
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.strokeStyle = smile.color;
    ctx.lineWidth = smile.width;
    ctx.beginPath();
    ctx.moveTo(...smile.start);
    ctx.quadraticCurveTo(...smile.curve);
    ctx.stroke();
  },

  advancePad(pad, dt) {
    pad.dipVel += (-150 * pad.dip - 9 * pad.dipVel) * dt;
    pad.dip += pad.dipVel * dt;
    if (Math.abs(pad.dip) < 0.02 && Math.abs(pad.dipVel) < 0.4) {
      pad.dip = 0;
      pad.dipVel = 0;
    }
  },

  // 新荷叶从水下顶破水面：一圈更大的涟漪 + 中间高、四周低的水珠
  emerging(x, y) {
    const ripples = Array.from({ length: 3 }, (_, i) => ({
      x, y: y + 2, r0: 26 + i * 6, r1: 62 + i * 17,
      t: -i * 0.05, life: 0.7 + i * 0.13,
    }));
    const droplets = Array.from({ length: 13 }, (_, i) => {
      const angle = Math.PI * 2 * i / 13 + (Math.random() - 0.5) * 0.4;
      const lift = 1 - Math.abs(Math.cos(angle)) * 0.35;   // 叶心位置的水柱更高
      return {
        x: x + Math.cos(angle) * 20, y: y + Math.sin(angle) * 7 - 2,
        vx: Math.cos(angle) * (42 + Math.random() * 58),
        vy: -(205 + Math.random() * 140) * lift + Math.sin(angle) * 26,
        r: 1.6 + Math.random() * 2.2, t: 0, life: 0.45 + Math.random() * 0.4,
      };
    });
    return { ripples, droplets };
  },

  landing(x, y) {
    const ripples = Array.from({ length: 3 }, (_, i) => ({
      x, y: y + 2, r0: 44 + i * 7, r1: 82 + i * 18,
      t: -i * 0.07, life: 0.75 + i * 0.14,
    }));
    const droplets = Array.from({ length: 14 }, (_, i) => {
      const angle = Math.PI * 2 * i / 14 + (Math.random() - 0.5) * 0.45;
      return {
        x: x + Math.cos(angle) * 34, y: y + Math.sin(angle) * 12 - 2,
        vx: Math.cos(angle) * (50 + Math.random() * 75),
        vy: -(185 + Math.random() * 135) + Math.sin(angle) * 35,
        r: 2 + Math.random() * 2.3, t: 0, life: 0.5 + Math.random() * 0.42,
      };
    });
    return { ripples, droplets };
  },

  rippleStyle(particle) {
    const progress = Math.max(0, particle.t / particle.life);
    const radius = particle.r0 + (particle.r1 - particle.r0) * progress;
    return { rx: radius, ry: radius * 0.42,
      opacity: particle.t < 0 ? 0 : 0.78 * (1 - progress),
      width: 3 * (1 - progress) + 0.8 };
  },

  advanceDroplet(particle, dt) {
    particle.vy += 700 * dt;
    particle.x += particle.vx * dt;
    particle.y += particle.vy * dt;
  },

  dropletStyle(particle) {
    const progress = particle.t / particle.life;
    return { rx: particle.r, ry: particle.r * (1 + Math.min(1.1, Math.abs(particle.vy) / 520)),
      opacity: 0.92 * (1 - progress * progress) };
  },
};
