/**
 * 回归自测：单轮核心机制（web/assets/focus-round.js）
 * ------------------------------------------------------------
 * 用可重复的模拟脑电分数覆盖：蓄力速度、随机位置归一化、宽容期、
 * 衰减、间歇蓄力、唯一金色区域、子弹时间、点击结算、信号异常、
 * 暂停恢复、低帧率、多轮状态污染与计分边界。
 *
 * 运行：node tests/selfcheck_round_logic.js
 * 不启动服务、不读写会话数据，也不需要真实脑电设备。
 */
"use strict";

const assert = require("assert");
const FR = require("../web/assets/focus-round.js");

let passed = 0;
const failures = [];
function check(name, fn) {
  try {
    fn();
    passed += 1;
    console.log("PASS " + name);
  } catch (err) {
    failures.push({ name, message: err && err.message ? err.message : String(err) });
    console.log("FAIL " + name + " — " + (err && err.message ? err.message : err));
  }
}

/** 固定金色区域起点，消除随机性；firstRound=false 使用常规范围。 */
function fixedConfig(zoneLo, extra) {
  return Object.assign({
    zoneLoMin: zoneLo,
    zoneLoMax: zoneLo,
    firstRoundLoMin: zoneLo,
    firstRoundLoMax: zoneLo,
  }, extra || {});
}

function engineAt(zoneLo, extra) {
  return new FR.RoundEngine(fixedConfig(zoneLo, extra), () => 0, { firstRound: false });
}

/** 推进到子弹时间（或超时），返回实际用时。 */
function chargeToBullet(engine, inputFn, dt, maxSec) {
  const step = dt || 0.02;
  const limit = maxSec == null ? 300 : maxSec;
  let t = 0;
  const events = [];
  while (engine.phase === "CHARGING" && t < limit) {
    const input = typeof inputFn === "function" ? inputFn(t) : inputFn;
    events.push.apply(events, engine.update(step, input));
    t += step;
  }
  return { t, events };
}

function runBulletToEnd(engine, dt) {
  const step = dt || 0.02;
  let t = 0;
  const events = [];
  while (engine.phase === "BULLET_TIME" && t < 10) {
    events.push.apply(events, engine.update(step, { signalOk: true, charging: false, score: 0 }));
    t += step;
  }
  return { t, events };
}

// ---------------------------------------------------------------------------
// 1. 蓄力速度与负增益
// ---------------------------------------------------------------------------
check("分数越高蓄力越快，且低于零点不为负", () => {
  const low = FR.chargeSpeed(45);
  const mid = FR.chargeSpeed(65);
  const high = FR.chargeSpeed(90);
  assert.ok(low > 0, "45 分应仍有正蓄力速度");
  assert.ok(high > mid && mid > low, "蓄力速度应随分数单调增加");
  assert.strictEqual(FR.chargeSpeed(42), 0, "零点应为 0");
  assert.strictEqual(FR.chargeSpeed(39), 0, "滞回区间内不得出现负增益");
  assert.strictEqual(FR.chargeSpeed(-10), 0, "异常低分不得为负");
});

check("蓄力值不会超出 0–100", () => {
  const e = engineAt(95, { chargeGainPerScoreSec: 10 });
  e.update(50, { signalOk: true, charging: true, score: 100 });
  assert.ok(e.energy >= 0 && e.energy <= 100, "蓄力应被钳制");
  assert.strictEqual(e.phase, "BULLET_TIME");
  // 衰减到 0 后不能为负
  const d = engineAt(95);
  for (let i = 0; i < 500; i += 1) {
    d.update(0.1, { signalOk: true, charging: false, score: 0 });
  }
  assert.strictEqual(d.energy, 0, "能量最低衰减到 0");
});

// ---------------------------------------------------------------------------
// 2. 计分：速度区分度与随机位置归一化
// ---------------------------------------------------------------------------
check("相同金色区域位置下，蓄力越快潜在得分越高", () => {
  const slow = engineAt(30);
  const fast = engineAt(30);
  chargeToBullet(slow, { signalOk: true, charging: true, score: 55 }, 0.01);
  chargeToBullet(fast, { signalOk: true, charging: true, score: 85 }, 0.01);
  assert.strictEqual(slow.phase, "BULLET_TIME");
  assert.strictEqual(fast.phase, "BULLET_TIME");
  assert.ok(fast.potential > slow.potential,
    `快蓄力 ${fast.potential} 应高于慢蓄力 ${slow.potential}`);
  assert.ok(fast.potential - slow.potential >= 15, "区分度应明显大于旧版固定 1/2 分");
});

