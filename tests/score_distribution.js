/**
 * 得分分布与公平性检查（可重复模拟脑电）
 * ------------------------------------------------------------
 * 运行：node tests/score_distribution.js
 * 输出 Markdown 表格，便于贴进开发报告。
 * 仅使用模拟分数，不代表真机或临床结论。
 */
"use strict";

const FR = require("../web/assets/focus-round.js");

const DT = 0.05;
const SECONDS = 90;
const JUMP_ANIM_SEC = 2.0;

function seeded(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function simulate(scoreAt, seconds = SECONDS, opt = {}) {
  const rng = seeded(opt.seed || 20261127);
  const e = new FR.RoundEngine({}, rng, { firstRound: false });
  const reaction = opt.reaction == null ? 0.3 : opt.reaction;
  let t = 0;
  let jumpAge = 0;

  while (t < seconds) {
    if (e.phase === "JUMP_SUCCESS" || e.phase === "JUMP_MISSED") {
      jumpAge += DT;
      if (jumpAge >= JUMP_ANIM_SEC) {
        jumpAge = 0;
        e.finishRound();
      }
      t += DT;
      continue;
    }

    const score = scoreAt(t);
    if (e.phase === "BULLET_TIME") {
      e.update(DT, { signalOk: true, charging: false, score });
      if (e.phase === "BULLET_TIME" && e.bulletElapsed >= reaction) {
        e.tap();
      }
    } else {
      const events = e.update(DT, {
        signalOk: true,
        charging: score > FR.CONFIG.chargeZeroScore,
        score,
      });
      for (const ev of events) {
        if (ev.type === "bullet_enter" && reaction <= 0) e.tap();
      }
    }
    t += DT;
  }

  if (e.phase === "JUMP_SUCCESS" || e.phase === "JUMP_MISSED") e.finishRound();
  const rounds = e.records;
  const successes = rounds.filter(r => r.success).length;
  const misses = rounds.length - successes;
  const bases = rounds.map(r => r.potential).filter(Number.isFinite);
  const awards = rounds.map(r => r.awarded).filter(Number.isFinite);
  const avg = arr => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null;
  const min = arr => arr.length ? Math.min(...arr) : null;
  const max = arr => arr.length ? Math.max(...arr) : null;
  return {
    rounds: rounds.length,
    successes,
    misses,
    baseAvg: avg(bases),
    actualAvg: avg(awards),
    total: awards.reduce((a, b) => a + b, 0),
    baseMin: min(bases),
    baseMax: max(bases),
    actualMin: min(awards),
    actualMax: max(awards),
  };
}

function fmt(v, digits = 1) {
  return v == null ? "—" : Number(v).toFixed(digits);
}

function rangeText(avg, min, max) {
  return avg == null ? "—" : `${fmt(avg)}（${fmt(min, 0)}–${fmt(max, 0)}）`;
}

function line(name, r, reaction) {
  return `| ${name} | ${r.rounds} | ${r.successes}/${r.misses} | `
    + `${rangeText(r.baseAvg, r.baseMin, r.baseMax)} | `
    + `${rangeText(r.actualAvg, r.actualMin, r.actualMax)} | `
    + `${r.total} | ${reaction.toFixed(1)}s |`;
}

console.log("## 1. 不同脑电输入的 90s 模拟（点击反应 0.3s）\n");
console.log("| 画像 | 完成轮次 | 成功/错过 | 平均脑电基础得分（范围） | 平均实际得分（范围） | 本局积分 | 点击时机 |");
console.log("|---|---:|---:|---:|---:|---:|---:|");
const profiles = [
  ["稳定 42（零点）", () => 42],
  ["稳定 45", () => 45],
  ["稳定 48（低）", () => 48],
  ["稳定 55", () => 55],
  ["稳定 60", () => 60],
  ["稳定 65（基准）", () => 65],
  ["稳定 70", () => 70],
  ["稳定 80", () => 80],
  ["稳定 85（高）", () => 85],
  ["稳定 90", () => 90],
  ["稳定 100（极高）", () => 100],
  ["间歇 85/35（4s+4s）", t => ((t % 8) < 4 ? 85 : 35)],
  ["间歇 70/45（4s+4s）", t => ((t % 8) < 4 ? 70 : 45)],
];
const results = profiles.map(([name, fn], i) => {
  const r = simulate(fn, SECONDS, { seed: 1000 + i });
  console.log(line(name, r, 0.3));
  return { name, r };
});

console.log("\n## 2. 点击时机对同一基础分的影响（B=76）\n");
console.log("| 点击时间 | 倍率 | 实际得分 | 相对基础分 |");
console.log("|---:|---:|---:|---:|");
for (const t of [0, 0.2, 0.6, 1.0, 1.5, 2.0, 2.4, 2.5]) {
  const m = FR.timingMultiplier(t);
  const s = FR.actualScore(76, t);
  console.log(`| ${t.toFixed(1)}s | ${m.toFixed(3)} | ${s} | ${(s / 76 * 100).toFixed(1)}% |`);
}

console.log("\n## 3. 随机金色区域位置的公平性（稳定 65，点击 0.3s）\n");
console.log("| 区域起点 | 基础得分 | 实际得分 |");
console.log("|---:|---:|---:|");
let bases = [];
for (const lo of [24, 28, 32, 36, 40, 45, 50, 55]) {
  const e = new FR.RoundEngine({
    zoneLoMin: lo, zoneLoMax: lo, firstRoundLoMin: lo, firstRoundLoMax: lo,
  }, () => 0, { firstRound: false });
  let t = 0;
  while (e.phase === "CHARGING" && t < 300) {
    e.update(0.01, { signalOk: true, charging: true, score: 65 });
    t += 0.01;
  }
  e.update(0.3, { signalOk: true, charging: false, score: 65 });
  const out = e.tap();
  bases.push(e.potential);
  console.log(`| ${lo} | ${e.potential} | ${out.score} |`);
}
console.log(`\n基础得分极差：${Math.max(...bases) - Math.min(...bases)} 分`);

console.log("\n## 4. 分辨率与高分段\n");
const byName = Object.fromEntries(results.map(x => [x.name, x.r]));
const b65 = byName["稳定 65（基准）"]?.baseAvg;
const b85 = byName["稳定 85（高）"]?.baseAvg;
const b100 = byName["稳定 100（极高）"]?.baseAvg;
const allBases = results.flatMap(x => [x.r.baseMin, x.r.baseMax]).filter(Number.isFinite);
console.log(`- 有效脑电基础分范围：${Math.min(...allBases)}–${Math.max(...allBases)} 分`);
console.log(`- 基准 65 → ${b65}，高 85 → ${b85}，极高 100 → ${b100}`);
console.log(`- 85→100（脑电 +15 分）只带来 ${b100 - b85} 分基础分提升，高分段存在自然压缩`);
console.log("- 结论：保留原公式；若后续要提高高分段区分度，先做参数对比实验，不直接乘倍数。");

console.log("\n## 5. 边界行为\n");
for (const [name, score] of [["42（蓄力零点）", 42], ["45（刚过阈值）", 45], ["100（极高）", 100]]) {
  const r = simulate(() => score, 30, { seed: 7, reaction: 0.3 });
  console.log(`- ${name}：30s 完成 ${r.rounds} 轮，成功 ${r.successes}，错过 ${r.misses}，积分 ${r.total}`);
}

console.log("\n> 模拟数据仅用于机制检查；未完成 Xmuse 真机与儿童受试者验证。");
