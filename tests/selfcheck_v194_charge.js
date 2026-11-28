#!/usr/bin/env node
/* v1.9.4 补充：10% 初始蓄力、安全区域、归零休息状态机。
 * 只测试纯逻辑，不启动服务，不触碰真实数据库。 */
"use strict";
const assert = require("assert");
const FR = require("../web/assets/focus-round.js");

let passed = 0;
function check(name, fn) {
  try { fn(); passed += 1; console.log("PASS " + name); }
  catch (e) { console.log("FAIL " + name + " — " + e.message); process.exitCode = 1; }
}
function near(a, b, eps = 1e-6) { return Math.abs(a - b) <= eps; }
function engine(extra, options = { firstRound: false }) {
  return new FR.RoundEngine(Object.assign({}, FR.CONFIG, extra || {}), () => 0, options);
}
function chargeToBullet(e, score, dt = 0.02) {
  for (let i = 0; i < 10000 && e.phase === "CHARGING"; i++) {
    e.update(dt, { signalOk: true, charging: true, score });
  }
}

// ---- 初始蓄力：首轮与后续统一 10%，不硬编码 ----
check("公共配置为 10%", () => {
  assert.strictEqual(FR.CONFIG.startEnergy, 10);
  assert.strictEqual(FR.CONFIG.gameParamsVersion, "v1.9.4");
});

check("首轮从 10% 开始", () => {
  const e = engine({}, { firstRound: true });
  assert.strictEqual(e.energy, 10);
  assert.strictEqual(e.startEnergy, 10);
  assert.strictEqual(e.zone.lo >= 12, true);
});

check("每次跳跃结束后都从 10% 开始", () => {
  const e = engine({ zoneLoMin: 20, zoneLoMax: 20, firstRoundLoMin: 20, firstRoundLoMax: 20 }, { firstRound: true });
  chargeToBullet(e, 95);
  e.tap();
  const rec = e.finishRound();
  assert.ok(rec, "应先完成一轮");
  assert.strictEqual(rec.start_energy, 10);
  assert.strictEqual(rec.game_params_version, "v1.9.4");
  assert.strictEqual(e.energy, 10, "新轮次必须回到公共起点");
});

// ---- 计分距离 D 从新的起点计算，公式不变 ----
check("D 使用区域入口减 10%，计分公式不变", () => {
  const e = engine({ zoneLoMin: 40, zoneLoMax: 40, firstRoundLoMin: 40, firstRoundLoMax: 40 });
  const expected = FR.computePotentialScore(30, 5, FR.CONFIG);
  e.chargeSec = 5;
  e.energy = 40;
  e.update(0.02, { signalOk: true, charging: true, score: 95 });
  assert.strictEqual(e.potential, expected);
  assert.strictEqual(e.records.length, 0);
  e.tap();
  const rec = e.finishRound();
  assert.strictEqual(rec.potential, expected);
  assert.strictEqual(rec.start_energy, 10);
  assert.strictEqual(rec.zone_lo, 40);
});

// ---- 自适应难度安全限制 ----
check("最低难度区域仍与 10% 起点保持至少 2 个百分点", () => {
  const e = engine({ zoneLoMin: 5, zoneLoMax: 5, startEnergy: 10 });
  assert.strictEqual(e.zone.lo, 12);
  assert.strictEqual(e.zone.width, 6);
});

check("正常难度范围不被安全限制改写", () => {
  const e = engine({ zoneLoMin: 24, zoneLoMax: 55, startEnergy: 10 });
  assert.strictEqual(e.zone.lo, 24);
  assert.strictEqual(e.zone.width, 6);
});

// ---- 归零休息：2 秒、有效信号、防抖、恢复 ----
function zeroEngine(extra) {
  return engine(Object.assign({
    startEnergy: 0, zoneLoMin: 40, zoneLoMax: 40,
    firstRoundLoMin: 40, firstRoundLoMax: 40,
    chargeGainPerScoreSec: 0,
  }, extra || {}));
}
function zeroFor(e, sec, input) {
  const dt = 0.01;
  const n = Math.round(sec / dt);
  const events = [];
  for (let i = 0; i < n; i++) events.push(...e.update(dt, input || {
    signalOk: true, charging: false, score: 30,
  }));
  return events;
}

check("有效信号下蓄力为 0 持续 2 秒才进入休息", () => {
  const e = zeroEngine();
  let events = zeroFor(e, 1.99);
  assert.strictEqual(e.resting, false);
  events = zeroFor(e, 0.02);
  assert.strictEqual(e.resting, true);
  assert.strictEqual(e.restEvents, 1);
  assert.strictEqual(events.filter(x => x.type === "rest_start").length, 1);
  assert.strictEqual(e.energy, 0);
  assert.strictEqual(e.zone.lo, 40, "休息不能重置金色区域");
});

check("信号无效与暂停期间不累计归零时间", () => {
  const e = zeroEngine();
  zeroFor(e, 1.0);
  const before = e.zeroSec;
  zeroFor(e, 5, { signalOk: false, charging: false, score: 30 });
  zeroFor(e, 5, { signalOk: true, charging: false, score: 30, paused: true });
  assert.strictEqual(e.zeroSec, before);
  assert.strictEqual(e.resting, false);
});

check("蓄力增长后自动退出，且 0 附近波动不反复触发", () => {
  const e = zeroEngine({ chargeGainPerScoreSec: 0.16 });
  zeroFor(e, 2.01);
  assert.strictEqual(e.resting, true);
  const restCount = e.restEvents;
  // 能量升到 1% 左右但仍低于退出阈值：保持休息，不闪烁。
  zeroFor(e, 0.2, { signalOk: true, charging: true, score: 50 });
  assert.ok(e.energy > 0 && e.energy < FR.CONFIG.restExitEnergy);
  assert.strictEqual(e.resting, true);
  assert.strictEqual(e.restEvents, restCount);
  // 继续蓄力越过退出阈值：自动恢复，只触发一次。
  zeroFor(e, 1.5, { signalOk: true, charging: true, score: 70 });
  assert.ok(e.energy >= FR.CONFIG.restExitEnergy);
  assert.strictEqual(e.resting, false);
  assert.strictEqual(e.restEvents, restCount);
  // 又回到 0：必须重新等满 2 秒，不能在 0 附近反复切换。
  zeroFor(e, 0.5);
  assert.strictEqual(e.resting, false);
});

check("休息不扣分、不改变位置/计时/区域，也不自动补充蓄力", () => {
  const e = zeroEngine();
  const charge = e.chargeSec, zone = JSON.stringify(e.zone);
  zeroFor(e, 3.0);
  assert.strictEqual(e.resting, true);
  assert.strictEqual(e.energy, 0);
  assert.strictEqual(e.awarded, null);
  assert.ok(near(e.chargeSec, charge + 3.0, 1e-6), `${e.chargeSec} vs ${charge + 3}`);
  assert.strictEqual(JSON.stringify(e.zone), zone);
});

check("冷却期间不计入归零休息时长", () => {
  const e = zeroEngine();
  e.tap();                       // 提前点击，触发 0.5s 冷却
  zeroFor(e, 0.49);
  assert.ok(e.cooldownRemaining > 0);
  assert.strictEqual(e.zeroSec, 0);
});

console.log(`\n${passed} 项 v1.9.4 蓄力补充检查通过`);