check("相同平均蓄力速度下，不同金色区域位置得分近似相同", () => {
  const near = engineAt(26);
  const far = engineAt(45);
  chargeToBullet(near, { signalOk: true, charging: true, score: 65 }, 0.01);
  chargeToBullet(far, { signalOk: true, charging: true, score: 65 }, 0.01);
  assert.strictEqual(near.phase, "BULLET_TIME");
  assert.strictEqual(far.phase, "BULLET_TIME");
  assert.ok(Math.abs(near.potential - far.potential) <= 1,
    `近 ${near.potential} / 远 ${far.potential} 应近似相同`);
});

check("计分公式边界与范围", () => {
  assert.strictEqual(FR.computePotentialScore(0, 0), 20, "零距离应回落到下限");
  assert.strictEqual(FR.computePotentialScore(10, 0), 100, "零用时封顶 100");
  assert.strictEqual(FR.computePotentialScore(10, 1e9), 20, "极慢用时接近下限");
  assert.ok(FR.computePotentialScore(-5, -5) >= 20, "负值输入不得越界");
  assert.ok(FR.computePotentialScore(10, 0.0001) <= 100, "得分不得超过 100");
});

// ---------------------------------------------------------------------------
// 3. 宽容期与能量衰减
// ---------------------------------------------------------------------------
check("短暂低于阈值不会立即损失能量", () => {
  const e = engineAt(90);
  e.update(2, { signalOk: true, charging: true, score: 65 });
  const before = e.energy;
  e.update(1.4, { signalOk: true, charging: false, score: 35 });
  assert.ok(Math.abs(e.energy - before) < 1e-9, "宽容期内能量应保持不变");
  assert.strictEqual(e.decayEvents, 0);
});

check("连续低于阈值超过宽容期会缓慢衰减", () => {
  const e = engineAt(90);
  e.update(2, { signalOk: true, charging: true, score: 65 });
  const before = e.energy;
  e.update(1.6, { signalOk: true, charging: false, score: 35 });
  assert.ok(e.energy < before, "超过宽容期后应开始衰减");
  assert.ok(e.decayEvents >= 1, "应记录一次衰减事件");
  assert.ok(e.decaySec > 0, "应累计衰减时长");
  // 重新达标后停止衰减，并恢复蓄力
  const atStop = e.energy;
  e.update(0.5, { signalOk: true, charging: false, score: 35 });
  assert.ok(e.energy < atStop);
  e.update(0.5, { signalOk: true, charging: true, score: 70 });
  assert.ok(e.energy > 0 && !e.decaying, "恢复达标后应停止衰减");
});

check("间歇性蓄力比持续蓄力得分效率更低", () => {
  const continuous = engineAt(50);
  const intermittent = engineAt(50);
  chargeToBullet(continuous, { signalOk: true, charging: true, score: 65 }, 0.02);
  chargeToBullet(intermittent, t => ({
    signalOk: true,
    // 1 秒蓄力 + 3 秒走神：走神超过宽容期后持续掉能量
    charging: (t % 4) < 1,
    score: (t % 4) < 1 ? 65 : 35,
  }), 0.02, 300);
  assert.strictEqual(continuous.phase, "BULLET_TIME");
  assert.strictEqual(intermittent.phase, "BULLET_TIME");
  assert.ok(intermittent.chargeSec > continuous.chargeSec * 2,
    "间歇蓄力应显著拉长有效用时");
  assert.ok(intermittent.potential < continuous.potential - 15,
    `间歇 ${intermittent.potential} 应明显低于持续 ${continuous.potential}`);
});

