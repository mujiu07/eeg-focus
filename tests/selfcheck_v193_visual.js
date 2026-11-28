/**
 * v1.9.3 全站视觉一致性静态验收
 * 运行：node tests/selfcheck_v193_visual.js
 *
 * 真实布局、弹窗和截图由 tests/browser_ui_v193.py 完成；这里固定：
 * 唯一小蛙几何、公共图标库、视觉变量、页面接入和角色 Emoji 清理契约。
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
const frogPages = ["index", "profiles", "calibrate", "growth", "report", "game"];

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
const page = name => read(`web/${name}.html`);

check("标准小蛙素材目录和渲染器存在", () => {
  assert.ok(exists("web/assets/frog/frog-art.js"));
  assert.ok(exists("web/assets/frog/frog-prototype.svg"));
  assert.ok(exists("web/assets/frog/README.md"));
  const art = read("web/assets/frog/frog-art.js");
  assert.ok(art.includes("PondEffects.frogEllipses"));
  assert.ok(art.includes("PondEffects.frogMouth"));
  assert.ok(art.includes("frog-eye-wrap"));
  assert.ok(art.includes("#346951"));
  assert.ok(art.includes("#609b68"));
  assert.ok(art.includes("#b9cf94"));
});

check("首页原型仍然是池塘青蛙，不被静态素材替换", () => {
  const home = page("index");
  assert.ok(home.includes('id="pondFrogArtwork"'));
  assert.ok(home.includes('id="pondFrogOutfitBack"'));
  assert.ok(home.includes('id="pondFrogOutfit"'));
  assert.ok(home.includes("assets/pond-effects.js"));
  assert.ok(home.includes("assets/frog/frog-art.js"));
  const effects = read("web/assets/pond-effects.js");
  assert.ok(effects.includes("frogEllipses"));
  assert.ok(effects.includes("#346951"));
  assert.ok(effects.includes("#609b68"));
  assert.ok(effects.includes("#b9cf94"));
});

check("所有页面接入公共视觉与图标规范", () => {
  for (const name of pages) {
    const html = page(name);
    assert.ok(html.includes("assets/icons/icons.css"), `${name} 缺少 icons.css`);
    assert.ok(html.includes("assets/visual-v193.css"), `${name} 缺少 visual-v193.css`);
    assert.ok(html.includes("assets/icons/icons.js"), `${name} 缺少 icons.js`);
  }
});

check("所有出现主角小蛙的页面复用 FrogArt/PondEffects", () => {
  for (const name of frogPages) {
    const html = page(name);
    assert.ok(html.includes("assets/frog/frog-art.js"), `${name} 未接入 FrogArt`);
    assert.ok(html.includes("assets/pond-effects.js"), `${name} 未接入 PondEffects`);
  }
});

check("页面不再使用系统青蛙 Emoji 作为主角", () => {
  const hits = [];
  const walk = dir => {
    for (const name of fs.readdirSync(dir)) {
      const p = path.join(dir, name);
      const st = fs.statSync(p);
      if (st.isDirectory()) { walk(p); continue; }
      if (!/\.(html|js)$/.test(name)) continue;
      const text = fs.readFileSync(p, "utf8");
      if (text.includes("🐸")) hits.push(path.relative(root, p));
    }
  };
  walk(path.join(root, "web"));
  assert.deepStrictEqual(hits, []);
});

check("青蛙眼睛分组不会被 CSS transform 覆盖位移", () => {
  const art = read("web/assets/frog/frog-art.js");
  assert.ok(art.includes('class="frog-eye-wrap" transform="translate('));
  assert.ok(art.includes('class="frog-eye frog-eye--'));
  const css = read("web/assets/icons/icons.css");
  assert.ok(css.includes(".frog-eye-wrap"));
  assert.ok(css.includes(".frog-art .frog-eye"));
});

check("主要页面的小蛙挂载点存在", () => {
  assert.ok(page("profiles").includes('data-frog="profile-hero"'));
  assert.ok(page("profiles").includes("avatarMarkup"));
  assert.ok(page("growth").includes('data-frog="growth-brand"'));
  assert.ok(page("growth").includes('data-frog="growth-scene"'));
  assert.ok(page("calibrate").includes('data-frog="calibrate"'));
  assert.ok(page("report").includes('data-frog="report-cheer"'));
  assert.ok(page("index").includes('data-frog="inline"'));
});

check("商城、装扮、游戏、成就动画共享同一几何", () => {
  const dress = read("web/assets/dressup.js");
  assert.ok(dress.includes("PondEffects"));
  assert.ok(dress.includes("frogEllipses"));
  assert.ok(read("web/assets/shop.js").includes("DressUp.frogSvg"));
  const cine = read("web/assets/achievement-cinematic.js");
  assert.ok(cine.includes("window.FrogArt"));
  assert.ok(cine.includes("FrogArt.svg"));
});

check("图标库使用统一 24 网格、1.8 描边和 data-icon 挂载", () => {
  const icons = read("web/assets/icons/icons.js");
  assert.ok(icons.includes("viewBox=\"0 0 24 24\""));
  assert.ok(icons.includes("stroke-width=\"1.8\""));
  assert.ok(icons.includes("data-icon"));
  assert.ok(icons.includes("function svg(name"));
  const pagesWithIcons = pages.filter(name => page(name).includes("data-icon"));
  assert.ok(pagesWithIcons.length >= 8, pagesWithIcons.join(","));
});

check("公共视觉变量和去重复描边规则存在", () => {
  const css = read("web/assets/visual-v193.css");
  assert.ok(css.includes("--v-line"));
  assert.ok(css.includes("--v-card-radius"));
  assert.ok(css.includes(".profile-card"));
  assert.ok(css.includes("border-color: transparent"));
  assert.ok(css.includes("#report .stat"));
  assert.ok(css.includes("a.stat"));
});

check("版本、变更记录和开发报告同步到 1.9.5", () => {
  assert.ok(read("app/server.py").includes('version="1.9.5"'));
  assert.ok(read("CHANGELOG.md").includes("## v1.9.5"));
  assert.ok(exists("docs/DEV-REPORT-v1.9.5.md"));
});

console.log("");
if (process.exitCode) console.log("v1.9.3 visual static checks failed");
else console.log(`${passed} 项 v1.9.3 视觉一致性静态检查通过`);
