#!/usr/bin/env node
/* v1.8.4 蓄力过程统计、确定性种子与最低难度边界检查。 */
const FR = require("../web/assets/focus-round.js");
let passed = 0;
function check(name, condition, detail) {
  if (!condition) throw new Error(`${name} 失败 ${detail == null ? "" : JSON.stringify(detail)}`);
  passed += 1; console.log("PASS " + name);
}
function near(a, b, eps = 1e-6) { return Math.abs(a - b) <= eps; }

// 1. 确定性随机源
const r1 = FR.makeRng("seed-20261127");
const r2 = FR.makeRng("seed-20261127");
const a = [r1(), r1(), r1()], b = [r2(), r2(), r2()];
check("同一 seed 产生同一随机序列", a.every((v, i) => v === b[i]), { a, b });
check("不同 seed 产生不同序列", FR.makeRng("a")() !== FR.makeRng("b")());

// 2. 过程统计：有效蓄力 + 低于阈值 = eval；冷却/断流/暂停分开
const cfg = FR.normalizeConfig(Object.assign({}, FR.CONFIG, {
  zoneLoMin: 80, zoneLoMax: 80, zoneWidth: 6, bulletTimeSec: 2.5,
}));
const eng = new FR.RoundEngine(cfg, () => 0);
eng.update(1.0, { signalOk: true, charging: false, score: 30 });
check("低于阈值累计不与有效蓄力混合",
  near(eng.belowThresholdSec, 1) && near(eng.chargeActiveSec, 0) && near(eng.evalSec, 1), eng.snapshot());
eng.update(2.0, { signalOk: true, charging: true, score: 65 });
check("有效蓄力时间单独累计", near(eng.chargeActiveSec, 2) && near(eng.evalSec, 3), eng.snapshot());
check("能量增长与净变化记录", eng.energyGainTotal > 0 && eng.energy > 15, eng.snapshot());
const before = eng.energy;
eng.update(5.0, { signalOk: false, charging: true, score: 65 });
check("断流不进入 eval 且不改变能量",
  near(eng.staleSec, 5) && near(eng.evalSec, 3) && near(eng.energy, before), eng.snapshot());
eng.update(1.0, { signalOk: true, charging: true, score: 65, paused: true });
check("主动暂停单独计时", near(eng.pausedSec, 1) && near(eng.evalSec, 3), eng.snapshot());

// 3. 冷却不进入 eval
const tap = new FR.RoundEngine(cfg, () => 0);
const outcome = tap.tap();
check("提前点击触发冷却", outcome.type === "early" && outcome.cooldownStarted, outcome);
tap.update(0.25, { signalOk: true, charging: true, score: 65 });
check("冷却时间只进 charge/cooldown，不进 eval",
  near(tap.cooldownSec, 0.25) && near(tap.evalSec, 0) && near(tap.chargeSec, 0.25), tap.snapshot());

// 4. 最低难度边界：区域必须高于起始能量，D 从 15% 起算
const low = FR.normalizeConfig(Object.assign({}, FR.CONFIG, {
  zoneLoMin: 17, zoneLoMax: 17, zoneWidth: 6, startEnergy: 15,
}));
const le = new FR.RoundEngine(low, () => 0);
check("最低难度区域不会从起始能量内部生成", le.zone.lo > le.startEnergy, le.zone);
const d = le.zone.lo - le.startEnergy;
check("D 使用区域入口减起始能量", near(d, 2), { d, zone: le.zone });

// 5. 未完成轮次保留过程字段
const pending = le.pendingRound("time_up");
check("未完成轮次保留过程统计与能量",
  pending && pending.charge_active_sec != null && pending.jump_anim_sec != null
  && pending.energy_gain != null, pending);

// 6. 子弹时间与游戏层动画字段可回填
const bullet = new FR.RoundEngine(FR.normalizeConfig(Object.assign({}, FR.CONFIG, {
  zoneLoMin: 15, zoneLoMax: 15, zoneWidth: 6, startEnergy: 0,
})), () => 0);
bullet.update(1, { signalOk: true, charging: true, score: 100 });
const ev = bullet.update(1, { signalOk: true, charging: true, score: 100 });
if (bullet.phase === "BULLET_TIME") bullet.update(0.5, { signalOk: true, charging: true, score: 100 });
check("进入区域后记录子弹时间", bullet.phase === "BULLET_TIME" && bullet.bulletSec > 0, bullet.snapshot());
bullet.tap();
const rec = bullet.finishRound();
rec.jump_anim_sec = 0.55;
check("完成轮次可回填跳跃动画且不改变 eval",
  rec && rec.jump_anim_sec === 0.55 && rec.eval_sec === bullet.records[0].eval_sec, rec);

console.log(`\n${passed} 项 v1.8.4 单轮检查通过`);