check("计时包含等待、宽容期与衰减时间", () => {
  const baseline = engineAt(50);
  const withGrace = engineAt(50);
  chargeToBullet(baseline, { signalOk: true, charging: true, score: 65 }, 0.02);
  // 先蓄力 2 秒，再走神 2.6 秒（1.5 秒宽容 + 1.1 秒衰减），然后继续
  const chargeSec = 2;
  for (let t = 0; t < 50 && withGrace.phase === "CHARGING"; t += 0.02) {
    const charging = t < chargeSec || t >= chargeSec + 2.6;
    withGrace.update(0.02, {
      signalOk: true,
      charging,
      score: charging ? 65 : 35,
    });
  }
  assert.strictEqual(withGrace.phase, "BULLET_TIME");
  assert.ok(withGrace.chargeSec > baseline.chargeSec + 2.5,
    "走神等待必须计入本轮用时");
  assert.ok(withGrace.potential < baseline.potential,
    "计入等待后得分应更低");
});

// ---------------------------------------------------------------------------
// 4. 唯一金色区域与子弹时间
// ---------------------------------------------------------------------------
check("每轮只生成一次金色区域，错过后不重掷", () => {
  const e = engineAt(30);
  const firstZone = Object.assign({}, e.zone);
  chargeToBullet(e, { signalOk: true, charging: true, score: 85 }, 0.02);
  runBulletToEnd(e);
  assert.strictEqual(e.phase, "JUMP_MISSED");
  const afterMiss = Object.assign({}, e.zone);
  assert.deepStrictEqual(afterMiss, firstZone, "错过后不得重新随机金色区域");
  e.update(10, { signalOk: true, charging: true, score: 100 });
  assert.strictEqual(e.phase, "JUMP_MISSED", "错过后不得继续蓄力或再次触发");
  assert.deepStrictEqual(e.zone, firstZone, "错过后仍保持同一区域");
});

check("下一轮重新生成金色区域并重置本轮数据", () => {
  const e = engineAt(30);
  chargeToBullet(e, { signalOk: true, charging: true, score: 85 }, 0.02);
  runBulletToEnd(e);
  const rec = e.finishRound();
  assert.ok(rec && rec.success === false);
  assert.strictEqual(e.records.length, 1);
  assert.strictEqual(e.phase, "CHARGING");
  assert.strictEqual(e.energy, FR.CONFIG.startEnergy);
  assert.strictEqual(e.chargeSec, 0);
  assert.strictEqual(e.roundIndex, 2);
  assert.ok(e.zone.hi > e.zone.lo, "新区域必须合法");
});

check("不同蓄力速度拥有相同的子弹时间点击窗口", () => {
  const slow = engineAt(30);
  const fast = engineAt(30);
  chargeToBullet(slow, { signalOk: true, charging: true, score: 50 }, 0.01);
  chargeToBullet(fast, { signalOk: true, charging: true, score: 95 }, 0.01);
  const slowWindow = runBulletToEnd(slow, 0.01).t;
  const fastWindow = runBulletToEnd(fast, 0.01).t;
  assert.ok(Math.abs(slowWindow - FR.CONFIG.bulletTimeSec) < 0.05, "慢速玩家窗口应为 2.5s");
  assert.ok(Math.abs(fastWindow - FR.CONFIG.bulletTimeSec) < 0.05, "快速玩家窗口应为 2.5s");
  assert.ok(Math.abs(slowWindow - fastWindow) < 0.05, "窗口长度必须一致");
});

check("子弹时间移动速度 = 区域宽度 / 窗口时长", () => {
  const e = engineAt(30);
  chargeToBullet(e, { signalOk: true, charging: true, score: 85 }, 0.02);
  const before = e.energy;
  e.update(1, { signalOk: true, charging: false, score: 0 });
  const expected = e.zone.lo + e.zone.width * (1 / FR.CONFIG.bulletTimeSec);
  assert.ok(Math.abs(e.energy - expected) < 1e-6,
    `1 秒后应到 ${expected}，实际 ${e.energy}`);
  assert.ok(e.energy > before, "子弹时间内应缓慢向前移动");
});

// ---------------------------------------------------------------------------
// 5. 点击、结算与防刷分
// ---------------------------------------------------------------------------
check("成功点击只结算一次积分", () => {
  const e = engineAt(30);
  chargeToBullet(e, { signalOk: true, charging: true, score: 85 }, 0.02);
  const potential = e.potential;
  const first = e.tap();
  const second = e.tap();
  const third = e.tap();
  assert.strictEqual(first.type, "success");
  assert.strictEqual(first.score, potential);
  assert.strictEqual(second.type, "ignored");
  assert.strictEqual(third.type, "ignored");
  assert.strictEqual(e.awarded, potential);
  assert.ok(e.reactionSec >= 0, "应记录点击反应时间");
  e.update(10, { signalOk: true, charging: false, score: 0 });
  assert.strictEqual(e.awarded, potential, "动画期间不得重复结算");
  const rec = e.finishRound();
  assert.strictEqual(rec.awarded, potential);
  assert.strictEqual(rec.success, true);
  assert.strictEqual(e.records.length, 1, "每轮只产生一条记录");
});

