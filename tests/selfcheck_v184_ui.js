#!/usr/bin/env node
/* v1.8.4 工作台/评估 UI 契约静态检查。 */
const fs = require("fs");
const path = require("path");
const root = path.resolve(__dirname, "..");
const read = p => fs.readFileSync(path.join(root, p), "utf8");
const game = read("web/game.html");
const dev = read("web/dev.html");
const monitor = read("web/assets/eeg-monitor.js");
const wb = read("web/assets/dev-workbench.js");
const round = read("web/assets/focus-round.js");
const storage = read("app/storage.py");
const server = read("app/server.py");
let passed = 0;
function check(name, condition, detail) {
  if (!condition) throw new Error(`${name} 失败 ${detail || ""}`);
  passed += 1; console.log("PASS " + name);
}

check("工作台保留三栏并增加标签页",
  game.includes('class="game-layout"') && game.includes('data-dw-tab="overview"')
  && game.includes('data-dw-pane="baseline"') && game.includes('data-dw-pane="difficulty"')
  && game.includes('data-dw-pane="diagnostics"') && game.includes('data-dw-pane="assessment"'));
check("左侧波形和中央游戏画布仍在",
  game.includes('id="mon-wave-canvas"') && game.includes('id="game-canvas"'));
check("儿童模式不创建监测或工作台",
  /if \(developerRun && window\.EEGMonitor\)/.test(game)
  && /if \(window\.DevWorkbench\)/.test(game)
  && !/DevWorkbench\.create\(\{\}\)/.test(game));
check("工作台只在开发者模式加载 API",
  wb.includes("/api/dev/workbench")
  && game.indexOf("DevWorkbench.create") > game.indexOf("if (developerRun && window.EEGMonitor)"));
check("标签页切换只改面板类名、不重建游戏",
  wb.includes("data-dw-pane") && wb.includes("classList.toggle(\"hidden\"")
  && !wb.includes("new FocusRound") && !wb.includes("game-canvas"));
check("双基线数据来自同一帧的 daily/reference",
  monitor.includes("daily: finite(f.daily_score)") && monitor.includes("reference: finite(f.reference_score)")
  && monitor.includes('line("daily"') && monitor.includes('line("reference"'));
check("双基线不插值且标出无效区间",
  monitor.includes("b.t - a.t > 1.5") && monitor.includes("不插值")
  && monitor.includes("baselinePoints"));
check("诊断面板显示依据且不是医学结论",
  wb.includes("evidenceText") && game.includes("不构成医学诊断")
  && game.includes("工程诊断") && !wb.includes("ADHD"));
check("难度控制明确只影响下一局",
  game.includes("修改只影响下一局") && game.includes("当前 Session 的参数快照不变"));
check("标准评估入口和横幅存在",
  game.includes('id="assessment-banner"') && game.includes('params.get("assessment") === "1"')
  && game.includes('protocol_version: "standard_v1"') && game.includes("planned_sec: 90"));
check("评估页面不写个人难度/不标记普通游戏",
  game.includes('body.purpose = "assessment"')
  && game.includes("if (profileUser && !assessmentRequested) Profile.markGame"));
check("标准评估使用服务端 seed",
  game.includes("FocusRound.makeRng(seed)") && round.includes("function makeRng(seed)"));
check("评估协议固定难度 1.00 且隔离奖励",
  server.includes("fixed_factor") && server.includes("assessment_isolated")
  && server.includes("assessment_reference_required"));
check("Schema v4 包含评估表和过程列",
  storage.includes("SCHEMA_VERSION = 4") && storage.includes("CREATE TABLE IF NOT EXISTS assessments")
  && storage.includes("charge_active_sec") && storage.includes("energy_loss"));
check("诊断导出默认不导出昵称/原始波形",
  wb.includes("/api/dev/diagnostics/") && wb.includes("res.content")
  && server.includes("nickname_exported") && server.includes("dev_export"));
check("开发者页提供工作台和评估入口",
  dev.includes("打开实时工作台") && dev.includes("标准评估 90s")
  && dev.includes("loadWorkbench") && dev.includes("wb-export-json"));
check("D 使用黄色区域入口减起始能量，而不是绝对位置",
  round.includes("this.zone.lo - this.startEnergy")
  && round.includes("computePotentialScore("));

console.log(`\n${passed} 项 v1.8.4 UI 契约检查通过`);
