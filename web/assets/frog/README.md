# 专注小蛙 · 标准角色素材

## 唯一原型

`web/index.html` 首页池塘中的小蛙由 `PondEffects.frogEllipses` 与
`PondEffects.frogMouth` 实时绘制，颜色为：

- 深绿 `#346951`
- 身体 `#609b68`
- 肚皮 `#b9cf94`
- 眼白 `#fbf3d9`
- 瞳孔 `#263b33`

不要重新设计眼睛、身体比例、面部特征或基础配色。

## 文件

- `frog-art.js`：全站 SVG 渲染器，优先读取 `window.PondEffects`，否则使用同一份内置几何兜底。
- `frog-prototype.svg`：透明背景的标准静态预览，用于文档和视觉对照。

## 调用方式

静态页面：

```html
<script src="assets/pond-effects.js"></script>
<script src="assets/frog/frog-art.js"></script>
<div data-frog="alias" aria-hidden="true"></div>
```

动态模板：

```js
const art = FrogArt.svg({ className: "my-frog", expression: "open" });
```

- 主角形象必须使用 `FrogArt.svg()` 或 `data-frog`。
- 表情只允许在标准几何上做眼睛/嘴巴变化，不得改变身体比例、基础配色和眼睛位置。
- 商城、装扮、游戏画布继续共享 `PondEffects` 几何，不另起素材。
- 禁止使用系统青蛙 Emoji 作为主角。
