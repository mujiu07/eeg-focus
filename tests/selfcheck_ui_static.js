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
const monitorJs = read("web/assets/eeg-monitor.js");
const monitorCss = read("web/assets/eeg-monitor.css");
const profilesHtml = read("web/profiles.html");
const settingsHtml = read("web/settings.html");
const profileBridge = read("web/assets/profile-bridge.js");
const storagePy = read("app/storage.py");
const accountsPy = read("app/accounts.py");

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
  assert.ok(serverPy.includes('version="1.9.5"'));
  assert.ok(serverPy.includes("multiplier: Optional[float]"));
  assert.ok(serverPy.includes("cooldown_count: Optional[NonNegativeInt]"));
  assert.ok(serverPy.includes("cooldown_sec: Optional[float]"));
});

check("开发者模式三栏布局与监测面板隔离", () => {
  assert.ok(game.includes('id="game-layout"'));
  assert.ok(game.includes('class="monitor-panel monitor-left"'));
  assert.ok(game.includes('class="monitor-panel monitor-right"'));
  assert.ok(game.includes('assets/eeg-monitor.css'));
  assert.ok(game.includes('assets/eeg-monitor.js'));
  assert.ok(game.includes('if (developerRun && window.EEGMonitor)'));
  assert.ok(monitorCss.includes('html.monitor-mode .monitor-panel'));
  assert.ok(monitorCss.includes('grid-template-columns'));
});

check("监测只消费真实窗口、序号与算法中间结果", () => {
  assert.ok(game.includes('monitor?.ingestFrame(f)'));
  assert.ok(monitorJs.includes('b.raw'));
  assert.ok(monitorJs.includes('b.processed'));
  assert.ok(monitorJs.includes('sample_seq0'));
  assert.ok(monitorJs.includes('time_basis'));
  assert.ok(!monitorJs.includes('Math.random'));
  assert.ok(serverPy.includes('/api/session/{sid}/monitor'));
  assert.ok(serverPy.includes('take_monitor_window'));
  assert.ok(serverPy.includes('last_debug'));
  assert.ok(serverPy.includes('monitor_data.build_batch'));
});

check("监测面板覆盖频段、算法、分数、事件与状态", () => {
  for (const id of ["mon-wave-canvas", "mon-band-canvas", "mon-score-canvas",
    "mon-algo", "mon-status", "mon-events", "mon-band-history"]) {
    assert.ok(game.includes(`id="${id}"`), id);
  }
  assert.ok(monitorJs.includes('游戏驱动分数'));
  assert.ok(monitorJs.includes('当前信号源'));
  assert.ok(monitorJs.includes('本局累计积分'));
  assert.ok(monitorJs.includes('signal_lost'));
  assert.ok(monitorJs.includes('score_settle'));
  assert.ok(monitorJs.includes('canvas'));
});

check("个人档案页、编辑、删除与最近使用入口", () => {
  assert.ok(profilesHtml.includes("今天谁来陪小蛙玩？"));
  assert.ok(profilesHtml.includes("新建档案"));
  assert.ok(profilesHtml.includes("data-edit"));
  assert.ok(profilesHtml.includes("data-delete"));
  assert.ok(profilesHtml.includes("bf-active-user"));
  assert.ok(profileBridge.includes("applyBootstrap"));
  assert.ok(profileBridge.includes("/sync"));
  assert.ok(profileBridge.includes("legacySnapshot"));
});

check("本地目录、备份恢复与隐私提示", () => {
  assert.ok(settingsHtml.includes("数据目录"));
  assert.ok(settingsHtml.includes("立即备份"));
  assert.ok(settingsHtml.includes("恢复"));
  assert.ok(settingsHtml.includes("SQLite 未做静态加密"));
  assert.ok(storagePy.includes("Documents"));
  assert.ok(storagePy.includes("cloud_sync_hint"));
  assert.ok(storagePy.includes("PRAGMA foreign_keys = ON"));
  assert.ok(storagePy.includes("wallet_transactions"));
  assert.ok(storagePy.includes("schema_version"));
  assert.ok(accountsPy.includes("/storage/backup"));
  assert.ok(accountsPy.includes("/profiles/{user_id}/sync"));
});

check("用户归属、结算幂等与 Session TTL 留在后端", () => {
  assert.ok(serverPy.includes("def _session_for"));
  assert.ok(serverPy.includes("SESSION_RETENTION_SEC"));
  assert.ok(serverPy.includes("_reap_sessions"));
  assert.ok(storagePy.includes("idempotency_key"));
  assert.ok(serverPy.includes("user_id"));
  assert.ok(storagePy.includes("session:{session_id}"));
  assert.ok(storagePy.includes("load_report"));
  assert.ok(!serverPy.includes("SESSIONS_DIR, f\"{s.id}.json\", \"w\""));
});

check("v1.8.3 自适应难度只进入开发者端", () => {
  const dev = read("web/dev.html");
  assert.ok(dev.includes("个体自适应难度"));
  assert.ok(dev.includes("/difficulty"));
  assert.ok(dev.includes("锁定当前难度"));
  assert.ok(dev.includes("恢复标准 1.00"));
  assert.ok(game.includes("applyDifficulty(res.difficulty)"));
  assert.ok(game.includes("incomplete_round"));
  assert.ok(engine.includes("evalSec"));
  assert.ok(engine.includes("pendingRound"));
  assert.ok(serverPy.includes("difficulty_snapshot"));
  assert.ok(serverPy.includes("record_difficulty"));
  assert.ok(storagePy.includes("difficulty_profiles"));
  assert.ok(accountsPy.includes("/profiles/{user_id}/difficulty"));
  const childText = game.replace(/<script[\s\S]*?<\/script>/g, "");
  assert.ok(!childText.includes("自动难度") && !childText.includes("难度系数"));
});

check("v1.8.2 每日校准与双基线入口", () => {
  const calibrate = read("web/calibrate.html");
  const profilesPage = read("web/profiles.html");
  assert.ok(calibrate.includes("daily_v2") && calibrate.includes("stage_windows"));
  assert.ok(calibrate.includes("tutorialEvents") && calibrate.includes("自然观察"));
  assert.ok(calibrate.includes('purpose = "calibration"') || calibrate.includes("purpose = 'calibration'"));
  assert.ok(game.includes('purpose: "game"') && game.includes("daily_calibration_required"));
  assert.ok(profilesPage.includes("calibration_status") && profilesPage.includes("今日校准"));
  assert.ok(read("web/assets/api.js").includes("4 * 60 * 60 * 1000"));
});

console.log("");
if (process.exitCode) console.log("static UI checks failed");
else console.log("all " + passed + " static UI checks passed");
