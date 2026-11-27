/**
 * v1.8.3 单轮边界：净蓄力评估、未完成轮次、难度范围与计分独立性。
 * 只测纯逻辑，不启动服务。
 */
"use strict";
const assert = require("assert");
const FR = require("../web/assets/focus-round.js");

let passed = 0;
function check(name, fn) {
  try { fn(); passed += 1; console.log("PASS " + name); }
  catch (e) { console.log("FAIL " + name + " — " + e.message); process.exitCode = 1; }
}
function engine(lo, rng) {
  return new FR.RoundEngine(Object.assign({}, FR.CONFIG, {
    zoneLoMin: lo, zoneLoMax: lo, firstRoundLoMin: lo, firstRoundLoMax: lo,
  }), rng || (() => .5));
}

check("净蓄力评估时间排除无效点击冷却", () => {
  const e = engine(40);
  e.update(2, { signalOk: true, charging: true, score: 85 });
  e.tap();
  e.update(1, { signalOk: true, charging: true, score: 85 });
  assert.ok(Math.abs(e.chargeSec - 3) < 1e-6, "计分时间应包含冷却");
  assert.ok(Math.abs(e.evalSec - 2.5) < 1e-6, "评估时间应排除 0.5s 冷却");
});

check("断流和主动暂停不增加净蓄力时间", () => {
  const e = engine(40);
  e.update(1, { signalOk: true, charging: true, score: 85 });
  e.update(2, { signalOk: false, charging: true, score: 85 });
  e.update(2, { signalOk: true, charging: true, score: 85, paused: true });
  assert.ok(Math.abs(e.evalSec - 1) < 1e-6, `实际 ${e.evalSec}`);
  assert.strictEqual(e.chargeSec, 1);
});

check("未完成轮次保留观察下限和能量增长", () => {
  const e = engine(50);
  e.update(5, { signalOk: true, charging: true, score: 85 });
  const p = e.pendingRound("time_up");
  assert.ok(p && p.entered === false);
  assert.ok(Math.abs(p.eval_sec - 5) < 1e-6);
  assert.ok(p.energy_gain > 0, "应记录有效能量增长");
  assert.strictEqual(p.ended_reason, "time_up");
  assert.strictEqual(e.finishRound(), null);
});

check("完成轮次只记录一次，新轮次从空状态开始", () => {
  const e = engine(30);
  e.update(3, { signalOk: true, charging: true, score: 85 });
  e.tap();
  e.finishRound();
  assert.strictEqual(e.records.length, 1);
  const p = e.pendingRound();
  assert.ok(p && p.eval_sec === 0 && p.energy_gain === 0, "新一轮不能复用上一轮时长");
});

check("难度只缩放黄色区域起点，宽度保持 6", () => {
  for (const lo of [17, 24, 33, 55, 66]) {
    const e = engine(lo, () => 0);
    assert.strictEqual(e.zone.lo, lo);
    assert.strictEqual(e.zone.hi, lo + 6);
    assert.strictEqual(e.zone.width, 6);
  }
});

check("每轮重新随机且不沿用上一轮区域", () => {
  const values = [.8, .2];
  const e = new FR.RoundEngine(Object.assign({}, FR.CONFIG, {
    zoneLoMin: 24, zoneLoMax: 55, firstRoundLoMin: 24, firstRoundLoMax: 55,
  }), () => values.shift() ?? .5);
  const first = e.zone.lo;
  e.update(3, { signalOk: true, charging: true, score: 90 });
  e.tap();
  e.finishRound();
  assert.notStrictEqual(e.zone.lo, first, "新一轮应重新采样");
});

check("相同稳定蓄力速度在不同区域距离下基础分接近", () => {
  const speed = 4;
  const a = FR.computePotentialScore(10, 10 / speed, FR.CONFIG);
  const b = FR.computePotentialScore(30, 30 / speed, FR.CONFIG);
  assert.ok(Math.abs(a - b) <= 1, `10%距离=${a}, 30%距离=${b}`);
});

check("轮次记录包含评估时间、难度快照和区域宽度", () => {
  const e = new FR.RoundEngine(Object.assign({}, FR.CONFIG, {
    zoneLoMin: 24, zoneLoMax: 24, firstRoundLoMin: 24, firstRoundLoMax: 24,
    difficultyFactor: .8,
  }), () => .5);
  e.update(2, { signalOk: true, charging: true, score: 85 });
  e.tap();
  const rec = e.finishRound();
  assert.ok(rec.eval_sec > 0);
  assert.strictEqual(rec.difficulty_factor, .8);
  assert.strictEqual(rec.zone_width, 6);
  assert.ok(rec.energy_gain > 0);
});

console.log(`\n${passed} 项 v1.8.3 单轮检查通过`);
