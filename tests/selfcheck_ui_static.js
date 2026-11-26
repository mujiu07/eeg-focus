/**
 * 界面与数据链路的静态自检
 * ------------------------------------------------------------
 * 运行：node tests/selfcheck_ui_static.js
 * 不启动浏览器；用于防止儿童端又出现实时分数、百分制或 +0 反馈。
 */
"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const read = rel => fs.readFileSync(path.join(root, rel), "utf8");
const game = read("web/game.html");
const report = read("web/report.html");
const exportPy = read("app/export.py");
const serverPy = read("app/server.py");
const engine = read("web/assets/focus-round.js");

let passed = 0;
function check(name, fn) {
  try {
    fn();
    passed += 1;
    console.log("PASS " + name);
  } catch (err) {
    console.log("FAIL " + name + " — " + (err && err.message ? err.message : err));
    process.exitCode = 1;
  }
}

check("儿童端隐藏实时脑电分、蓄力百分比、BPM 与信号质量", () => {
  assert.ok(game.includes("html:not(.debug-hud) .debug-only { display: none !important; }"));
  assert.ok(/id="focus-readout" class="debug-only"/.test(game));
  assert.ok(game.includes('class="debug-only">蓄力 <strong id="energy-readout"'));
  assert.ok(/id="hr-hud"[^>]*debug-only|debug-only[^>]*id="hr-hud"/.test(game));
  assert.ok(/id="quality-hud"[^>]*debug-only|debug-only[^>]*id="quality-hud"/.test(game));
  assert.ok(game.includes('debugHud ? "信号分数" : "蓄力"'));
  assert.ok(game.includes('document.documentElement.classList.toggle("debug-hud", debugHud)'));
});

check("儿童端保留本局积分，不出现百分制/潜在得分文案", () => {
  assert.ok(game.includes("<span>本局积分</span>"));
  assert.ok(game.includes('<span>本局积分</span>') && game.includes('id="score"'));
  assert.ok(game.includes('商城积分 +<b>'));
  assert.ok(!game.includes("潜在"));
  assert.ok(!game.includes("完美 +"));
  assert.ok(!game.includes("得分</span>"));
});

check("成功只显示 +N，错过不显示 +0，反馈时长来自集中配置", () => {
  assert.ok(game.includes('text: "+" + gain'));
  assert.ok(game.includes("life: roundConfig.gainCueSec"));
  assert.ok(game.includes("p.life || roundConfig.gainCueSec"));
  assert.ok(!game.includes('"完美 +"'));
  assert.ok(engine.includes("gainCueSec: 1.0"));
});

check("金色区域使用左深右浅渐变", () => {
  assert.ok(/linear-gradient\(90deg,[\s\S]*rgba\(255, 205, 92/.test(game));
  assert.ok(game.includes("#energy-zone {"));
});

check("无效点击冷却有低刺激反馈，且不出现扣分/清空", () => {
  assert.ok(game.includes("等到黄色区域再跳哦"));
  assert.ok(game.includes('classList.toggle("cooling"'));
  assert.ok(game.includes("state.actions.cooldown_count += 1"));
  assert.ok(!game.includes("state.score -="));
  assert.ok(!game.includes("state.energy -="));
  assert.ok(!game.includes("state.energy = 0"));
});

check("报告与导出区分脑电基础分、实际分和冷却数据", () => {
  assert.ok(report.includes("本局游戏积分"));
  assert.ok(report.includes("平均脑电基础得分"));
  assert.ok(report.includes("平均实际得分"));
  assert.ok(report.includes("触发冷却"));
  assert.ok(exportPy.includes("每轮平均脑电基础得分"));
  assert.ok(exportPy.includes("每轮平均实际得分"));
  assert.ok(exportPy.includes("点击倍率"));
  assert.ok(exportPy.includes("冷却次数"));
  assert.ok(exportPy.includes("冷却时长（秒）"));
});

check("后端版本与逐轮字段已同步", () => {
  assert.ok(serverPy.includes('version="1.6.0"'));
  assert.ok(serverPy.includes("multiplier: Optional[float]"));
  assert.ok(serverPy.includes("cooldown_count: Optional[NonNegativeInt]"));
  assert.ok(serverPy.includes("cooldown_sec: Optional[float]"));
});

console.log("");
if (process.exitCode) console.log("static UI checks failed");
else console.log("all " + passed + " static UI checks passed");
