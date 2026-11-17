/* ============================================================
   专注小蛙 · 装扮系统
   ------------------------------------------------------------
   · 图鉴：展示全部装扮的外观、名称、获取途径；未获得灰显
   · 装扮：自由搭配，同一类别同时只能穿戴一件（打开面板默认停在这一页）
   · 肤色：只替换青蛙本体的配色，不叠加形状，眼睛与瞳孔保持原样
   · 图鉴只用于查看：点击装扮放大展示外观与获得时间，换装请到「装扮」页
   · 配饰与青蛙使用同一套几何坐标，首页 SVG 与游戏 Canvas 共用
     ITEMS 里的形状描述，保证两处画风一致
   · 穿搭只保存在本机 localStorage（bf-outfit），不上传、不联网
   ============================================================ */
(function () {
  "use strict";

  const STORE_KEY = "bf-outfit";
  const OWNED_KEY = "bf-owned";
  const OWNED_AT_KEY = "bf-owned-at";
  const TAU = Math.PI * 2;

  const CATS = [
    { id: "skin", name: "肤色", hint: "换一换小蛙身上的颜色" },
    { id: "hat", name: "头饰", hint: "戴在头顶的小帽子" },
    { id: "face", name: "面饰", hint: "架在眼睛和嘴巴附近" },
    { id: "chest", name: "胸饰", hint: "别在左胸的小徽章" },
    { id: "neck", name: "颈饰", hint: "围在脖子上的小物" },
    { id: "hand", name: "手持", hint: "举在前爪的小道具" },
    { id: "back", name: "背饰", hint: "背在身后的小装饰" },
    { id: "aura", name: "光效", hint: "脚下光圈与跳跃尾迹" },
  ];

  // 光效可选颜色（也是图鉴里「彩虹」的取色来源）
  const AURA_PALETTES = {
    glow: [
      { id: "gold", name: "金色", colors: ["#ffd166", "#ffe9a8", "#f0a94e"] },
      { id: "pink", name: "粉色", colors: ["#ff9fc4", "#ffc7dc", "#f07ba8"] },
      { id: "rainbow", name: "彩虹", colors: ["#ff8f8f", "#8fd8ea", "#ffd166"] },
    ],
    trail: [
      { id: "red", name: "红", colors: ["#ff7b7b"] },
      { id: "orange", name: "橙", colors: ["#ffa94d"] },
      { id: "yellow", name: "黄", colors: ["#ffd93d"] },
      { id: "green", name: "绿", colors: ["#6fd08c"] },
      { id: "blue", name: "蓝", colors: ["#6fb6f2"] },
      { id: "purple", name: "紫", colors: ["#b08cf0"] },
      { id: "pink", name: "粉", colors: ["#ff9fc4"] },
    ],
  };

  // ---------- 形状工厂（青蛙本地坐标，原点 = 青蛙中心） ----------
  const E = (x, y, rx, ry, fill, extra) =>
    Object.assign({ s: "ellipse", x, y, rx, ry, fill }, extra);
  const C = (x, y, r, fill, extra) =>
    Object.assign({ s: "circle", x, y, r, fill }, extra);
  const R = (x, y, w, h, r, fill, extra) =>
    Object.assign({ s: "rect", x, y, w, h, r, fill }, extra);
  const P = (d, fill, extra) =>
    Object.assign({ s: "path", d, fill }, extra);
  const K = (d, stroke, w, extra) =>
    Object.assign({ s: "path", d, fill: "none", stroke, w }, extra);
  const L = (x1, y1, x2, y2, stroke, w, extra) =>
    Object.assign({ s: "line", x1, y1, x2, y2, stroke, w }, extra);

  // 五角星路径（用于王冠、墨镜、勋章上的高光）
  function starPath(cx, cy, r) {
    const pts = [];
    for (let i = 0; i < 10; i++) {
      const rad = i % 2 === 0 ? r : r * 0.44;
      const a = -Math.PI / 2 + i * Math.PI / 5;
      pts.push((cx + Math.cos(a) * rad).toFixed(2) + " " + (cy + Math.sin(a) * rad).toFixed(2));
    }
    return "M" + pts.join(" L") + " Z";
  }

  // ---------- 装扮数据 ----------
  // 每件装扮的 shapes.front 画在青蛙前面，shapes.back 画在青蛙后面
  const ITEMS = [
    // ===== 肤色 =====
    // 肤色不带形状，只替换青蛙本体的三层配色（深色底 / 体色 / 肚皮），
    // 眼睛的高光与瞳孔保持原样，换色后依然是一只干净的小蛙。
    {
      id: "skin-moss", cat: "skin", name: "苔绿小蛙", from: "初始拥有", ach: null,
      skin: { deep: "#346951", body: "#609b68", belly: "#b9cf94" },
    },
    {
      id: "skin-sakura", cat: "skin", name: "樱花小蛙", from: "初始拥有", ach: null,
      skin: { deep: "#a84a66", body: "#ef9db4", belly: "#ffe9f0" },
    },
    {
      id: "skin-sky", cat: "skin", name: "天空小蛙", from: "累计专注满 30 分钟", ach: "doctor-1", price: 6,
      skin: { deep: "#31638f", body: "#6fb2e0", belly: "#cfe8f8" },
    },
    {
      id: "skin-lemon", cat: "skin", name: "柠檬小蛙", from: "连续打卡 3 天", ach: "spirit-1", price: 8,
      skin: { deep: "#92801f", body: "#ddc257", belly: "#f5edc2" },
    },
    {
      id: "skin-grape", cat: "skin", name: "葡萄小蛙", from: "单局专注满 5 分钟", ach: "focus-3", price: 10,
      skin: { deep: "#503f78", body: "#9481c6", belly: "#e0d8f4" },
    },
    {
      id: "skin-dusk", cat: "skin", name: "晚霞小蛙", from: "累计专注满 600 分钟", ach: "doctor-5", price: 12,
      skin: { deep: "#9c4a22", body: "#e59362", belly: "#f8dcc4" },
    },

    // ===== 头饰 =====
    {
      id: "hat-lily", cat: "hat", name: "睡莲小帽", from: "初始拥有", ach: null,
      shapes: {
        front: [
          E(0, -18, 22, 6, "#3da45c"),
          P("M-18 -18 Q-16 -33 0 -33 Q16 -33 18 -18 Z", "#58c270"),
          K("M-11 -26 Q0 -31 11 -26", "#ffffff", 2, { alpha: 0.5 }),
          E(0, -35, 5.2, 4, "#ffd0dc"),
          E(-6.5, -33, 4, 3, "#ffdbe4"),
          E(6.5, -33, 4, 3, "#ffdbe4"),
        ],
      },
    },
    {
      id: "hat-leaf", cat: "hat", name: "大荷叶帽", from: "累计专注满 30 分钟", ach: "doctor-1", price: 6,
      shapes: {
        front: [
          E(0, -20, 26, 7.5, "#46b463"),
          P("M-14 -20 Q0 -38 14 -20 Z", "#5fc47a"),
          K("M-7 -26 Q0 -31 7 -26", "#ffffff", 2, { alpha: 0.45 }),
          L(-18, -20, -8, -23, "#1e6038", 1.2, { alpha: 0.32 }),
          L(-6, -19, 2, -22, "#1e6038", 1.2, { alpha: 0.32 }),
          L(8, -20, 18, -23, "#1e6038", 1.2, { alpha: 0.32 }),
        ],
      },
    },
    {
      id: "hat-dandelion", cat: "hat", name: "蒲公英绒帽", from: "连续打卡 3 天", ach: "spirit-1", price: 7,
      shapes: {
        front: [
          L(0, -20, 0, -28, "#7fbf8f", 2.4),
          E(0, -19, 13, 4, "#fff2cc"),
          C(0, -36, 9.5, "#fffaf0"),
          C(0, -36, 6.4, "#ffe9c4", { alpha: 0.75 }),
          L(0, -36, 0, -46, "#ffffff", 1.4, { alpha: 0.7 }),
          L(0, -36, -8, -43, "#ffffff", 1.4, { alpha: 0.7 }),
          L(0, -36, 8, -43, "#ffffff", 1.4, { alpha: 0.7 }),
          L(0, -36, -10, -36, "#ffffff", 1.4, { alpha: 0.55 }),
          L(0, -36, 10, -36, "#ffffff", 1.4, { alpha: 0.55 }),
        ],
      },
    },
    {
      id: "hat-crown", cat: "hat", name: "青蛙小皇冠", from: "单局专注满 5 分钟", ach: "focus-3", price: 12,
      shapes: {
        front: [
          P("M-15 -18 L-17 -33 L-8 -27 L0 -38 L8 -27 L17 -33 L15 -18 Z",
            "#ffd27f", { stroke: "#e0a34a", w: 1.6 }),
          R(-15.5, -23, 31, 5, 2, "#f0a94e"),
          C(0, -25, 2.6, "#ff8f9e"),
          C(-10, -25, 2, "#8fd8ea"),
          C(10, -25, 2, "#8fd8ea"),
        ],
      },
    },
    {
      id: "hat-rain", cat: "hat", name: "雨滴小帽", from: "累计专注满 600 分钟", ach: "doctor-5", price: 8,
      shapes: {
        front: [
          P("M0 -41 C9 -30 15 -25 15 -18 A15 15 0 0 1 -15 -18 C-15 -25 -9 -30 0 -41 Z",
            "#8fd8ea", { stroke: "#58b6d4", w: 1.5 }),
          E(0, -17, 18, 4.5, "#6fc4dc"),
          K("M-8 -22 Q-5 -28 -2 -33", "#ffffff", 2.4, { alpha: 0.6 }),
        ],
      },
    },

    // ===== 面饰 =====
    {
      id: "face-round", cat: "face", name: "圆框水镜", from: "初始拥有", ach: null,
      shapes: {
        front: [
          C(-14, -12, 10.5, "rgba(255,255,255,.30)", { stroke: "#2f9c93", w: 2.6 }),
          C(14, -12, 10.5, "rgba(255,255,255,.30)", { stroke: "#2f9c93", w: 2.6 }),
          K("M-4 -12 Q0 -15.5 4 -12", "#2f9c93", 2.6),
          L(-24, -13, -27, -16, "#2f9c93", 2.4),
          L(24, -13, 27, -16, "#2f9c93", 2.4),
          K("M-19 -16 Q-16 -19 -12 -19", "#ffffff", 2, { alpha: 0.65 }),
        ],
      },
    },
    {
      id: "face-star", cat: "face", name: "星星墨镜", from: "单局专注满 10 分钟", ach: "focus-4", price: 7,
      shapes: {
        front: [
          C(-14, -12, 10.5, "rgba(35,70,79,.9)", { stroke: "#23464f", w: 1.6 }),
          C(14, -12, 10.5, "rgba(35,70,79,.9)", { stroke: "#23464f", w: 1.6 }),
          K("M-3.5 -12.5 Q0 -15 3.5 -12.5", "#23464f", 2.4),
          P(starPath(-14, -12, 5.4), "#ffe9c4"),
          P(starPath(14, -12, 5.4), "#ffe9c4"),
        ],
      },
    },
    {
      id: "face-dive", cat: "face", name: "潜水小镜", from: "累计专注满 60 分钟", ach: "doctor-2", price: 8,
      shapes: {
        front: [
          E(-14, -11.5, 12.5, 11, "rgba(143,216,234,.62)", { stroke: "#4fa9c4", w: 2.4 }),
          E(14, -11.5, 12.5, 11, "rgba(143,216,234,.62)", { stroke: "#4fa9c4", w: 2.4 }),
          R(-4, -13.5, 8, 4, 2, "#4fa9c4"),
          K("M-26.5 -11 Q-32 -6 -30 2", "#4fa9c4", 3),
          K("M26.5 -11 Q32 -6 30 2", "#4fa9c4", 3),
          E(-18, -15, 3.4, 2, "#ffffff", { alpha: 0.55, rot: -0.35 }),
        ],
      },
    },
    {
      id: "face-dew", cat: "face", name: "露珠单片镜", from: "连续打卡 7 天", ach: "spirit-3", price: 9,
      shapes: {
        front: [
          C(14, -12, 10, "rgba(255,255,255,.22)", { stroke: "#e0a34a", w: 2.4 }),
          K("M23 -7 Q30 0 24 8 Q18 14 20 19", "#e0a34a", 1.6),
          C(20, 19, 2.2, "#ffd27f"),
          L(24, -13, 27, -16, "#e0a34a", 2.2),
          K("M9 -16 Q12 -19 16 -19", "#ffffff", 2, { alpha: 0.6 }),
        ],
      },
    },

    // ===== 颈饰 =====
    {
      id: "neck-scarf", cat: "neck", name: "荷叶围巾", from: "单局专注满 3 分钟", ach: "focus-2", price: 6,
      shapes: {
        front: [
          P("M-17 8 Q0 18 17 8 L17 13 Q0 23 -17 13 Z", "#58c270"),
          K("M-13 11 Q0 18 13 11", "#ffffff", 2, { alpha: 0.35 }),
          P("M9 17 Q15 24 11 30 Q6 25 5 19 Z", "#46b463"),
          C(10, 18, 3.2, "#3da45c"),
        ],
      },
    },
    {
      id: "neck-bell", cat: "neck", name: "铃兰铃铛", from: "累计专注满 150 分钟", ach: "doctor-3", price: 7,
      shapes: {
        front: [
          K("M-13 10 Q0 20 13 10", "#ffd27f", 2.2),
          P("M-5 20 Q-5 14 0 14 Q5 14 5 20 Z", "#ffd27f", { stroke: "#e0a34a", w: 1.2 }),
          E(0, 20, 5, 2.2, "#ffe9c4"),
          C(0, 16, 1.3, "#e0a34a"),
          C(-1.6, 18, 1, "#ffffff", { alpha: 0.7 }),
        ],
      },
    },
    {
      id: "neck-bow", cat: "neck", name: "暖阳蝴蝶结", from: "连续打卡 5 天", ach: "spirit-2", price: 6,
      shapes: {
        front: [
          P("M0 14 L-14 6 Q-17.5 14 -14 22 Z", "#ffb0a8", { stroke: "#f08f86", w: 1.2 }),
          P("M0 14 L14 6 Q17.5 14 14 22 Z", "#ffb0a8", { stroke: "#f08f86", w: 1.2 }),
          C(0, 14, 3.8, "#ff8f86"),
          C(-1.2, 12.6, 1.2, "#ffffff", { alpha: 0.6 }),
        ],
      },
    },
    {
      id: "neck-medal", cat: "neck", name: "池塘小勋章", from: "连续打卡 15 天", ach: "spirit-4", price: 10,
      shapes: {
        front: [
          L(-9, 9, -1, 20, "#58b6d4", 3),
          L(9, 9, 1, 20, "#58b6d4", 3),
          C(0, 21, 7.5, "#ffd27f", { stroke: "#e0a34a", w: 1.5 }),
          C(0, 21, 5.2, "#ffe9c4"),
          P(starPath(0, 21, 3.8), "#f0a94e"),
        ],
      },
    },

    // ===== 背饰（画在身体后面） =====
    {
      id: "back-bag", cat: "back", name: "荷叶小包", from: "单局专注满 1 分钟", ach: "focus-1", price: 8,
      shapes: {
        back: [
          R(-31, -6, 20, 24, 7, "#f7a455"),
          P("M-31 0 Q-21 -8 -11 0 L-11 4 Q-21 10 -31 4 Z", "#ffc37e"),
          C(-21, 4, 2.2, "#ffd27f"),
          K("M-15 -4 Q-5 -9 2 -2", "#e08f3f", 2.5),
          R(-29, 6, 16, 3, 1.5, "#ffffff", { alpha: 0.25 }),
        ],
      },
    },
    {
      id: "back-wing", cat: "back", name: "蜻蜓翅膀", from: "累计专注满 300 分钟", ach: "doctor-4", price: 15,
      shapes: {
        back: [
          E(-25, -8, 14, 6, "rgba(207,239,245,.74)", { stroke: "#9fd8e2", w: 1.5, rot: -0.32 }),
          E(-23, -1, 11, 4.6, "rgba(207,239,245,.66)", { stroke: "#9fd8e2", w: 1.4, rot: -0.12 }),
          E(25, -8, 14, 6, "rgba(207,239,245,.74)", { stroke: "#9fd8e2", w: 1.5, rot: 0.32 }),
          E(23, -1, 11, 4.6, "rgba(207,239,245,.66)", { stroke: "#9fd8e2", w: 1.4, rot: 0.12 }),
        ],
      },
    },
    {
      id: "back-bubble", cat: "back", name: "泡泡背包", from: "连续打卡 30 天", ach: "spirit-5", price: 12,
      shapes: {
        back: [
          C(-24, 2, 9.5, "rgba(205,238,247,.88)", { stroke: "#8fd0e0", w: 1.4 }),
          C(-30, -6, 5.8, "rgba(205,238,247,.82)", { stroke: "#8fd0e0", w: 1.2 }),
          C(-15, -7, 4.4, "rgba(205,238,247,.82)", { stroke: "#8fd0e0", w: 1.2 }),
          C(-27, -2, 2.4, "#ffffff", { alpha: 0.7 }),
          C(-20, 6, 1.6, "#ffffff", { alpha: 0.55 }),
        ],
      },
    },
    {
      id: "back-cape", cat: "back", name: "星光小披风", from: "第一次校准成功", ach: "guardian-first", price: 14,
      shapes: {
        back: [
          P("M-26 -4 Q0 -16 26 -4 L22 26 Q0 32 -22 26 Z",
            "rgba(191,232,221,.94)", { stroke: "#8fd0c2", w: 1.5 }),
          K("M-26 -4 Q0 6 26 -4", "#8fd0c2", 2),
          C(-12, 6, 1.4, "#ffffff", { alpha: 0.85 }),
          C(8, 12, 1.2, "#ffffff", { alpha: 0.75 }),
          C(-3, 22, 1.5, "#ffffff", { alpha: 0.7 }),
          C(15, 2, 1.2, "#ffffff", { alpha: 0.6 }),
        ],
      },
    },

    {
      id: "back-angel", cat: "back", name: "天使翅膀", from: "池塘守护神 III · 连续打卡 7 天",
      ach: "spirit-3", shop: false, exclusive: "池塘守护神",
      shapes: {
        back: [
          P("M-15 -8 C-30 -28 -43.5 -25 -42.6 -6 C-41.6 10 -29.6 17 -14 11 Z",
            "#fdfbf4", { stroke: "#e4dece", w: 1.3 }),
          P("M15 -8 C30 -28 43.5 -25 42.6 -6 C41.6 10 29.6 17 14 11 Z",
            "#fdfbf4", { stroke: "#e4dece", w: 1.3 }),
          K("M-25 -16 C-35 -12 -41 -4 -40 5", "#e7e1d1", 1.2, { alpha: .9 }),
          K("M25 -16 C35 -12 41 -4 40 5", "#e7e1d1", 1.2, { alpha: .9 }),
          K("M-19 -2 C-30 2 -37 9 -38 14", "#efe9db", 1.1, { alpha: .85 }),
          K("M19 -2 C30 2 37 9 38 14", "#efe9db", 1.1, { alpha: .85 }),
          K("M-15 6 C-24 9 -30 14 -31 17", "#f4efe3", 1, { alpha: .8 }),
          K("M15 6 C24 9 30 14 31 17", "#f4efe3", 1, { alpha: .8 }),
          C(0, -9, 2.6, "#ffd166"),
          C(0, -9, 1.2, "#fff3c4"),
        ],
      },
    },

    // ===== 头饰（补充） =====
    {
      id: "hat-wizard", cat: "hat", name: "魔法师尖帽", from: "累计专注满 60 分钟", ach: "doctor-2", price: 12,
      shapes: {
        front: [
          E(0, -18, 20, 5, "#4b3a78"),
          P("M-13 -19 Q-4 -34 -2 -43 Q6 -30 13 -19 Z", "#5d4a8f", { stroke: "#453466", w: 1.2 }),
          R(-13, -23, 26, 4, 2, "#3b2d63"),
          P(starPath(-5, -27, 2.8), "#ffd166"),
          P(starPath(4, -33, 2.2), "#ffe9a8"),
        ],
      },
    },
    {
      id: "hat-sakura", cat: "hat", name: "樱花发卡", from: "连续打卡 5 天", ach: "spirit-2", price: 7,
      shapes: {
        front: [
          C(12, -25, 2.4, "#ffb3c9"),
          C(16, -27, 2.4, "#ffb3c9"),
          C(18, -23, 2.4, "#ffb3c9"),
          C(14, -21, 2.4, "#ffb3c9"),
          C(10, -22, 2.4, "#ffb3c9"),
          C(14, -24, 1.7, "#ffe066"),
          C(20, -20, 1.8, "#ffc7d8"),
          C(23, -21, 1.8, "#ffc7d8"),
          C(24, -18, 1.8, "#ffc7d8"),
          C(21, -16.5, 1.8, "#ffc7d8"),
          C(18.5, -17.5, 1.8, "#ffc7d8"),
          C(21, -18.5, 1.2, "#ffe066"),
        ],
      },
    },
    {
      id: "hat-goggles", cat: "hat", name: "飞行员护目镜", from: "单局专注满 3 分钟", ach: "focus-2", price: 9,
      shapes: {
        front: [
          K("M-22 -22 Q0 -30 22 -22", "#c98f2e", 3),
          E(-11, -23, 6.5, 5.6, "rgba(255,240,200,.85)", { stroke: "#d9a441", w: 2 }),
          E(11, -23, 6.5, 5.6, "rgba(255,240,200,.85)", { stroke: "#d9a441", w: 2 }),
          R(-3, -25, 6, 3.4, 1.5, "#d9a441"),
          E(-13, -25, 2.4, 1.6, "#ffffff", { alpha: 0.6 }),
          E(9, -25, 2.4, 1.6, "#ffffff", { alpha: 0.6 }),
        ],
      },
    },
    {
      id: "hat-sailor", cat: "hat", name: "水手帽", from: "累计专注满 150 分钟", ach: "doctor-3", price: 8,
      shapes: {
        front: [
          P("M-15 -18 Q-15 -32 0 -32 Q15 -32 15 -18 Z", "#fdfbf4", { stroke: "#e6e0cf", w: 1.2 }),
          E(0, -18, 19, 5, "#f3efe2"),
          R(-13, -27, 26, 3, 1, "#5aa6d8"),
          K("M0 -30 L0 -26 M-3 -28 L3 -28 M-4 -25 Q0 -22 4 -25", "#3d7fb0", 1.6),
        ],
      },
    },
    {
      id: "hat-mushroom", cat: "hat", name: "红白小蘑菇", from: "连续打卡 3 天", ach: "spirit-1", price: 7,
      shapes: {
        front: [
          P("M-19 -16 Q-19 -35 0 -35 Q19 -35 19 -16 Z", "#e8635f", { stroke: "#d04f4b", w: 1.2 }),
          E(0, -16, 19, 4.5, "#f7d7d5"),
          R(-3.5, -16, 7, 6, 2, "#fdf6e8"),
          C(-9, -25, 3, "#fffaf2"),
          C(8, -28, 2.6, "#fffaf2"),
          C(0, -31, 2.2, "#fffaf2"),
          C(12, -20, 1.8, "#fffaf2"),
        ],
      },
    },
    {
      id: "hat-wreath", cat: "hat", name: "柳条花环", from: "连续打卡 7 天", ach: "spirit-3", price: 9,
      shapes: {
        front: [
          E(0, -24, 16, 5.5, "none", { stroke: "#8fbf7a", w: 4 }),
          E(-10, -25, 4, 2, "#a9d49a", { rot: -0.4 }),
          E(0, -28, 4, 2, "#a9d49a"),
          E(10, -25, 4, 2, "#a9d49a", { rot: 0.4 }),
          C(-8, -27, 2.6, "#fffaf2"),
          C(2, -29, 2.6, "#fffaf2"),
          C(11, -26, 2.6, "#fffaf2"),
          C(-8, -27, 1.1, "#ffd166"),
          C(2, -29, 1.1, "#ffd166"),
          C(11, -26, 1.1, "#ffd166"),
        ],
      },
    },
    {
      id: "hat-duck", cat: "hat", name: "小黄鸭", from: "单局专注满 1 分钟", ach: "focus-1", price: 6,
      shapes: {
        front: [
          E(0, -29, 9.5, 6.5, "#ffd84d"),
          C(6.5, -35, 5.5, "#ffd84d"),
          P("M11 -36 L18 -34 L11 -32 Z", "#f2994a"),
          C(8, -36, 1.2, "#2b2b2b"),
          E(-1, -31, 5, 2.5, "#ffe98a", { alpha: 0.8 }),
        ],
      },
    },

    {
      id: "hat-grad", cat: "hat", name: "学士帽", from: "青蛙博士 · 累计游玩 30 分钟",
      ach: "doctor-1", shop: false, exclusive: "青蛙博士",
      shapes: {
        front: [
          P("M0 -37 L17 -29 L0 -21 L-17 -29 Z", "#31364a", { stroke: "#22273a", w: 1.3 }),
          R(-9.5, -24, 19, 7, 2.4, "#262b3a"),
          E(0, -19.5, 12, 3.4, "#1d222e"),
          K("M0 -29 L0 -23", "#3c4358", 1.2, { alpha: .8 }),
        ],
      },
    },

    // ===== 面饰（补充） =====
    {
      id: "face-black", cat: "face", name: "学霸黑框镜", from: "单局专注满 5 分钟", ach: "focus-3", price: 6,
      shapes: {
        front: [
          R(-25, -20, 21, 16, 4, "rgba(255,255,255,.12)", { stroke: "#2b2b2b", w: 2.4 }),
          R(4, -20, 21, 16, 4, "rgba(255,255,255,.12)", { stroke: "#2b2b2b", w: 2.4 }),
          R(-4.5, -14, 9, 3, 1.5, "#2b2b2b"),
          L(-25, -16, -28, -18, "#2b2b2b", 2.2),
          L(25, -16, 28, -18, "#2b2b2b", 2.2),
        ],
      },
    },
    {
      id: "face-blush", cat: "face", name: "粉心腮红", from: "连续打卡 15 天", ach: "spirit-4", price: 5,
      shapes: {
        front: [
          E(-19, 2, 6.2, 3.8, "rgba(255,179,193,.55)"),
          E(19, 2, 6.2, 3.8, "rgba(255,179,193,.55)"),
          P("M-19 0 C-22 -3 -25 -0.5 -22 2 L-19 5 L-16 2 C-13 -0.5 -16 -3 -19 0 Z", "#ff8fa8", { alpha: 0.88 }),
          P("M19 0 C22 -3 25 -0.5 22 2 L19 5 L16 2 C13 -0.5 16 -3 19 0 Z", "#ff8fa8", { alpha: 0.88 }),
        ],
      },
    },
    {
      id: "face-mustache", cat: "face", name: "俏皮八字胡", from: "累计专注满 30 分钟", ach: "doctor-1", price: 5,
      shapes: {
        front: [
          P("M0 1 Q-6 -4 -11 1 Q-6 2.5 0 3.5 Z", "#2f2f2f"),
          P("M0 1 Q6 -4 11 1 Q6 2.5 0 3.5 Z", "#2f2f2f"),
        ],
      },
    },

    {
      id: "face-monocle", cat: "face", name: "单片眼镜", from: "专注小达人 · 单局专注满 3 分钟",
      ach: "focus-2", shop: false, exclusive: "专注小达人",
      shapes: {
        front: [
          C(14, -12, 10.5, "rgba(255,255,255,.20)", { stroke: "#d9a441", w: 2.9 }),
          C(14, -12, 10.5, "none", { stroke: "#f8e0ac", w: 1.1, alpha: .85 }),
          K("M7 -16 Q10 -18.5 13 -18", "#ffffff", 2, { alpha: .6 }),
          L(23.6, -9.4, 26.4, -6.2, "#d9a441", 1.8),
          C(26.4, -6.2, 1.5, "#e8b45c"),
          K("M27 -5 Q25 4 19.5 10 Q16 14 13.5 18", "#d9a441", 1.4),
          C(13.5, 18, 1.7, "#e8b45c"),
          K("M15.6 -22 Q19 -24 23 -22", "#d9a441", 1.6, { alpha: .55 }),
        ],
      },
    },

    // ===== 胸饰 =====
    {
      id: "chest-flower", cat: "chest", name: "小红花", from: "池塘小卫士 · 第一次校准成功",
      ach: "guardian-first", shop: false, exclusive: "池塘小卫士",
      shapes: {
        front: [
          L(9.4, 9.4, 7.6, 5.2, "#3da45c", 1.6),
          C(12, 8.8, 2.8, "#e14b4b"),
          C(8.4, 11.6, 2.8, "#e14b4b"),
          C(15.6, 11.6, 2.8, "#e14b4b"),
          C(9.4, 15.2, 2.8, "#e14b4b"),
          C(14.6, 15.2, 2.8, "#e14b4b"),
          C(12, 12.6, 2.3, "#ffd166"),
          C(11.2, 11.8, 0.8, "#fff3c4"),
          E(6.4, 8.2, 2.6, 1.2, "#4fae67", { rot: -0.7 }),
        ],
      },
    },
    // 上架胸饰：都别在左胸同一位置（约 x 13.5 / y 11.5），大小控制在圆徽章
    // 5–6 半径内，既压得住肚皮又不遮嘴；价格 5–12 分，比背饰 / 光效轻一档
    {
      id: "chest-lotus", cat: "chest", name: "荷叶胸针", from: "单局专注满 1 分钟", ach: "focus-1", price: 5,
      shapes: {
        front: [
          P("M19.01 10.53 A5.6 5.6 0 1 0 19.01 12.47 L13.5 11.5 Z",
            "#4fae67", { stroke: "#2f8a4d", w: 1.5 }),
          P("M17.83 10.74 A4.4 4.4 0 1 0 17.83 12.26 L13.5 11.5 Z", "#a9d49a"),
          L(13.5, 11.5, 13.5, 7.5, "#2f8a4d", 1.05, { alpha: 0.6 }),
          L(13.5, 11.5, 10.4, 8.4, "#2f8a4d", 1.05, { alpha: 0.55 }),
          L(13.5, 11.5, 9.8, 13.8, "#2f8a4d", 1.05, { alpha: 0.55 }),
          L(13.5, 11.5, 13.5, 15.4, "#2f8a4d", 1.05, { alpha: 0.6 }),
          L(13.5, 11.5, 16.4, 14.4, "#2f8a4d", 1.05, { alpha: 0.5 }),
          C(11.4, 9.5, 1.2, "#eaf9ff", { stroke: "#4fa9c4", w: 0.8 }),
          C(11.05, 9.15, 0.44, "#ffffff"),
          R(12.1, 4.8, 2.8, 1.4, 0.7, "#e6eef0", { stroke: "#b9cbd2", w: 0.7 }),
          K("M10 8.4 Q13.5 6 17 8.4", "#ffffff", 1.3, { alpha: 0.55 }),
        ],
      },
    },
    {
      id: "chest-dew", cat: "chest", name: "露珠胸针", from: "单局专注满 3 分钟", ach: "focus-2", price: 7,
      shapes: {
        front: [
          C(13.5, 5.6, 1.25, "none", { stroke: "#e0a34a", w: 1.5 }),
          P("M13.5 6.6 C13.5 6.6 18.2 11.4 18.2 14 C18.2 16.7 16.1 18.6 13.5 18.6 " +
            "C10.9 18.6 8.8 16.7 8.8 14 C8.8 11.4 13.5 6.6 13.5 6.6 Z",
            "#8fd8ea", { stroke: "#4fa9c4", w: 1.4 }),
          E(13.5, 14.6, 3.1, 2.9, "rgba(255,255,255,.38)"),
          K("M10.9 12.6 Q11.3 10.5 13.1 9.5", "#ffffff", 1.4, { alpha: 0.85 }),
          E(13.5, 16.4, 1.7, 0.75, "#ffffff", { alpha: 0.5 }),
          L(13.5, 18.7, 13.5, 19.7, "#e0a34a", 1.2),
          C(13.5, 19.9, 0.85, "#f0c46a", { stroke: "#d9a441", w: 0.6 }),
        ],
      },
    },
    {
      id: "chest-star", cat: "chest", name: "专注星章", from: "单局专注满 10 分钟", ach: "focus-4", price: 10,
      shapes: {
        front: [
          P("M11.6 16.4 L9.9 20.2 L11.6 19.3 L12.8 20.4 Z", "#58b6d4"),
          P("M15.4 16.4 L17.1 20.2 L15.4 19.3 L14.2 20.4 Z", "#4fa9c4"),
          P(starPath(13.5, 11.8, 6.4), "#f0c46a", { stroke: "#b8860b", w: 1.4 }),
          C(13.5, 11.8, 4.4, "#fff3c4", { stroke: "#d9a441", w: 1.2 }),
          P(starPath(13.5, 11.8, 3.3), "#f0a94e"),
          P(starPath(13.5, 11.8, 1.5), "#fff6d6", { alpha: 0.85 }),
          P(starPath(6.3, 6.6, 1.3), "#ffd166"),
          P(starPath(20.7, 6.6, 1.3), "#ffd166"),
        ],
      },
    },
    {
      id: "chest-ripple", cat: "chest", name: "池塘守护徽章", from: "池塘守护神 I · 连续打卡 3 天", ach: "spirit-1", shop: false, exclusive: "池塘守护神 I",
      shapes: {
        front: [
          C(13.5, 11.6, 5.8, "#3f8fa8", { stroke: "#2f7285", w: 1.5 }),
          C(13.5, 11.6, 4.8, "#8fd8ea"),
          K("M9.4 10.2 Q10.8 8.9 12.2 10.2 Q13.6 11.5 15 10.2 Q16.4 8.9 17.6 10.2",
            "#2f7285", 1.15, { alpha: 0.5 }),
          K("M9.4 13 Q10.8 11.7 12.2 13 Q13.6 14.3 15 13 Q16.4 11.7 17.6 13",
            "#4fa9c4", 1.05, { alpha: 0.55 }),
          E(13.5, 15.5, 2.5, 1.2, "#4fae67", { stroke: "#3da45c", w: 0.8 }),
          K("M13.5 15.5 L13.5 14.7", "#3da45c", 1, { alpha: 0.85 }),
          K("M9.9 8.7 Q13.5 6.1 17.1 8.7", "#ffffff", 1.2, { alpha: 0.6 }),
        ],
      },
    },

    // ===== 颈饰（补充） =====
    {
      id: "neck-ripple", cat: "neck", name: "水波纹领结", from: "初始拥有", ach: null,
      shapes: {
        front: [
          P("M0 14 L-14 7 Q-17.5 14 -14 21 Z", "rgba(143,216,234,.72)", { stroke: "#58b6d4", w: 1.3 }),
          P("M0 14 L14 7 Q17.5 14 14 21 Z", "rgba(143,216,234,.72)", { stroke: "#58b6d4", w: 1.3 }),
          C(0, 14, 3.6, "#8fd8ea", { stroke: "#58b6d4", w: 1 }),
          K("M-10 11 Q-12 14 -10 17", "#ffffff", 1.4, { alpha: 0.6 }),
          K("M10 11 Q12 14 10 17", "#ffffff", 1.4, { alpha: 0.6 }),
        ],
      },
    },
    {
      id: "neck-rainbow", cat: "neck", name: "彩虹小围巾", from: "单局专注满 10 分钟", ach: "focus-4", price: 8,
      shapes: {
        front: [
          P("M-17 9 Q0 19 17 9 L17 14 Q0 24 -17 14 Z", "#ffd166"),
          P("M-17 9 Q0 19 17 9 L17 10.6 Q0 20.6 -17 10.6 Z", "#ff8f8f"),
          P("M-17 13 Q0 23 17 13 L17 14.6 Q0 24.6 -17 14.6 Z", "#6fd08c"),
          P("M9 17 Q15 25 11 31 Q6 26 5 19 Z", "#8fd8ea"),
          K("M10 20 Q14 25 12 29", "#ff8f8f", 2),
        ],
      },
    },
    {
      id: "neck-cape", cat: "neck", name: "荷叶小斗篷", from: "累计专注满 300 分钟", ach: "doctor-4", price: 7,
      shapes: {
        front: [
          P("M-24 6 Q0 22 24 6 Q17 -2 0 -2 Q-17 -2 -24 6 Z", "#4fae67", { stroke: "#3da45c", w: 1.2 }),
          K("M0 -1 L0 18", "#3da45c", 1.2, { alpha: 0.4 }),
          K("M-12 1 L-16 13", "#3da45c", 1.2, { alpha: 0.35 }),
          K("M12 1 L16 13", "#3da45c", 1.2, { alpha: 0.35 }),
        ],
      },
    },
    {
      id: "neck-scarfred", cat: "neck", name: "红领巾", from: "连续打卡 30 天", ach: "spirit-5", price: 6,
      shapes: {
        front: [
          P("M-13 9 Q0 15 13 9 L7 20 L0 25 L-7 20 Z", "#e14b4b", { stroke: "#c93c3c", w: 1.2 }),
          C(0, 12, 2.6, "#ffd166"),
          L(-2, 14, 0, 22, "#ffd166", 1.4),
        ],
      },
    },

    // ===== 手持（新类别） =====
    {
      id: "hand-wand", cat: "hand", name: "星星魔法棒", from: "累计专注满 600 分钟", ach: "doctor-5", price: 12,
      shapes: {
        front: [
          L(24, 20, 30, 2, "#c98f2e", 2.6),
          C(31, 0, 8, "#ffe9a8", { alpha: 0.32 }),
          P(starPath(31, 0, 5.5), "#ffd166"),
          P(starPath(31, 0, 2.4), "#fff6d6"),
        ],
      },
    },
    {
      id: "hand-gun", cat: "hand", name: "迷你水枪", from: "单局专注满 3 分钟", ach: "focus-2", price: 7,
      shapes: {
        front: [
          R(23, 9, 13, 7, 3, "#5aa6d8"),
          R(35, 11, 6, 4, 2, "#3d8fbf"),
          R(25, 16, 5, 9, 2, "#4a97c8"),
          C(26, 8, 2.6, "rgba(205,238,247,.9)", { stroke: "#8fd0e0", w: 1 }),
          K("M27 11 L31 11", "#cdeef7", 1.4),
        ],
      },
    },
    {
      id: "hand-flag", cat: "hand", name: "Focus 小红旗", from: "第一次校准成功", ach: "guardian-first", price: 5,
      shapes: {
        front: [
          L(27, 22, 27, -10, "#b07a3a", 2.2),
          P("M27 -8 L45 -4 L27 1 Z", "#e14b4b"),
          K("M30 -5 L40 -4", "#fff6f6", 1.6, { alpha: 0.85 }),
        ],
      },
    },
    {
      id: "hand-umbrella", cat: "hand", name: "荷叶小伞", from: "连续打卡 3 天", ach: "spirit-1", price: 8,
      shapes: {
        front: [
          L(29, 20, 29, -2, "#7fbf8f", 2.2),
          E(29, -4, 14, 5.5, "#4fae67", { stroke: "#3da45c", w: 1.2 }),
          K("M29 -4 L18 -6", "#3da45c", 1.1, { alpha: 0.4 }),
          K("M29 -4 L40 -6", "#3da45c", 1.1, { alpha: 0.4 }),
          C(29, -1, 1.8, "#3da45c"),
        ],
      },
    },

    {
      id: "hand-scepter", cat: "hand", name: "守护权杖", from: "池塘守护神 IV · 连续打卡 15 天",
      ach: "spirit-4", shop: false, exclusive: "池塘守护神",
      shapes: {
        front: [
          L(27, 27, 27, -13, "#c9a227", 3),
          L(27, 27, 27, -13, "#f0c46a", 1.2),
          C(27, -18, 9, "rgba(255,233,168,.26)"),
          C(27, -18, 5.8, "#f0c46a", { stroke: "#c9a227", w: 1.5 }),
          P(starPath(27, -18, 2.6), "#fff6d6"),
          P("M21.6 -22.6 Q27 -29 32.4 -22.6", "none", { stroke: "#f0c46a", w: 1.9 }),
          C(27, -25.4, 1.6, "#ffe9a8"),
          C(27, -25.4, 1.6, "#ffe9a8", { alpha: .8 }),
          E(27, 27, 4.4, 1.6, "#c9a227", { alpha: .8 }),
        ],
      },
    },

    // ===== 光效（新类别，颜色可选） =====
    {
      id: "aura-glow", cat: "aura", name: "荷叶光晕", from: "累计专注满 30 分钟", ach: "doctor-1", price: 13,
      tone: "glow",
      shapes: {
        back: [
          E(0, 31, 28, 8, "@0", { alpha: 0.22 }),
          E(0, 31, 26, 7.2, "none", { stroke: "@1", w: 2.8, alpha: 0.95 }),
          E(0, 31, 20, 5.2, "none", { stroke: "@2", w: 1.4, alpha: 0.55 }),
        ],
      },
    },
    {
      id: "aura-trail", cat: "aura", name: "星星尾迹", from: "连续打卡 15 天", ach: "spirit-4", price: 15,
      tone: "trail",
      shapes: {
        front: [
          P(starPath(26, -26, 5), "@0"),
          P(starPath(32, -16, 3.2), "@1"),
          P(starPath(20, -34, 2.4), "@2"),
        ],
      },
    },
    {
      id: "aura-halo", cat: "hat", name: "头顶光环", from: "池塘守护神 II · 连续打卡 5 天",
      ach: "spirit-2", shop: false, exclusive: "池塘守护神",
      shapes: {
        front: [
          E(0, -44, 16, 4.6, "rgba(255,233,168,.16)"),
          E(0, -44, 15, 4.2, "none", { stroke: "#ffe9a8", w: 2.6, alpha: .95 }),
          E(0, -44, 11, 2.8, "none", { stroke: "#fff6d6", w: 1.2, alpha: .85 }),
          C(-13.5, -45.6, 1.6, "#fff6d6", { alpha: .9 }),
          C(13.5, -45.6, 1.6, "#fff6d6", { alpha: .9 }),
        ],
      },
    },
    {
      id: "aura-divine", cat: "aura", name: "守护神光焰", from: "池塘守护神 V · 连续打卡 30 天",
      ach: "spirit-5", shop: false, exclusive: "池塘守护神",
      shapes: {
        back: [
          E(0, -4, 27, 42, "rgba(255,224,150,.10)"),
          E(0, 31, 35, 10.5, "rgba(255,214,120,.20)"),
          E(0, 31, 30, 8.4, "none", { stroke: "#ffd166", w: 3, alpha: .95 }),
          E(0, 31, 21.5, 5.8, "none", { stroke: "#fff2c4", w: 1.6, alpha: .75 }),
          P(starPath(-24, -15, 3), "#ffe9a8"),
          P(starPath(23, -24, 2.4), "#fff6d6"),
          P(starPath(-15, -38, 2.2), "#ffd166"),
          P(starPath(17, -41, 1.8), "#ffe9a8", { alpha: .85 }),
        ],
        front: [
          P(starPath(28, 5, 3), "#fff2c4", { alpha: .9 }),
          P(starPath(-27, 2, 2.2), "#ffe9a8", { alpha: .9 }),
        ],
      },
    },
  ];

  const BY_ID = {};
  ITEMS.forEach(item => { BY_ID[item.id] = item; });

  // ---------- 肤色 ----------
  // 原始青蛙的三层配色；没有穿肤色时就用它
  const BASE_SKIN = { deep: "#346951", body: "#609b68", belly: "#b9cf94" };
  // 几何里各层原本的颜色 → 对应肤色的哪一层，替换时按这个映射走
  const SKIN_SLOTS = { "#346951": "deep", "#609b68": "body", "#b9cf94": "belly" };

  function skinOf(set) {
    const source = set || wearing;
    // 单项预览（例如只看一顶帽子）没有皮肤字段时，沿用当前穿戴的肤色
    const id = Object.prototype.hasOwnProperty.call(source, "skin") ? source.skin : wearing.skin;
    const item = BY_ID[id];
    return (item && item.skin) ? item.skin : BASE_SKIN;
  }

  // 用当前（或指定搭配的）肤色重绘青蛙本体的椭圆；source 默认取共享几何
  function skinEllipses(set, source) {
    const skin = skinOf(set);
    return (source || frogEllipses()).map(([cx, cy, rx, ry, fill]) => {
      const slot = SKIN_SLOTS[String(fill).toLowerCase()];
      return [cx, cy, rx, ry, slot ? skin[slot] : fill];
    });
  }

  function skinMouth(set) {
    const mouth = frogMouth();
    return Object.assign({}, mouth, { color: skinOf(set).deep });
  }


  // ---------- 青蛙本体：与 PondEffects 共用同一份几何 ----------
  const FROG_FALLBACK = [
    [0, 17, 29, 9, "#346951"],
    [0, 7, 24, 22, "#609b68"],
    [0, 13, 16, 13, "#b9cf94"],
    ...[-14, 14].flatMap(x => [
      [x, -12, 10, 11, "#609b68"],
      [x, -12, 6, 7, "#fbf3d9"],
      [x + 1, -12, 3, 4, "#263b33"],
    ]),
  ];
  const FROG_MOUTH_FALLBACK = { start: [-8, 5], curve: [0, 10, 8, 5], color: "#346951", width: 2 };

  function frogEllipses() {
    const shared = window.PondEffects && window.PondEffects.frogEllipses;
    return Array.isArray(shared) && shared.length ? shared : FROG_FALLBACK;
  }
  function frogMouth() {
    const shared = window.PondEffects && window.PondEffects.frogMouth;
    return shared && shared.start ? shared : FROG_MOUTH_FALLBACK;
  }

  // ---------- 读写穿搭 ----------
  function blankWear() {
    const out = {};
    CATS.forEach(cat => { out[cat.id] = null; });
    return out;
  }

  let wearing = blankWear();
  let unlocked = new Set();
  let auraColors = { glow: "gold", trail: "orange" };
  // 在商城买下的装扮（与成就解锁相互独立，成就重置不会没收已购装扮）
  let ownedShop = new Set();
  // 记录每件装扮的获得时间（毫秒时间戳），成就解锁的时间从 Achievements 读取
  let ownedAt = {};

  function readOwned() {
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(OWNED_KEY)); } catch (_) { raw = null; }
    const list = Array.isArray(raw) ? raw : (raw && Array.isArray(raw.ids) ? raw.ids : []);
    ownedShop = new Set(list.filter(id => typeof id === "string" && BY_ID[id]));

    let times = null;
    try { times = JSON.parse(localStorage.getItem(OWNED_AT_KEY)); } catch (_) { times = null; }
    ownedAt = {};
    if (times && typeof times === "object" && !Array.isArray(times)) {
      Object.keys(times).forEach(id => {
        const ts = Number(times[id]);
        // 只接受合理的时间戳，避免旧数据里的布尔标记被当成时间
        if (BY_ID[id] && ts >= 1e12) ownedAt[id] = ts;
      });
    }
  }

  function saveOwned() {
    try {
      localStorage.setItem(OWNED_KEY, JSON.stringify([...ownedShop]));
    } catch (_) { /* 隐私模式忽略 */ }
    try {
      localStorage.setItem(OWNED_AT_KEY, JSON.stringify(ownedAt));
    } catch (_) { /* 隐私模式忽略 */ }
  }

  function readWear() {
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(STORE_KEY)) || null; } catch (_) { raw = null; }
    const next = blankWear();
    auraColors = { glow: "gold", trail: "orange" };
    if (!raw || typeof raw !== "object") return next;
    CATS.forEach(cat => {
      const id = raw[cat.id];
      if (typeof id === "string" && BY_ID[id] && BY_ID[id].cat === cat.id) next[cat.id] = id;
    });
    if (raw.colors && typeof raw.colors === "object") {
      Object.keys(auraColors).forEach(kind => {
        const picked = raw.colors[kind];
        if (typeof picked === "string" && AURA_PALETTES[kind].some(opt => opt.id === picked)) {
          auraColors[kind] = picked;
        }
      });
    }
    return next;
  }

  function saveWear() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(Object.assign({}, wearing, { colors: auraColors })));
    } catch (_) { /* 隐私模式忽略 */ }
  }

  // 光效颜色：形状里用 @0/@1/@2 占位，渲染时按当前配色替换
  function tonePalette(item) {
    if (!item || !item.tone) return null;
    const list = AURA_PALETTES[item.tone];
    const picked = list.find(opt => opt.id === auraColors[item.tone]) || list[0];
    return picked.colors;
  }

  function toneColor(raw, item) {
    if (typeof raw !== "string" || raw.charAt(0) !== "@") return raw;
    const palette = tonePalette(item);
    if (!palette) return "#ffd166";
    const idx = Number(raw.slice(1)) || 0;
    return palette[idx % palette.length];
  }

  function refreshUnlocked() {
    let list = [];
    try {
      if (window.Achievements && typeof window.Achievements.status === "function") {
        list = window.Achievements.status().unlocked || [];
      }
    } catch (_) { list = []; }
    unlocked = new Set(list);
    // 成就被重置后，已经失效的装扮要自动摘下来
    let changed = false;
    CATS.forEach(cat => {
      const id = wearing[cat.id];
      if (id && !isOwned(BY_ID[id])) { wearing[cat.id] = null; changed = true; }
    });
    if (changed) saveWear();
  }

  function isOwned(item) {
    if (!item) return false;
    if (ownedShop.has(item.id)) return true;   // 商城买下
    if (!item.ach) return true;                // 初始拥有
    return unlocked.has(item.ach);             // 成就解锁
  }

  // ---------- 获得时间 ----------
  function pad2(n) { return String(n).padStart(2, "0"); }

  function formatStamp(ts) {
    const d = new Date(Number(ts));
    if (!d || isNaN(d.getTime())) return "";
    return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate()) +
      " " + pad2(d.getHours()) + ":" + pad2(d.getMinutes());
  }

  // 优先用商城购买时记录的时间；成就解锁的装扮用成就解锁时间
  function acquiredAt(item) {
    if (!item) return 0;
    if (ownedAt[item.id]) return ownedAt[item.id];
    if (!item.ach) return 0;
    try {
      const status = window.Achievements && typeof window.Achievements.status === "function"
        ? window.Achievements.status()
        : null;
      const ts = status && status.unlockedAt ? Number(status.unlockedAt[item.ach]) : 0;
      if (ts >= 1e12) return ts;
    } catch (_) { /* 忽略 */ }
    return 0;
  }

  function acquiredText(item) {
    if (!isOwned(item)) return "尚未获得";
    if (!item.ach && !ownedAt[item.id]) return "初始拥有";
    const ts = acquiredAt(item);
    return ts ? formatStamp(ts) : "未记录（获得时间记录上线前取得）";
  }

  // ---------- 商城 ----------
  // 只有「成就专属」不可购买；其余（含成就可免费解锁的）都能用积分买
  // 定价倍率：肤色 ×1.5，背饰 / 头饰 ×1.2，手持 ×1.1，其余分类按原价。
  // 实际售价 = 原价 × 倍率 后向上取整；乘完先按 6 位小数归整，
  // 避免浮点误差把 10 × 1.2 = 12.000000000000002 误进成 13 分。
  const PRICE_MULT = {
    skin: 1.5,
    back: 1.2,
    hat: 1.2,
    hand: 1.1,
  };

  function priceOf(item) {
    const data = typeof item === "string" ? BY_ID[item] : item;
    if (!data || data.shop === false) return 0;
    const base = Math.max(0, Number(data.price) || 0);
    if (!base) return 0;
    const mult = PRICE_MULT[data.cat] || 1;
    if (mult === 1) return Math.round(base);
    const scaled = Number((base * mult).toFixed(6));
    return Math.max(0, Math.ceil(scaled));
  }

  function shopItems() {
    return ITEMS.filter(item => item.shop !== false).map(item => ({
      id: item.id,
      name: item.name,
      cat: item.cat,
      catName: (CATS.find(c => c.id === item.cat) || {}).name || "",
      price: priceOf(item),
      owned: isOwned(item),
      // 初始拥有 / 成就也能白拿 → 商城不是唯一途径
      freeByAch: !!item.ach,
      from: item.from,
    }));
  }

  function exclusiveItems() {
    return ITEMS.filter(item => item.shop === false).map(item => ({
      id: item.id,
      name: item.name,
      cat: item.cat,
      from: item.from,
      owned: isOwned(item),
      exclusive: item.exclusive || "",
    }));
  }

  function buy(id) {
    const item = BY_ID[id];
    if (!item) return { ok: false, reason: "missing" };
    if (item.shop === false) return { ok: false, reason: "exclusive", name: item.name };
    if (isOwned(item)) return { ok: false, reason: "owned", name: item.name };
    const price = priceOf(item);
    if (!price) return { ok: false, reason: "noprice", name: item.name };
    if (!window.Wallet) return { ok: false, reason: "wallet" };
    if (window.Wallet.points() < price) {
      return { ok: false, reason: "poor", price: price, points: window.Wallet.points(), name: item.name };
    }
    if (!window.Wallet.spend(price)) {
      return { ok: false, reason: "poor", price: price, points: window.Wallet.points(), name: item.name };
    }
    ownedShop.add(item.id);
    ownedAt[item.id] = Date.now();
    saveOwned();
    if (mask && !mask.classList.contains("hidden")) {
      if (tab === "book") renderBook();
      else renderWear();
    }
    return { ok: true, price: price, name: item.name, points: window.Wallet.points() };
  }

  // 学士帽的华丽度跟着「青蛙博士」等级走（doctor-1..5 解锁数）
  function doctorTier() {
    let n = 0;
    for (let i = 1; i <= 5; i++) if (unlocked.has("doctor-" + i)) n++;
    return n;
  }

  // 学士帽在基础形状之上叠加装饰：等级越高，流苏、金边、星徽越多
  function gradExtra(tier) {
    const out = [];
    out.push(L(6.4, -33.6, 12, -21, "#e0b24e", 1.8));
    out.push(C(12, -20.4, 2, "#e0b24e"));
    if (tier >= 2) {
      out.push(C(12, -20.4, 3.2, "none", { stroke: "#fff0c2", w: 1, alpha: .9 }));
      out.push(L(0, -34, 6.4, -33.6, "#e0b24e", 1.6));
    }
    if (tier >= 3) {
      out.push(P("M-17 -29 L0 -21 L17 -29", "none", { stroke: "#e0b24e", w: 1.5, alpha: .95 }));
      out.push(K("M-9 -24 L9 -24", "#e0b24e", 1.2, { alpha: .75 }));
      out.push(C(-13.5, -26.4, 1.4, "#ffd166"));
      out.push(C(13.5, -26.4, 1.4, "#ffd166"));
    }
    if (tier >= 4) {
      out.push(P(starPath(-11, -28.2, 2.6), "#ffd166"));
      out.push(P(starPath(11, -28.2, 2.6), "#ffd166"));
    }
    if (tier >= 5) {
      out.push(P(starPath(0, -40, 3.4), "#ffe9a8"));
      out.push(E(0, -37.4, 8.6, 2.1, "none", { stroke: "#f0c46a", w: 1.2, alpha: .85 }));
      out.push(C(-6.2, -25.4, 1.2, "#fff6d6"));
      out.push(C(6.2, -25.4, 1.2, "#fff6d6"));
    }
    return out;
  }

  // 统一取某一层的形状：学士帽把等级装饰追加进来
  function shapesFor(item, layer) {
    const list = ((item.shapes && item.shapes[layer]) || []).slice();
    if (item.id === "hat-grad" && layer === "front") {
      const tier = Math.max(1, doctorTier());
      gradExtra(tier).forEach(sh => list.push(sh));
    }
    return list;
  }

  function equippedCount() {
    // 肤色是底色不算配饰件数，避免"默认肤色 / 已换色"时数字跳动
    return CATS.reduce((n, cat) => n + (cat.id !== "skin" && wearing[cat.id] ? 1 : 0), 0);
  }

  function ownedCount() {
    return ITEMS.reduce((n, item) => n + (isOwned(item) ? 1 : 0), 0);
  }

  // ---------- 渲染：SVG ----------
  function svgShape(sh, item) {
    const fill = toneColor(sh.fill, item);
    const strokeColor = toneColor(sh.stroke, item);
    const op = sh.alpha != null ? ` opacity="${sh.alpha}"` : "";
    const rot = sh.rot ? ` transform="rotate(${(sh.rot * 180 / Math.PI).toFixed(2)} ${sh.x || 0} ${sh.y || 0})"` : "";
    const stroke = strokeColor
      ? ` stroke="${strokeColor}" stroke-width="${sh.w || 1.6}" stroke-linecap="round" stroke-linejoin="round"`
      : "";
    switch (sh.s) {
      case "ellipse":
        return `<ellipse cx="${sh.x}" cy="${sh.y}" rx="${sh.rx}" ry="${sh.ry}" fill="${fill}"${stroke}${op}${rot}/>`;
      case "circle":
        return `<circle cx="${sh.x}" cy="${sh.y}" r="${sh.r}" fill="${fill}"${stroke}${op}${rot}/>`;
      case "rect":
        return `<rect x="${sh.x}" y="${sh.y}" width="${sh.w}" height="${sh.h}" rx="${sh.r || 0}" fill="${fill}"${stroke}${op}${rot}/>`;
      case "line":
        return `<line x1="${sh.x1}" y1="${sh.y1}" x2="${sh.x2}" y2="${sh.y2}" fill="none"${stroke}${op}${rot}/>`;
      case "path":
        return `<path d="${sh.d}" fill="${fill || "none"}"${stroke}${op}${rot}/>`;
      default:
        return "";
    }
  }

  function frogBodySvg(set) {
    const ellipses = skinEllipses(set).map(([cx, cy, rx, ry, fill]) =>
      `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="${fill}"/>`
    ).join("");
    const mouth = skinMouth(set);
    return ellipses +
      `<path d="M ${mouth.start.join(" ")} Q ${mouth.curve.join(" ")}" fill="none" stroke="${mouth.color}" stroke-width="${mouth.width}"/>`;
  }

  // 预览用小蛙：outfit 形如 { hat: "hat-crown" }
  function frogSvg(outfit) {
    const set = outfit || wearing;
    const back = [];
    const front = [];
    CATS.forEach(cat => {
      const item = BY_ID[set[cat.id]];
      if (!item) return;
      shapesFor(item, "back").forEach(sh => back.push(svgShape(sh, item)));
      shapesFor(item, "front").forEach(sh => front.push(svgShape(sh, item)));
    });
    return `<svg class="dress-frog" viewBox="-44 -50 88 92" aria-hidden="true" focusable="false">` +
      back.join("") + frogBodySvg(set) + front.join("") + `</svg>`;
  }

  // ---------- 渲染：Canvas（游戏页） ----------
  function roundRectPath(ctx, sh) {
    const r = Math.min(sh.r || 0, sh.w / 2, sh.h / 2);
    const { x, y, w, h } = sh;
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  function paintShape(ctx, sh, item) {
    const fill = toneColor(sh.fill, item);
    const strokeColor = toneColor(sh.stroke, item);
    ctx.save();
    if (sh.alpha != null) ctx.globalAlpha *= sh.alpha;
    if (sh.rot) {
      const cx = sh.x || 0, cy = sh.y || 0;
      ctx.translate(cx, cy);
      ctx.rotate(sh.rot);
      ctx.translate(-cx, -cy);
    }
    let path = null;
    if (sh.s === "ellipse") {
      ctx.beginPath();
      ctx.ellipse(sh.x, sh.y, sh.rx, sh.ry, 0, 0, TAU);
    } else if (sh.s === "circle") {
      ctx.beginPath();
      ctx.arc(sh.x, sh.y, sh.r, 0, TAU);
    } else if (sh.s === "rect") {
      roundRectPath(ctx, sh);
    } else if (sh.s === "line") {
      ctx.beginPath();
      ctx.moveTo(sh.x1, sh.y1);
      ctx.lineTo(sh.x2, sh.y2);
    } else if (sh.s === "path") {
      try { path = new Path2D(sh.d); } catch (_) { path = null; }
    }
    if (sh.s === "line" || (sh.s === "path" && !path)) {
      if (strokeColor) {
        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = sh.w || 1.6;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.stroke();
      }
    } else {
      const target = path || null;
      if (fill && fill !== "none") {
        ctx.fillStyle = fill;
        if (target) ctx.fill(target); else ctx.fill();
      }
      if (strokeColor) {
        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = sh.w || 1.6;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        if (target) ctx.stroke(target); else ctx.stroke();
      }
    }
    ctx.restore();
  }

  // 在已 translate 到青蛙中心的上下文里调用
  // outfit 可选：传入 { hat: "hat-crown" } 可直接预览任意搭配，默认用当前穿搭
  function drawCanvas(ctx, layer, t, outfit) {
    const set = outfit || wearing;
    CATS.forEach(cat => {
      const item = BY_ID[set[cat.id]];
      if (!item) return;
      const shapes = shapesFor(item, layer);
      if (!shapes.length) return;
      // 尾迹的星星只在图鉴/装扮预览里静态展示，游戏内由 drawTrail 生成
      if (item.id === "aura-trail" && layer === "front") return;
      if (item.id === "back-wing" && layer === "back") {
        ctx.save();
        ctx.rotate(Math.sin((t || 0) * 7) * 0.045);
        shapes.forEach(sh => paintShape(ctx, sh, item));
        ctx.restore();
        return;
      }
      shapes.forEach(sh => paintShape(ctx, sh, item));
    });
  }

  // ---------- 跳跃尾迹（世界坐标，游戏页调用） ----------
  let trailParticles = [];
  let trailClock = 0;

  function drawTrail(ctx, t, x, y, jumping) {
    const item = BY_ID[wearing.aura];
    if (!item || item.id !== "aura-trail") {
      if (trailParticles.length) trailParticles.length = 0;
      return;
    }
    const palette = tonePalette(item) || ["#ffd93d"];
    if (jumping && t - trailClock > 0.045) {
      trailClock = t;
      trailParticles.push({
        x: x + (Math.random() - 0.5) * 12,
        y: y + (Math.random() - 0.5) * 10,
        born: t,
        life: 0.85,
        size: 2.2 + Math.random() * 2.4,
        rot: Math.random() * Math.PI,
        color: palette[Math.floor(Math.random() * palette.length)],
      });
      if (trailParticles.length > 80) trailParticles.shift();
    }
    if (!trailParticles.length) return;
    trailParticles = trailParticles.filter(p => t - p.born < p.life);
    trailParticles.forEach(p => {
      const k = Math.max(0, (t - p.born) / p.life);
      ctx.save();
      ctx.globalAlpha = 1 - k;
      ctx.fillStyle = p.color;
      ctx.translate(p.x, p.y - k * 20);
      ctx.rotate(p.rot + k * 1.8);
      ctx.scale(1 - k * 0.45, 1 - k * 0.45);
      try {
        ctx.fill(new Path2D(starPath(0, 0, p.size)));
      } catch (_) {
        ctx.beginPath();
        ctx.arc(0, 0, p.size, 0, TAU);
        ctx.fill();
      }
      ctx.restore();
    });
  }

  // ---------- 首页：把配饰挂到池塘小蛙身上 ----------
  // 青蛙本体的配色也跟着肤色走，和装扮预览保持一致
  function applyHeroSkin() {
    const art = document.getElementById("pondFrogArtwork");
    if (!art) return;
    const parts = skinEllipses().map(([cx, cy, rx, ry, fill]) =>
      `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="${fill}"/>`
    );
    const mouth = skinMouth();
    parts.push(`<path d="M ${mouth.start.join(" ")} Q ${mouth.curve.join(" ")}" ` +
      `fill="none" stroke="${mouth.color}" stroke-width="${mouth.width}"/>`);
    art.innerHTML = parts.join("");
  }

  function applyHeroOutfit() {
    const back = document.getElementById("pondFrogOutfitBack");
    const front = document.getElementById("pondFrogOutfit");
    if (back || front) {
      const backParts = [];
      const frontParts = [];
      CATS.forEach(cat => {
        const item = BY_ID[wearing[cat.id]];
        if (!item) return;
        shapesFor(item, "back").forEach(sh => backParts.push(svgShape(sh, item)));
        shapesFor(item, "front").forEach(sh => frontParts.push(svgShape(sh, item)));
      });
      if (back) back.innerHTML = backParts.join("");
      if (front) front.innerHTML = frontParts.join("");
    }
    applyHeroSkin();
  }

  // ---------- 入口 chip ----------
  let chip = null;
  let chipCount = null;

  function hangerSvg() {
    return `<svg viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <path d="M24 8.5c-3.1 0-5.4 2.3-5.4 5.1 0 2.2 1.3 3.4 2.5 4.3.9.6 1.4 1.1 1.4 2"
            fill="none" stroke="#2f9c93" stroke-width="2.6" stroke-linecap="round"/>
      <path d="M22.4 20.6 10.8 30.2c-1.8 1.4-1 4.3 1.3 4.3h23.8c2.3 0 3.1-2.9 1.3-4.3L25.6 20.6"
            fill="#eafaf5" stroke="#2f9c93" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M16.6 33.4h14.8" stroke="#9fe3d6" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="24" cy="20.6" r="1.6" fill="#2f9c93"/>
    </svg>`;
  }

  function buildChip(entry) {
    entry.innerHTML = `
      <button type="button" class="dress-chip" id="dress-open" aria-haspopup="dialog" aria-label="装扮小屋">
        <span class="dress-chip__badge">${hangerSvg()}</span>
        <span class="dress-chip__meta">
          <span class="dress-chip__title">装扮</span>
          <span class="dress-chip__count" id="dress-chip-count">穿戴 0 件</span>
        </span>
      </button>`;
    chip = entry.querySelector("#dress-open");
    chipCount = entry.querySelector("#dress-chip-count");
    chip.addEventListener("click", openPanel);
    refreshChip();
  }

  function refreshChip() {
    if (chip) {
      const n = equippedCount();
      chipCount.textContent = "穿戴 " + n + " 件";
      chip.setAttribute("aria-label", "装扮小屋，已穿戴 " + n + " 件");
    }
  }

  // ---------- 面板 ----------
  let mask = null;
  let card = null;
  let tab = "wear";
  let lastFocus = null;
  let bookDetailBack = null;
  let toastTimer = 0;

  function buildPanel() {
    mask = document.createElement("div");
    mask.className = "dress-mask hidden";
    mask.id = "dress-mask";
    mask.innerHTML = `
      <div class="dress-card" role="dialog" aria-modal="true" aria-labelledby="dress-title">
        <button type="button" class="dress-close" id="dress-close" aria-label="关闭装扮面板">
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5.5 5.5l9 9M14.5 5.5l-9 9" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>
        </button>
        <div class="dress-head">
          <div class="dress-head__icon">${hangerSvg()}</div>
          <div class="dress-head__text">
            <h2 id="dress-title">装扮小屋</h2>
            <p id="dress-sub">已收集 0 / ${ITEMS.length} 件装扮</p>
          </div>
        </div>
        <div class="dress-tabs" role="tablist" aria-label="装扮面板">
          <button type="button" class="dress-tab is-active" role="tab" data-tab="wear" aria-selected="true">装扮</button>
          <button type="button" class="dress-tab" role="tab" data-tab="book" aria-selected="false">图鉴</button>
        </div>
        <div class="dress-body">
          <section class="dress-panel hidden" data-panel="book">
            <div class="book-bar">
              <p class="book-bar__hint">点击任意装扮可放大查看外观与获得时间；换装请切到「装扮」页。</p>
            </div>
            <div id="book-grid"></div>
          </section>
          <section class="dress-panel" data-panel="wear">
            <div class="wear-layout">
              <div class="wear-stage">
                <span class="wear-stage__cloud wear-stage__cloud--a"></span>
                <span class="wear-stage__cloud wear-stage__cloud--b"></span>
                <span class="wear-stage__lily wear-stage__lily--a"></span>
                <span class="wear-stage__lily wear-stage__lily--b"></span>
                <div class="wear-stage__frog" id="wear-preview"></div>
                <span class="wear-stage__caption" id="wear-caption">素颜小蛙</span>
              </div>
              <div class="wear-slots" id="wear-slots"></div>
            </div>
            <div class="wear-foot">
              <button type="button" class="wear-clear" id="wear-clear">全部卸下</button>
              <p class="wear-foot__hint">每一类只能穿戴一件，点同一件可以取下。</p>
            </div>
          </section>
        </div>
        <div class="book-detail hidden" id="book-detail" role="dialog" aria-modal="true" aria-labelledby="book-detail-name">
          <button type="button" class="book-detail__close" id="book-detail-close" aria-label="关闭装扮详情">
            <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5.5 5.5l9 9M14.5 5.5l-9 9" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>
          </button>
          <div class="book-detail__inner">
            <div class="book-detail__stage">
              <span class="book-detail__glow" aria-hidden="true"></span>
              <div class="book-detail__art" id="book-detail-art"></div>
            </div>
            <div class="book-detail__info">
              <span class="book-detail__cat" id="book-detail-cat"></span>
              <h3 class="book-detail__name" id="book-detail-name"></h3>
              <p class="book-detail__from" id="book-detail-from"></p>
              <dl class="book-detail__meta">
                <div class="book-detail__row">
                  <dt>获得时间</dt>
                  <dd id="book-detail-time"></dd>
                </div>
              </dl>
              <p class="book-detail__status" id="book-detail-status"></p>
              <p class="book-detail__note">图鉴只用来查看外观，想换装请到「装扮」页。</p>
            </div>
          </div>
        </div>
        <p class="dress-foot" id="dress-foot">装扮只保存在这台设备上；穿戴后会立刻出现在首页池塘和游戏里的小蛙身上。</p>
        <div class="dress-toast" id="dress-toast" role="status" aria-live="polite"></div>
      </div>`;
    document.body.appendChild(mask);
    card = mask.querySelector(".dress-card");

    mask.querySelector("#dress-close").addEventListener("click", closePanel);
    mask.addEventListener("click", event => {
      if (event.target === mask) {
        if (isBookDetailOpen()) closeBookDetail();
        else closePanel();
      }
    });
    document.addEventListener("keydown", event => {
      if (event.key !== "Escape" || !mask || mask.classList.contains("hidden")) return;
      // Esc 先关详情，再关面板
      if (isBookDetailOpen()) closeBookDetail();
      else closePanel();
    });

    mask.querySelectorAll(".dress-tab").forEach(btn => {
      btn.addEventListener("click", () => setTab(btn.dataset.tab));
    });

    mask.querySelector("#book-grid").addEventListener("click", onBookClick);
    mask.querySelector("#book-detail-close").addEventListener("click", closeBookDetail);
    mask.querySelector("#wear-slots").addEventListener("click", onWearClick);
    mask.querySelector("#wear-clear").addEventListener("click", clearAll);
  }

  function setTab(next) {
    tab = next;
    closeBookDetail();
    mask.querySelectorAll(".dress-tab").forEach(btn => {
      const active = btn.dataset.tab === next;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    mask.querySelectorAll(".dress-panel").forEach(panel => {
      panel.classList.toggle("hidden", panel.dataset.panel !== next);
    });
    if (next === "book") renderBook();
    else renderWear();
    if (card) card.querySelector(".dress-body").scrollTop = 0;
    updateSub();
  }

  function toast(text) {
    const el = mask && mask.querySelector("#dress-toast");
    if (!el) return;
    el.textContent = text;
    el.classList.add("is-show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("is-show"), 2200);
  }

  function lockedHint(item) {
    const price = priceOf(item);
    if (price) return "「" + item.name + "」还没有获得 · " + item.from + "，或去商城花 " + price + " 积分购买";
    return "「" + item.name + "」还没有获得 · " + item.from + "（成就专属，商城不出售）";
  }

  function onBookClick(event) {
    // 图鉴只看外观：点击放大查看详情，不在这里换装
    const el = event.target.closest(".book-item");
    if (!el) return;
    const data = BY_ID[el.dataset.id];
    if (!data) return;
    openBookDetail(data);
  }

  function isBookDetailOpen() {
    const detail = mask && mask.querySelector("#book-detail");
    return !!detail && !detail.classList.contains("hidden");
  }

  function openBookDetail(data) {
    const detail = mask && mask.querySelector("#book-detail");
    if (!detail) return;
    const wasOpen = isBookDetailOpen();
    if (!wasOpen) bookDetailBack = document.activeElement;

    const owned = isOwned(data);
    const cat = CATS.find(c => c.id === data.cat);
    const price = owned ? 0 : priceOf(data);

    mask.querySelector("#book-detail-art").innerHTML = frogSvg({ [data.cat]: data.id });
    mask.querySelector("#book-detail-cat").textContent = cat ? cat.name : "";
    mask.querySelector("#book-detail-name").textContent = data.name;
    mask.querySelector("#book-detail-from").textContent =
      (owned ? "获取途径 · " : "获得条件 · ") + data.from;
    mask.querySelector("#book-detail-time").textContent = acquiredText(data);

    let status;
    if (!owned) {
      status = price
        ? "未获得 · 可去商城花 " + price + " 积分购买"
        : "未获得 · 成就专属，商城不出售";
    } else if (wearing[data.cat] === data.id) {
      status = "已获得 · 正在穿戴";
    } else {
      status = "已获得 · 未穿戴";
    }
    mask.querySelector("#book-detail-status").textContent = status;

    detail.querySelector(".book-detail__stage").classList.toggle("is-locked", !owned);
    detail.classList.remove("hidden");
    const closeBtn = mask.querySelector("#book-detail-close");
    if (closeBtn) closeBtn.focus({ preventScroll: true });
  }

  function closeBookDetail() {
    const detail = mask && mask.querySelector("#book-detail");
    if (!detail || detail.classList.contains("hidden")) return;
    detail.classList.add("hidden");
    if (bookDetailBack && typeof bookDetailBack.focus === "function") {
      bookDetailBack.focus({ preventScroll: true });
    }
    bookDetailBack = null;
  }

  function onWearClick(event) {
    const sw = event.target.closest(".swatch");
    if (sw) {
      setColor(sw.dataset.kind, sw.dataset.color);
      return;
    }
    const opt = event.target.closest(".wear-opt");
    if (!opt) return;
    const cat = opt.dataset.cat;
    const id = opt.dataset.id || null;
    if (id && !isOwned(BY_ID[id])) {
      toast(lockedHint(BY_ID[id]));
      return;
    }
    if (wearing[cat] === id) {
      wearing[cat] = null;
      commitWear("已取下这一件");
      return;
    }
    wearing[cat] = id;
    const name = id ? BY_ID[id].name : "无";
    commitWear("已换上「" + name + "」");
  }

  function commitWear(message) {
    saveWear();
    applyHeroOutfit();
    refreshChip();
    if (tab === "book") renderBook();
    if (tab === "wear") renderWear();
    updateSub();
    if (message) toast(message);
  }

  function clearAll() {
    CATS.forEach(cat => { wearing[cat.id] = null; });
    commitWear("已把装扮全部卸下");
  }

  // 光效换色
  function setColor(kind, id) {
    const list = AURA_PALETTES[kind];
    if (!list) return;
    const opt = list.find(item => item.id === id);
    if (!opt) return;
    auraColors[kind] = id;
    saveWear();
    applyHeroOutfit();
    if (tab === "wear") renderWear();
    toast("光效颜色已换成「" + opt.name + "」");
  }

  // ---------- 图鉴 ----------
  function updateSub() {
    const el = mask && mask.querySelector("#dress-sub");
    if (!el) return;
    el.textContent = "已收集 " + ownedCount() + " / " + ITEMS.length +
      " 件装扮 · 已穿戴 " + equippedCount() + " 件";
  }

  function renderBook() {
    const grid = mask.querySelector("#book-grid");
    if (!grid) return;
    updateSub();

    grid.innerHTML = CATS.map(cat => {
      const items = ITEMS.filter(item => item.cat === cat.id);
      const catGot = items.reduce((n, item) => n + (isOwned(item) ? 1 : 0), 0);
      return `
        <section class="book-group">
          <div class="book-group__head">
            <span class="book-group__name">${cat.name}</span>
            <span class="book-group__hint">${cat.hint}</span>
            <span class="book-group__count">${catGot}/${items.length}</span>
          </div>
          <div class="book-group__grid">
            ${items.map(item => bookItemHtml(item)).join("")}
          </div>
        </section>`;
    }).join("");
  }

  function bookItemHtml(item) {
    const owned = isOwned(item);
    const on = wearing[item.cat] === item.id;
    const price = owned ? 0 : priceOf(item);
    return `
      <button type="button" class="book-item${owned ? "" : " is-locked"}${on ? " is-worn" : ""}"
              data-id="${item.id}"
              aria-haspopup="dialog"
              aria-label="${item.name}${owned ? "，已获得" : "，未获得"}${price ? "，商城 " + price + " 积分" : ""}，点击查看详情">
        ${price ? `<span class="book-item__price">${price} 分</span>` : ""}
        <span class="book-item__art">${frogSvg({ [item.cat]: item.id })}</span>
        <span class="book-item__name">${item.name}</span>
        <span class="book-item__from">${item.from}</span>
        <span class="book-item__tag">${on ? "已穿戴" : owned ? "已获得" : "未获得"}</span>
      </button>`;
  }

  // ---------- 装扮页 ----------
  function renderWear() {
    const preview = mask.querySelector("#wear-preview");
    const slots = mask.querySelector("#wear-slots");
    const caption = mask.querySelector("#wear-caption");
    if (!preview || !slots) return;
    preview.innerHTML = frogSvg(wearing);
    const names = CATS.filter(cat => wearing[cat.id]).map(cat => BY_ID[wearing[cat.id]].name);
    if (caption) caption.textContent = names.length ? names.join(" · ") : "素颜小蛙";

    slots.innerHTML = CATS.map(cat => {
      const items = ITEMS.filter(item => item.cat === cat.id);
      return `
        <div class="wear-row">
          <div class="wear-row__head">
            <span class="wear-row__name">${cat.name}</span>
            <span class="wear-row__count">${cat.id === "skin"
              ? (wearing.skin ? "已换色" : "默认肤色")
              : (wearing[cat.id] ? "已穿戴" : "未穿戴")}</span>
          </div>
          <div class="wear-row__opts">
            ${cat.id === "skin" ? "" : `<button type="button" class="wear-opt wear-opt--none${wearing[cat.id] ? "" : " is-active"}"
                    data-cat="${cat.id}" data-id="" aria-pressed="${wearing[cat.id] ? "false" : "true"}">
              <span class="wear-opt__none" aria-hidden="true">∅</span>
              <span class="wear-opt__name">无</span>
            </button>`}
            ${items.map(item => wearOptHtml(item)).join("")}
          </div>
          ${swatchHtml(cat)}
        </div>`;
    }).join("");
  }

  function wearOptHtml(item) {
    const owned = isOwned(item);
    // 肤色总有一款在用：没选过的时候苔绿就是默认状态
    const active = item.cat === "skin"
      ? (wearing.skin || "skin-moss") === item.id
      : wearing[item.cat] === item.id;
    return `
      <button type="button" class="wear-opt${owned ? "" : " is-locked"}${active ? " is-active" : ""}"
              data-cat="${item.cat}" data-id="${item.id}" aria-pressed="${active ? "true" : "false"}"
              title="${item.name} · ${item.from}">
        <span class="wear-opt__art">${frogSvg({ [item.cat]: item.id })}</span>
        <span class="wear-opt__name">${item.name}</span>
        ${owned ? "" : '<span class="wear-opt__lock" aria-hidden="true">锁</span>'}
      </button>`;
  }

  // 光效选中后出现的配色条
  function swatchHtml(cat) {
    const item = BY_ID[wearing[cat.id]];
    if (!item || !item.tone) return "";
    const list = AURA_PALETTES[item.tone];
    const picked = auraColors[item.tone];
    return `
      <div class="wear-swatches" data-kind="${item.tone}">
        <span class="wear-swatches__label">颜色</span>
        ${list.map(opt => {
          const sw = opt.id === "rainbow"
            ? "linear-gradient(90deg,#ff8f8f,#ffd166,#6fd08c,#8fd8ea)"
            : opt.colors[0];
          return `<button type="button" class="swatch${opt.id === picked ? " is-active" : ""}"
                    data-kind="${item.tone}" data-color="${opt.id}"
                    style="--sw:${sw}" title="${opt.name}"
                    aria-label="${opt.name}" aria-pressed="${opt.id === picked}"></button>`;
        }).join("")}
      </div>`;
  }

  // ---------- 开关 ----------
  function openPanel(targetTab) {
    if (!mask) buildPanel();
    if (!mask.classList.contains("hidden") && (!targetTab || targetTab === tab)) return;
    lastFocus = document.activeElement;
    refreshUnlocked();
    refreshChip();
    mask.classList.remove("hidden");
    setTab(targetTab === "book" ? "book" : "wear");
    const closeBtn = mask.querySelector("#dress-close");
    if (closeBtn) closeBtn.focus({ preventScroll: true });
    document.addEventListener("keydown", trapFocus);
  }

  function closePanel() {
    if (!mask) return;
    const detail = mask.querySelector("#book-detail");
    if (detail) detail.classList.add("hidden");
    bookDetailBack = null;
    mask.classList.add("hidden");
    document.removeEventListener("keydown", trapFocus);
    if (lastFocus && typeof lastFocus.focus === "function") {
      lastFocus.focus({ preventScroll: true });
    }
  }

  function trapFocus(event) {
    if (event.key !== "Tab" || !card) return;
    // 详情打开时，焦点只在详情内循环
    const scope = isBookDetailOpen() ? card.querySelector("#book-detail") : card;
    if (!scope) return;
    const focusables = [...scope.querySelectorAll(
      "button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"
    )].filter(el => el.getClientRects().length > 0);
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

  // ---------- 初始化 ----------
  function init() {
    wearing = readWear();
    readOwned();
    refreshUnlocked();
    applyHeroOutfit();

    const entry = document.getElementById("dressup-entry");
    if (entry) buildChip(entry);

    // 成就进度变化（例如刚玩完一局回来）后，重新核对解锁状态
    window.addEventListener("pageshow", () => {
      refreshUnlocked();
      applyHeroOutfit();
      refreshChip();
      if (mask && !mask.classList.contains("hidden")) {
        if (tab === "book") renderBook();
        else renderWear();
      }
    });
    // 成就面板关闭时，可能刚重置过成就，这里顺手同步一次
    window.addEventListener("focus", () => {
      refreshUnlocked();
      refreshChip();
    });
  }

  window.DressUp = {
    items: function () { return ITEMS.map(item => Object.assign({ owned: isOwned(item) }, item)); },
    wearing: function () { return Object.assign({}, wearing); },
    isOwned: function (id) { return isOwned(BY_ID[id]); },
    colors: function () { return Object.assign({}, auraColors); },
    setColor: setColor,
    palettes: function () { return AURA_PALETTES; },
    skin: function () { return Object.assign({}, skinOf()); },
    skinEllipses: skinEllipses,
    skinMouth: skinMouth,
    frogSvg: frogSvg,
    drawCanvas: drawCanvas,
    drawTrail: drawTrail,
    apply: function () { refreshUnlocked(); applyHeroOutfit(); refreshChip(); },
    // --- 商城 ---
    categories: function () { return CATS.map(c => ({ id: c.id, name: c.name })); },
    shopItems: shopItems,
    exclusiveItems: exclusiveItems,
    priceOf: function (id) { return priceOf(id); },
    doctorTier: doctorTier,
    buy: buy,
    ownedIds: function () { return [...ownedShop]; },
    // 商城买下后重载（例如别的标签页写入）
    reloadOwned: function () {
      readOwned();
      refreshUnlocked();
      applyHeroOutfit();
      if (mask && !mask.classList.contains("hidden")) {
        if (tab === "book") renderBook();
        else renderWear();
      }
      return [...ownedShop];
    },
    open: function (which) {
      const entry = document.getElementById("dressup-entry");
      if (!chip && entry) buildChip(entry);
      openPanel(which);
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