check("错过点击立即普通跳跃且得分为 0", () => {
  const e = engineAt(30);
  chargeToBullet(e, { signalOk: true, charging: true, score: 85 }, 0.02);
  const potential = e.potential;
  runBulletToEnd(e);
  assert.strictEqual(e.phase, "JUMP_MISSED");
  assert.strictEqual(e.awarded, 0, "错过不得获得潜在得分");
  assert.ok(potential >= 20, "潜在得分仍然记录，便于分析");
  const rec = e.finishRound();
  assert.strictEqual(rec.awarded, 0);
  assert.strictEqual(rec.potential, potential);
  assert.strictEqual(rec.success, false);
});

check("提前点击、连续点击与长按重复都不刷分", () => {
  const e = engineAt(30);
  e.update(1, { signalOk: true, charging: true, score: 70 });
  const before = e.energy;
  for (let i = 0; i < 5; i += 1) {
    const out = e.tap();
    assert.strictEqual(out.type, "early");
  }
  assert.strictEqual(e.earlyTaps, 5);
  assert.ok(Math.abs(e.energy - before) < 1e-9, "提前点击不得清空或扣除蓄力");
  assert.strictEqual(e.awarded, null, "提前点击不得产生得分");
  chargeToBullet(e, { signalOk: true, charging: true, score: 85 }, 0.02);
  const first = e.tap();
  assert.strictEqual(first.type, "success");
  // 模拟长按产生的重复事件
  for (let i = 0; i < 10; i += 1) e.tap();
  assert.strictEqual(e.awarded, first.score, "重复输入不得累加");
});

// ---------------------------------------------------------------------------
// 6. 信号异常与暂停
// ---------------------------------------------------------------------------
check("信号异常期间不计时、不衰减、不产生蓄力", () => {
  const e = engineAt(90);
  e.update(2, { signalOk: true, charging: true, score: 65 });
  const snap = e.snapshot();
  for (let i = 0; i < 100; i += 1) {
    e.update(0.05, { signalOk: false, charging: false, score: 0 });
  }
  assert.ok(Math.abs(e.energy - snap.energy) < 1e-9, "异常期间能量必须冻结");
  assert.ok(Math.abs(e.chargeSec - snap.chargeSec) < 1e-9, "异常期间本轮计时必须暂停");
  assert.strictEqual(e.decaySec, 0, "异常期间不得触发衰减");
  assert.ok(Math.abs(e.staleSec - 5) < 0.001, "应累计信号异常时长");
  // 恢复后继续，不把异常时长算作走神
  e.update(0.5, { signalOk: true, charging: true, score: 65 });
  assert.ok(e.energy > snap.energy, "恢复后应继续蓄力");
  assert.strictEqual(e.decayEvents, 0, "异常不得被判定为注意力不足");
});

check("子弹时间遇到信号异常会暂停并原状态恢复", () => {
  const e = engineAt(30);
  chargeToBullet(e, { signalOk: true, charging: true, score: 85 }, 0.02);
  e.update(1, { signalOk: true, charging: false, score: 0 });
  const elapsed = e.bulletElapsed;
  const energy = e.energy;
  e.update(5, { signalOk: false, charging: false, score: 0 });
  assert.strictEqual(e.bulletElapsed, elapsed, "异常期间子弹时间必须冻结");
  assert.strictEqual(e.energy, energy, "异常期间蓄力条不得移动");
  const rest = runBulletToEnd(e, 0.01);
  assert.ok(Math.abs(rest.t - (FR.CONFIG.bulletTimeSec - elapsed)) < 0.05,
    "恢复后应继续剩余窗口，而不是重新计时");
});

