/* ============================================================
 * 专注小蛙 · 全站小蛙角色渲染器 v1.9.3
 *
 * 唯一原型来源：PondEffects.frogEllipses / PondEffects.frogMouth
 * 首页池塘、游戏画布、商城、装扮、成长页、报告、成就动画都从这里取形。
 * 本文件只负责把同一份几何输出成 SVG，不重新设计角色。
 * ============================================================ */
(function () {
  "use strict";

  var FALLBACK_ELLIPSES = [
    [0, 17, 29, 9, "#346951"],
    [0, 7, 24, 22, "#609b68"],
    [0, 13, 16, 13, "#b9cf94"],
    ...[-14, 14].flatMap(function (x) {
      return [
        [x, -12, 10, 11, "#609b68"],
        [x, -12, 6, 7, "#fbf3d9"],
        [x + 1, -12, 3, 4, "#263b33"],
      ];
    }),
  ];
  var FALLBACK_MOUTH = { start: [-8, 5], curve: [0, 10, 8, 5], color: "#346951", width: 2 };

  function geometry() {
    var shared = window.PondEffects;
    var ellipses = shared && Array.isArray(shared.frogEllipses) && shared.frogEllipses.length
      ? shared.frogEllipses
      : FALLBACK_ELLIPSES;
    var mouth = shared && shared.frogMouth && shared.frogMouth.start
      ? shared.frogMouth
      : FALLBACK_MOUTH;
    return { ellipses: ellipses, mouth: mouth };
  }

  function shapeTag(shape) {
    return '<ellipse cx="' + shape[0] + '" cy="' + shape[1] + '" rx="' + shape[2] +
      '" ry="' + shape[3] + '" fill="' + shape[4] + '"/>';
  }

  function eyesMarkup(expression) {
    if (expression === "smile") {
      return '<g class="frog-eyes frog-eyes--smile">' +
        '<ellipse cx="-14" cy="-12" rx="10" ry="11" fill="#609b68"/>' +
        '<ellipse cx="14" cy="-12" rx="10" ry="11" fill="#609b68"/>' +
        '<path d="M-20 -13 Q-14 -7 -8 -13" fill="none" stroke="#263b33" stroke-width="2.4" stroke-linecap="round"/>' +
        '<path d="M8 -13 Q14 -7 20 -13" fill="none" stroke="#263b33" stroke-width="2.4" stroke-linecap="round"/>' +
        "</g>";
    }
    var left = [
      [0, 0, 10, 11, "#609b68"],
      [0, 0, 6, 7, "#fbf3d9"],
      [1, 0, 3, 4, "#263b33"],
    ];
    var right = [
      [0, 0, 10, 11, "#609b68"],
      [0, 0, 6, 7, "#fbf3d9"],
      [-1, 0, 3, 4, "#263b33"],
    ];
    function eye(parts, x, side) {
      return '<g class="frog-eye-wrap" transform="translate(' + x + ' -12)">' +
        '<g class="frog-eye frog-eye--' + side + '">' +
        parts.map(function (p) {
          return '<ellipse cx="' + p[0] + '" cy="' + p[1] + '" rx="' + p[2] + '" ry="' + p[3] +
            '" fill="' + p[4] + '"/>';
        }).join("") + "</g></g>";
    }
    return '<g class="frog-eyes frog-eyes--open">' + eye(left, -14, "l") + eye(right, 14, "r") + "</g>";
  }

  function mouthMarkup(mouth, expression) {
    var d = "M " + mouth.start.join(" ") + " Q " + mouth.curve.join(" ");
    if (expression === "open") {
      return '<g class="frog-mouth-group">' +
        '<path class="frog-mouth frog-mouth--line" d="' + d + '" fill="none" stroke="' + mouth.color +
        '" stroke-width="' + mouth.width + '"/>' +
        '<path class="frog-mouth frog-mouth--open" d="M-8 5 Q0 17 8 5 Z" fill="' + mouth.color +
        '" stroke="none" opacity="0"/>' +
        "</g>";
    }
    return '<path class="frog-mouth" d="' + d + '" fill="none" stroke="' + mouth.color +
      '" stroke-width="' + mouth.width + '" stroke-linecap="round"/>';
  }

  function svg(options) {
    options = options || {};
    var g = geometry();
    var expression = options.expression || "open";
    var ellipses = g.ellipses.filter(function (shape) {
      // 眼睛和嘴由本渲染器重新分组，避免出现两套眼睛。
      return !(shape[3] === 11 || shape[3] === 7 || shape[3] === 4);
    });
    var body = ellipses.map(shapeTag).join("");
    var className = options.className ? " " + options.className : "";
    // 头像专用紧凑视口：去掉透明留白，让小蛙在圆角头像里视觉居中。
    var viewBox = options.viewBox || (options.compact ? "-31.5 -30 63 63" : "-40 -37 80 80");
    var label = options.label
      ? ' role="img" aria-label="' + String(options.label).replace(/"/g, "&quot;") + '"'
      : ' aria-hidden="true"';
    return '<svg class="frog-art' + className + '" viewBox="' + viewBox + '" focusable="false"' + label + ">" +
      '<g class="frog-art__body">' + body + "</g>" +
      eyesMarkup(expression) +
      mouthMarkup(g.mouth, expression) +
      "</svg>";
  }

  function mount(el, options) {
    if (!el) return null;
    var opts = Object.assign({}, options || {});
    if (!opts.expression) opts.expression = el.getAttribute("data-frog-expression") || "open";
    if (!opts.label) opts.label = el.getAttribute("aria-label") || "";
    if (opts.label) el.removeAttribute("aria-label");
    el.classList.add("frog-art-host");
    el.innerHTML = svg(opts);
    return el.firstElementChild;
  }

  function mountAll(root) {
    var scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("[data-frog]").forEach(function (el) {
      if (el.getAttribute("data-frog-ready") === "1") return;
      mount(el);
      el.setAttribute("data-frog-ready", "1");
    });
  }

  window.FrogArt = {
    version: "1.9.4",
    svg: svg,
    mount: mount,
    mountAll: mountAll,
    geometry: geometry,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { mountAll(document); });
  } else {
    mountAll(document);
  }
})();
