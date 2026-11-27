/**
 * v1.9.2 UI 结构与导航静态验收
 * 运行：node tests/selfcheck_v192_ui_static.js
 *
 * 这里只检查可静态确认的布局/导航契约；真实浏览器布局、Canvas 尺寸、
 * 侧栏切换和音乐控件矩形由 tests/browser_ui_v192.py 检查。
 */
"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const read = rel => fs.readFileSync(path.join(root, rel), "utf8");
const exists = rel => fs.existsSync(path.join(root, rel));
const pages = ["index", "profiles", "calibrate", "game", "report", "growth",
  "parent", "history", "settings", "dev"];

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
const readPage = name => read(`web/${name}.html`);

check("全站 UI 规范文件存在并已接入所有页面", () => {
  assert.ok(exists("web/assets/ui.css"), "ui.css missing");
  const css = read("web/assets/ui.css");
  assert.ok(css.includes(".home-link"));
  assert.ok(css.includes(".btn {"));
  assert.ok(css.includes("align-items: center"));
  for (const page of pages) {
    assert.ok(readPage(page).includes('assets/ui.css'), `${page} 未接入 ui.css`);
  }
});

check("所有非首页的主要页面都有清晰首页入口", () => {
  for (const page of pages) {
    if (page === "index") continue;
    const html = readPage(page);
    assert.ok(/home-link|btn-game-home|🏠\s*首页/.test(html), `${page} 缺少首页入口`);
    if (page !== "game") assert.ok(/href="index\.html"/.test(html), `${page} 首页入口目标错误`);
  }
});

check("首页不再重复开始游戏、装扮、设置和直接校准主入口", () => {
  const html = readPage("index");
  assert.strictEqual((html.match(/id="btn-start"/g) || []).length, 1);
  assert.ok(!html.includes("进入脑电校准"));
  assert.ok(!html.includes('id="btn-calib"'));
  assert.ok(!/onclick="document\.getElementById\('btn-start'\)/.test(html));
  assert.ok(html.includes('id="settings-entry"'));
  assert.ok((html.match(/DressUp && window\.DressUp\.open\(\)/g) || []).length === 1);
  assert.ok(!html.includes('id="dressup-entry"'), "顶部装扮入口与导航装扮重复");
});

check("开发者工作台保留独立可见入口", () => {
  const settings = readPage("settings");
  assert.ok(settings.includes('href="dev.html"'));
  assert.ok(settings.includes("开发者工作台"));
  const home = readPage("index");
  assert.ok(home.includes('href="settings.html"'));
});

check("侧栏折叠使用 grid-area，避免隐藏项导致中央列掉进 0px 列", () => {
  const game = readPage("game");
  const monitor = read("web/assets/eeg-monitor.css");
  assert.ok(game.includes('id="game-layout"'));
  assert.ok(monitor.includes("grid-template-areas: \"left main right\""));
  assert.ok(monitor.includes("grid-template-areas: \"main right\""));
  assert.ok(monitor.includes("grid-template-areas: \"left main\""));
  assert.ok(monitor.includes("grid-template-areas: \"main\""));
  assert.ok(!monitor.includes("html.monitor-mode .game-layout.left-off { --mon-left: 0px; }"));
  assert.ok(game.includes("max-width: 1120px"));
  assert.ok(read("web/assets/eeg-monitor.js").includes('window.dispatchEvent(new Event("resize"))'));
});

check("音乐控件在游戏页挂载至中央容器，不固定覆盖工作台", () => {
  const game = readPage("game");
  const music = read("web/assets/music.js");
  const vinyl = read("web/assets/vinyl.css");
  assert.ok(game.includes('data-music-host'));
  assert.ok(game.includes("game-music-host"));
  assert.ok(music.includes('querySelector("[data-music-host]")'));
  assert.ok(vinyl.includes(".game-music-host .vinyl-player"));
  assert.ok(vinyl.includes("body:not(.game-page) .vinyl-player"));
});

check("隐藏波形、暂停绘制与停止监测的语义文本", () => {
  const game = readPage("game");
  assert.ok(game.includes("隐藏波形面板（不停止监测）"));
  assert.ok(game.includes("暂停波形绘制（监测继续）"));
  assert.ok(read("web/assets/eeg-monitor.js").includes("显示波形"));
  assert.ok(read("web/assets/eeg-monitor.js").includes("显示算法"));
});

check("游戏和校准离开有确认、清理与当前档案保留路径", () => {
  const game = readPage("game");
  const cal = readPage("calibrate");
  assert.ok(game.includes("function leaveGame"));
  assert.ok(game.includes("endAbandonedSession"));
  assert.ok(game.includes("btn-game-home"));
  assert.ok(cal.includes("btn-home"));
  assert.ok(cal.includes("stopCalibration"));
  assert.ok(cal.includes("pagehide"));
});

check("全站本地链接无缺失页面", () => {
  const bad = [];
  for (const page of pages) {
    const html = readPage(page);
    for (const m of html.matchAll(/href="([^"]+)"/g)) {
      const href = m[1];
      if (!href || href.startsWith("#") || /^(https?:|mailto:|tel:|javascript:|data:)/.test(href)) continue;
      const clean = href.split(/[?#]/)[0];
      if (!clean) continue;
      assert.ok(exists(path.join("web", clean)), `${page} -> ${href}`);
      if (!exists(path.join("web", clean))) bad.push(`${page}:${href}`);
    }
  }
  assert.deepStrictEqual(bad, []);
});

check("公共按钮类采用水平/垂直居中且不机械修改信息卡", () => {
  const css = read("web/assets/ui.css");
  assert.ok(css.includes("justify-content: center"));
  assert.ok(css.includes("display: inline-flex"));
  assert.ok(css.includes(".btn {"));
  assert.ok(css.includes(".top-link"));
  assert.ok(css.includes(".ui-state"));
  assert.ok(!/\.stat\s*\{[^}]*text-align:\s*center/.test(css));
});

console.log("");
if (process.exitCode) console.log("v1.9.2 static UI checks failed");
else console.log(`${passed} 项 v1.9.2 静态 UI/导航检查通过`);