check("主动暂停保存原有状态", () => {
  const e = engineAt(30);
  e.update(2, { signalOk: true, charging: true, score: 70 });
  const snap = e.snapshot();
  e.update(5, { signalOk: true, charging: true, score: 70, paused: true });
  assert.strictEqual(e.energy, snap.energy);
  assert.strictEqual(e.chargeSec, snap.chargeSec);
  e.update(1, { signalOk: true, charging: true, score: 70 });
  assert.ok(e.energy > snap.energy, "恢复后从原状态继续");
});

// ---------------------------------------------------------------------------
// 7. 帧率、多轮状态与数据记录
// ---------------------------------------------------------------------------
check("低帧率或大帧间隔不会跳过金色区域", () => {
  const e = engineAt(30, { chargeGainPerScoreSec: 10 });
  e.update(0.01, { signalOk: true, charging: true, score: 65 });
  const events = e.update(10, { signalOk: true, charging: true, score: 100 });
  assert.ok(events.some(ev => ev.type === "bullet_enter"), "应触发子弹时间");
  assert.strictEqual(e.phase, "BULLET_TIME");
  assert.strictEqual(e.energy, e.zone.lo, "进入时应落在区域起点，而不是越过");
  assert.ok(e.potential >= 20 && e.potential <= 100, "潜在得分必须合法");
  e.update(10, { signalOk: true, charging: false, score: 0 });
  assert.strictEqual(e.phase, "JUMP_MISSED", "大帧间隔也只触发一次错过");
});

check("连续多轮不存在状态污染", () => {
  const e = engineAt(30);
  for (let i = 0; i < 8; i += 1) {
    chargeToBullet(e, { signalOk: true, charging: true, score: 70 + (i % 3) * 10 }, 0.02);
    assert.strictEqual(e.phase, "BULLET_TIME");
    assert.strictEqual(e.chargeSec > 0, true);
    assert.strictEqual(e.decayEvents, 0);
    if (i % 2 === 0) {
      e.tap();
      assert.strictEqual(e.phase, "JUMP_SUCCESS");
    } else {
      runBulletToEnd(e);
      assert.strictEqual(e.phase, "JUMP_MISSED");
    }
    e.finishRound();
    assert.strictEqual(e.energy, FR.CONFIG.startEnergy, "每轮应从同一起点开始");
    assert.strictEqual(e.earlyTaps, 0, "提前点击计数不得跨轮累积");
    assert.strictEqual(e.staleSec, 0, "异常时长不得跨轮累积");
  }
  assert.strictEqual(e.records.length, 8);
  assert.strictEqual(e.roundIndex, 9);
  assert.strictEqual(e.records.filter(r => r.success).length, 4);
  assert.strictEqual(e.records.filter(r => !r.success).length, 4);
});

check("每轮数据字段完整且可用于研究分析", () => {
  const e = engineAt(30);
  chargeToBullet(e, { signalOk: true, charging: true, score: 85 }, 0.02);
  e.update(0.5, { signalOk: false, charging: false, score: 0 });
  e.tap();
  const rec = e.finishRound();
  const keys = [
    "round", "charge_sec", "zone_lo", "zone_hi", "t_ref", "potential",
    "awarded", "success", "reaction_sec", "mean_score", "above_ratio",
    "decay_events", "decay_sec", "stale_sec", "early_taps",
  ];
  keys.forEach(k => assert.ok(Object.prototype.hasOwnProperty.call(rec, k), "缺少字段 " + k));
  assert.ok(rec.reaction_sec != null && rec.reaction_sec >= 0);
  assert.ok(rec.mean_score > 0 && rec.mean_score <= 100);
  assert.ok(rec.above_ratio >= 0 && rec.above_ratio <= 1);
  assert.ok(Math.abs(rec.stale_sec - 0.5) < 0.001, "异常时长应写入本轮记录");
});

// ---------------------------------------------------------------------------
// 8. 积分经济
// ---------------------------------------------------------------------------
check("表现分与商城积分分离且不会产生负积分", () => {
  assert.strictEqual(FR.pointsForScore(0), 0);
  assert.strictEqual(FR.pointsForScore(19), 1, "有得分时至少 1 积分");
  assert.strictEqual(FR.pointsForScore(20), 1);
  assert.strictEqual(FR.pointsForScore(60), 2);
  assert.strictEqual(FR.pointsForScore(100), 3);
  assert.strictEqual(FR.pointsForScore(-100), 0);
  assert.ok(FR.pointsForScore(100) < 100, "单跳积分不应等于表现分");
});

// ---------------------------------------------------------------------------
// 9. 整局模拟脑电：稳定高分 / 稳定低分 / 间歇性 / 快速波动 / 断流
// ---------------------------------------------------------------------------
function simulateSession(profile, seconds, seed) {
  let s = seed || 20261127;
  const rng = () => {
    s = (s * 1664525 + 1013904223) % 4294967296;
    return s / 4294967296;
  };
  const e = new FR.RoundEngine({}, rng, { firstRound: false });
  const dt = 0.05;
  let t = 0;
  let jumpAge = 0;
  let awarded = 0;
  let successes = 0;
  let misses = 0;
  let stale = 0;

  while (t < seconds) {
    const input = profile(t);
    if (input.signalOk === false) stale += dt;
    if (e.phase === "JUMP_SUCCESS" || e.phase === "JUMP_MISSED") {
      jumpAge += dt;
      if (jumpAge >= 2) {
        e.finishRound();
        jumpAge = 0;
      }
    } else {
      const events = e.update(dt, input);
      for (const ev of events) {
        if (ev.type === "bullet_enter") {
          // 一半轮次立即点击兑现，一半轮次故意错过，覆盖两种结算路径
          if (e.roundIndex % 2 === 1) {
            const out = e.tap();
            if (out.type === "success") {
              awarded += out.score;
              successes += 1;
            }
          }
        } else if (ev.type === "miss") {
          misses += 1;
        }
      }
    }
    t += dt;
  }
  return { awarded, successes, misses, records: e.records.length, stale, engine: e };
}

const PROFILES = {
  high: () => ({ signalOk: true, charging: true, score: 85 }),
  low: () => ({ signalOk: true, charging: true, score: 48 }),
  intermittent: t => {
    const on = (t % 8) < 4;
    return { signalOk: true, charging: on, score: on ? 85 : 35 };
  },
  fluctuating: t => {
    const score = 70 + 20 * Math.sin(t * Math.PI * 2 / 1.5);
    return { signalOk: true, charging: score > 42, score };
  },
  dropout: t => ({
    signalOk: !(t >= 15 && t < 27),
    charging: true,
    score: 85,
  }),
};

check("整局模拟：稳定高分 > 间歇性高分 > 稳定低分", () => {
  const high = simulateSession(PROFILES.high, 90, 11);
  const intermittent = simulateSession(PROFILES.intermittent, 90, 12);
  const low = simulateSession(PROFILES.low, 90, 13);
  assert.ok(high.awarded > 0, "稳定高分应有得分");
  assert.ok(high.awarded > intermittent.awarded * 1.15,
    `高分 ${high.awarded} 应明显高于间歇 ${intermittent.awarded}`);
  assert.ok(intermittent.awarded > low.awarded,
    `间歇 ${intermittent.awarded} 应高于低分 ${low.awarded}`);
  assert.ok(high.misses + high.successes > 0);
});

check("整局模拟：快速波动不会卡死或产生负分", () => {
  const wave = simulateSession(PROFILES.fluctuating, 90, 21);
  assert.ok(wave.records > 0, "快速波动也应能完成若干轮");
  assert.ok(wave.awarded >= 0 && wave.awarded < 90 * 100, "得分必须有限且非负");
  assert.ok(wave.engine.records.every(r => r.potential >= 20 && r.potential <= 100));
  assert.ok(wave.engine.records.every(r => r.awarded >= 0));
});

check("整局模拟：设备断流期间不蓄力、不衰减、不计时", () => {
  const normal = simulateSession(PROFILES.high, 90, 31);
  const dropped = simulateSession(PROFILES.dropout, 90, 31);
  assert.ok(dropped.stale > 10, "应累计约 12 s 异常时长，实际 " + dropped.stale);
  assert.ok(dropped.awarded <= normal.awarded, "断流不得带来额外得分");
  assert.ok(dropped.records < normal.records, "断流期间应少完成轮次");
  // 断流跨轮后仍能继续，且每轮记录不含负值
  assert.ok(dropped.engine.records.every(r => r.charge_sec >= 0 && r.decay_sec >= 0));
});

// ---------------------------------------------------------------------------
console.log("");
if (failures.length) {
  console.log(failures.length + " failed: " + failures.map(f => f.name).join(", "));
  process.exit(1);
}
console.log("all " + passed + " checks passed");
