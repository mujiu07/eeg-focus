/* ============================================================
 * 专注小蛙 · 公共图标库 v1.9.3
 * 统一的线性图标：24 × 24、圆角端点、1.8 描边。
 * 儿童端用柔和自然题材；家长/开发者端保持同一套视觉重量。
 * ============================================================ */
(function () {
  "use strict";

  var P = {
    home: '<path d="M4 11.2 12 4l8 7.2V20a1 1 0 0 1-1 1h-4.4v-5.2H9.4V21H5a1 1 0 0 1-1-1z"/>',
    signal: '<path d="M4 17a2 2 0 1 1 0 .1M8.5 17a6 6 0 0 0-1.8-4.2M12.5 17A10 10 0 0 0 4 7M4 4a13 13 0 0 1 13 13"/>',
    gamepad: '<path d="M7 8h10a4 4 0 0 1 3.3 6.2l-1.2 1.8a2.2 2.2 0 0 1-3.6-.1L14.2 14h-4.4l-1.3 1.9a2.2 2.2 0 0 1-3.6.1l-1.2-1.8A4 4 0 0 1 7 8Z"/><path d="M8 11v2M7 12h2M15.5 11.2h.1M17 13h.1"/>',
    device: '<rect x="5" y="3.5" width="14" height="17" rx="2.5"/><path d="M9 17.5h6M8.5 7h7v6h-7z"/>',
    sliders: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2.2"/><circle cx="9" cy="17" r="2.2"/>',
    flask: '<path d="M9 3.5h6M10 3.5v5.2l-5.2 9A2 2 0 0 0 6.5 21h11a2 2 0 0 0 1.7-3.3l-5.2-9V3.5"/><path d="M7.4 15h9.2"/>',
    eye: '<path d="M3.5 12s3.2-5.4 8.5-5.4 8.5 5.4 8.5 5.4-3.2 5.4-8.5 5.4S3.5 12 3.5 12Z"/><circle cx="12" cy="12" r="2.8"/>',
    clipboard: '<path d="M8 5H6.5A1.5 1.5 0 0 0 5 6.5v13A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5v-13A1.5 1.5 0 0 0 17.5 5H16"/><rect x="8" y="3" width="8" height="4" rx="1.2"/><path d="M8.5 11h7M8.5 15h5"/>',
    chat: '<path d="M4 5.5h16v10H9l-4 4v-4H4z"/><path d="M8 10.5h8"/>',
    lock: '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8.5 10V7.5a3.5 3.5 0 0 1 7 0V10"/>',
    tool: '<path d="M14.5 5.2a4.8 4.8 0 0 0-6.3 6.3L4 15.7V20h4.3l4.2-4.2a4.8 4.8 0 0 0 6.3-6.3l-2.7 2.7-3-3z"/>',
    settings: '<path d="M19.4 13.2a7.8 7.8 0 0 0 0-2.4l2-1.5-2-3.4-2.4 1a8 8 0 0 0-2-1.1L14.7 2h-4l-.4 2.8a8 8 0 0 0-2 1.1l-2.4-1-2 3.4 2 1.5a7.8 7.8 0 0 0 0 2.4l-2 1.5 2 3.4 2.4-1a8 8 0 0 0 2 1.1l.4 2.8h4l.4-2.8a8 8 0 0 0 2-1.1l2.4 1 2-3.4z"/><circle cx="12" cy="12" r="3.1"/>',
    user: '<circle cx="12" cy="8.2" r="3.2"/><path d="M5.5 20c.5-3.5 2.8-5.6 6.5-5.6s6 2.1 6.5 5.6"/>',
    hanger: '<path d="M12 5.4a2.5 2.5 0 1 1 2.4 2.5c-1.5 0-2.4.8-2.4 2.2v1.3"/><path d="m12 11.4-8 5.2c-.9.6-.5 1.8.6 1.8h14.8c1.1 0 1.5-1.2.6-1.8z"/>',
    hat: '<path d="M8 4h8v10H8z"/><path d="M4.8 14h14.4v2.4H4.8z"/><path d="M8 10h8"/>',
    sprout: '<path d="M12 20v-7.2"/><path d="M12 13.4C8.2 13.4 5.8 11 5.5 7.1c3.9.1 6.2 2.2 6.5 6.3Z"/><path d="M12 13.4c3.2 0 5.2-2 5.5-5.1-3.3.1-5.2 1.8-5.5 5.1Z"/>',
    family: '<circle cx="8" cy="8.2" r="2.4"/><circle cx="16.2" cy="9.2" r="2"/><path d="M3.8 19c.3-3.1 1.9-5 4.4-5s4.1 1.9 4.4 5"/><path d="M13.6 19c.2-2.5 1.3-4.1 3.2-4.1 1.9 0 3.1 1.6 3.3 4.1"/>',
    chart: '<path d="M4 20V4"/><path d="M4 20h16"/><rect x="7" y="12" width="3" height="5" rx="1"/><rect x="12" y="8" width="3" height="9" rx="1"/><rect x="17" y="5" width="3" height="12" rx="1"/>',
    search: '<circle cx="10.5" cy="10.5" r="5.8"/><path d="m15 15 4.5 4.5"/>',
    activity: '<path d="M3 12h4l2.2-6 4.2 12 2.2-6H21"/>',
    eeg: '<path d="M5 18c0-2.3 1.7-3.6 4.1-4.7l1.3-.6c-1.7-.8-2.5-2.1-2.5-3.7 0-2.2 1.7-3.8 3.9-3.8 2.4 0 4.2 1.7 4.5 4.3.8.2 1.4.9 1.4 1.8 0 1.1-.9 2-2 2h-1c-.5 2.9-2.3 4.7-5.1 4.7H5Z"/><path d="M8.5 9.5h2l1-2 1.4 4 1-1.5h3"/>',
    brain: '<path d="M9.2 5.1c-2.5.2-4.1 2-4 4.2-1.7.8-2 3.2-.6 4.4-.4 2.1 1 3.7 3.1 3.8.5 1.7 2.2 2.5 3.7 1.8V6.1c-.8-.7-1.5-1-2.2-1Z"/><path d="M14.8 5.1c2.5.2 4.1 2 4 4.2 1.7.8 2 3.2.6 4.4.4 2.1-1 3.7-3.1 3.8-.5 1.7-2.2 2.5-3.7 1.8V6.1c.8-.7 1.5-1 2.2-1Z"/>',
    trophy: '<path d="M8 4.5h8v5.2a4 4 0 0 1-8 0z"/><path d="M8 6.2H5.3c0 2 1.2 3.3 3.2 3.5M16 6.2h2.7c0 2-1.2 3.3-3.2 3.5"/><path d="M12 13.8v3.4M8.3 20h7.4l-.8-2.8H9.1z"/>',
    clock: '<circle cx="12" cy="12" r="8.2"/><path d="M12 7.4V12l3.1 1.9"/>',
    trend: '<path d="M4 19V5M4 19h16"/><path d="m6.5 15 3.4-3.6 3 2.2 4.8-5.1"/><path d="M14.4 8.5h3.3v3.3"/>',
    target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4.2"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/>',
    hourglass: '<path d="M7 3.8h10M7 20.2h10M8 3.8c0 3.6 1.4 5.3 4 6.3-2.6 1-4 2.7-4 6.3M16 3.8c0 3.6-1.4 5.3-4 6.3 2.6 1 4 2.7 4 6.3"/>',
    check: '<path d="m5.5 12.5 4.1 4.2L18.7 7.5"/>',
    shield: '<path d="M12 3.5 19 6v5.5c0 4-2.8 7.1-7 9-4.2-1.9-7-5-7-9V6z"/><path d="m9 12 2.1 2.1 4-4.1"/>',
    book: '<path d="M4.5 5.5c2.6-.9 5.1-.5 7.5 1.2v13c-2.4-1.7-4.9-2.1-7.5-1.2zM19.5 5.5c-2.6-.9-5.1-.5-7.5 1.2v13c2.4-1.7 4.9-2.1 7.5-1.2z"/>',
    star: '<path d="m12 3.8 2.5 5.1 5.6.8-4 3.9.9 5.6-5-2.7-5 2.7.9-5.6-4-3.9 5.6-.8z" fill="currentColor" stroke="none"/>',
    leaf: '<path d="M5 19c0-7 4.3-11 14-11-1 7.5-5.3 11-11.7 11H5Z"/><path d="M5 19c3.4-3.5 6.6-6.4 10.5-8.8"/>',
    crown: '<path d="m4.5 8 3.4 3 4.1-6 4.1 6 3.4-3-1.3 10.5H5.8z"/><path d="M6 20.2h12"/>',
    medal: '<circle cx="12" cy="14.5" r="4.8"/><path d="m8 4 2.4 5.1M16 4l-2.4 5.1M12 12.5l.8 1.6 1.8.3-1.3 1.2.3 1.8-1.6-.9-1.6.9.3-1.8-1.3-1.2 1.8-.3z"/>',
    coin: '<circle cx="12" cy="12" r="8"/><path d="M12 7.8v8.4M9.4 10h4a1.8 1.8 0 0 1 0 3.6h-3.2a1.8 1.8 0 0 0 0 3.6h4.2"/>',
    moon: '<path d="M19.2 14.4A7.5 7.5 0 0 1 9.6 4.8a7.8 7.8 0 1 0 9.6 9.6Z"/>',
    sun: '<circle cx="12" cy="12" r="3.8"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4"/>',
    sunrise: '<path d="M4 18h16M7 15.3a5 5 0 0 1 10 0M12 4v4M5.6 9.6 7 11M18.4 9.6 17 11"/>',
    sunset: '<path d="M4 18h16M7 15.3a5 5 0 0 1 10 0M12 4v4M5.6 9.6 7 11M18.4 9.6 17 11"/>',
    auto: '<path d="M12 4a7 7 0 0 1 0 14 7 7 0 0 0 0-14Z" fill="currentColor" stroke="none"/><circle cx="12" cy="11" r="7"/>',
    palette: '<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.6 0 2.3-.8 2.3-1.8 0-1.2-1.2-1.6-1.2-2.8 0-.9.7-1.5 1.7-1.5h1.7c2.2 0 3.5-1.3 3.5-3.4 0-4.2-3.6-7.5-8-7.5Z"/><circle cx="7.8" cy="10" r="1"/><circle cx="10.2" cy="7.2" r="1"/><circle cx="14" cy="7.1" r="1"/><circle cx="16.4" cy="9.7" r="1"/>',
    music: '<path d="M9 18V6.5l9-2v11.2"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="15.5" cy="15.7" r="2.5"/>',
    speaker: '<path d="M4 10h3l4-3v10l-4-3H4z"/><path d="M15 9.2a4 4 0 0 1 0 5.6M17.6 7a7.4 7.4 0 0 1 0 10"/>',
    gift: '<path d="M4.5 10h15v10h-15z"/><path d="M3.5 7h17v3h-17zM12 7v13"/><path d="M12 7C9.5 7 7 5.8 7 4.2 7 3.1 7.9 2.5 9 2.5c2 0 3 2.2 3 4.5ZM12 7c2.5 0 5-1.2 5-2.8 0-1.1-.9-1.7-2-1.7-2 0-3 2.2-3 4.5Z"/>',
    close: '<path d="m6 6 12 12M18 6 6 18"/>',
    arrowLeft: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    arrowRight: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    refresh: '<path d="M19 8a8 8 0 1 0 1 7"/><path d="M19 3.5V8h-4.5"/>',
    lock: '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8.5 10V7.5a3.5 3.5 0 0 1 7 0V10"/>',
    download: '<path d="M12 3v12M7.5 10.5 12 15l4.5-4.5M4 20h16"/>',
    folder: '<path d="M3.5 6.5h6l2 2h9v10.5h-17z"/>',
    upload: '<path d="M12 16V4M7.5 8.5 12 4l4.5 4.5M4 20h16"/>',
    heart: '<path d="M12 20s-7.2-4.4-7.2-9.2A4 4 0 0 1 12 8a4 4 0 0 1 7.2 2.8C19.2 15.6 12 20 12 20Z"/>',
    sparkles: '<path d="m12 3 1.4 4.1L17.5 8.5l-4.1 1.4L12 14l-1.4-4.1-4.1-1.4 4.1-1.4zM18.5 14l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
    warning: '<path d="M12 4 21 20H3z"/><path d="M12 9v5M12 17.3v.2"/>',
    fish: '<path d="M4 12c3-3.8 8-4.8 12-2.8L19 6v12l-3-3.2C12 17 7 16 4 12Z"/><circle cx="15.2" cy="10.9" r=".9" fill="currentColor" stroke="none"/>',
    lotus: '<path d="M12 19c-4.2 0-7-2.4-7-5.5 3.1.1 5.4 1.7 7 4.5 1.6-2.8 3.9-4.4 7-4.5 0 3.1-2.8 5.5-7 5.5Z"/><path d="M12 19c-1.8-2.5-2.4-4.8-2-6.6 1.5.5 2.2 1.8 2 3.8 1.8-2.5 3.2-3.3 5.1-3.3-.8 2.1-2.4 3.8-5.1 6.1Z"/>',
    dragonfly: '<circle cx="12" cy="5.8" r="2.1"/><path d="M12 8v11M11.2 9 5 6M12.8 9l6.2-3M11.2 12 5 11M12.8 12l6.2-1"/><path d="M8 5 5.8 5.4M16 5l2.2.4"/>',
    snail: '<path d="M4 18h13.5A3.5 3.5 0 0 0 21 14.5c0-3-2.4-5.5-5.5-5.5-2 0-3.4.8-4.3 2.1"/><path d="M8 18a4 4 0 1 1 4-4c0 2.2-1.8 4-4 4Z"/><path d="M4 8V5.2M4 5 5.4 3.7"/>',
    tadpole: '<circle cx="14.5" cy="9.5" r="4.2"/><path d="M10.5 11.5c-3 .5-5 2.4-6.5 6M11.8 13.5c-2.2 1.8-3.4 4-3.8 6.5"/><circle cx="15.8" cy="8.6" r=".8" fill="currentColor" stroke="none"/>',
    turtle: '<ellipse cx="12" cy="13" rx="7" ry="5.5"/><path d="M5 13c-1.2 0-2 .7-2.5 1.5M19 13c1.2 0 2 .7 2.5 1.5M9 18.5v1.5M15 18.5v1.5"/><path d="M9 10.5h6M12 8v10"/>',
    duck: '<path d="M5 15c1-2.6 3.2-4 6-4h3.2c1.5 0 2.6 1 3 2.3l1.4.4c.8.2 1 1.3.3 1.8-1.3 1-2.6 1.4-4 1.4H8.5C7 17.9 5.8 16.8 5 15Z"/><circle cx="15.5" cy="8.6" r="2.3"/><path d="m17.8 8.8 2.2.6-2.1.8M7 18.5v1.2M12 18.5v1.2"/>',
    swan: '<path d="M5 17c2-1.4 3-3.4 3-6 0-3.2 1.6-5.4 4.2-5.4 2 0 3.3 1.2 3.3 3 0 1.5-1 2.5-2.4 2.5"/><path d="M5 17h9c2.8 0 4.6-1.2 5.5-3.5l1.2.2-1 2.2.8 2.1-2.3.6"/><path d="M9 19.5v1M14 19.5v1"/>',
    dragon: '<path d="M4 16c2.8-1.2 4.4-3.2 5-6l2.2 1.8L13 9c.8-2 2.4-3 4.7-3 1.4 0 2.4.6 3 1.8l-2.1.7.8 1.7c1.2 2.5.3 5-2.5 6.6-2.3 1.3-5.2 1.7-8.2 1.1L4 16Z"/><path d="M8 13.8c-1.2 1.2-2 2.7-2.2 4.4M14 9l1.5-3"/>',
    tree: '<path d="M12 3 6.5 10h3L5.5 15h13l-4-5h3z"/><path d="M12 15v5M9 20h6"/>',
    cap: '<path d="m3.5 9.5 8.5-4 8.5 4-8.5 4z"/><path d="M7 11.5v4.2c0 1.2 2.2 2.3 5 2.3s5-1.1 5-2.3v-4.2M20.5 9.5v5"/>',
    bookBlue: '<path d="M4.5 5.5c2.6-.9 5.1-.5 7.5 1.2v13c-2.4-1.7-4.9-2.1-7.5-1.2z" fill="#e4f1ff"/><path d="M19.5 5.5c-2.6-.9-5.1-.5-7.5 1.2v13c2.4-1.7 4.9-2.1 7.5-1.2z" fill="#f2f8ff"/>',
    bookGreen: '<path d="M4.5 5.5c2.6-.9 5.1-.5 7.5 1.2v13c-2.4-1.7-4.9-2.1-7.5-1.2z" fill="#e4f8eb"/><path d="M19.5 5.5c-2.6-.9-5.1-.5-7.5 1.2v13c2.4-1.7 4.9-2.1 7.5-1.2z" fill="#f2fff7"/>',
    bookAmber: '<path d="M4.5 5.5c2.6-.9 5.1-.5 7.5 1.2v13c-2.4-1.7-4.9-2.1-7.5-1.2z" fill="#fff3d9"/><path d="M19.5 5.5c-2.6-.9-5.1-.5-7.5 1.2v13c2.4-1.7 4.9-2.1 7.5-1.2z" fill="#fffaf0"/>',
    bookRed: '<path d="M4.5 5.5c2.6-.9 5.1-.5 7.5 1.2v13c-2.4-1.7-4.9-2.1-7.5-1.2z" fill="#ffe9e4"/><path d="M19.5 5.5c-2.6-.9-5.1-.5-7.5 1.2v13c2.4-1.7 4.9-2.1 7.5-1.2z" fill="#fff6f3"/>',
  };

  var FILLED = { star: true, auto: true, sparkles: true, warning: false };

  function svg(name, className) {
    var body = P[name] || P.leaf;
    var fill = FILLED[name] ? "currentColor" : "none";
    return '<svg class="ui-icon' + (className ? " " + className : "") +
      '" viewBox="0 0 24 24" fill="' + fill + '" stroke="currentColor" stroke-width="1.8" ' +
      'stroke-linecap="round" stroke-linejoin="round" focusable="false" aria-hidden="true">' + body + "</svg>";
  }

  function mountAll(root) {
    var scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("[data-icon]").forEach(function (el) {
      if (el.getAttribute("data-icon-ready") === "1") return;
      var name = el.getAttribute("data-icon");
      el.innerHTML = svg(name);
      el.classList.add("ui-icon-host");
      el.setAttribute("data-icon-ready", "1");
    });
  }

  window.Icons = {
    version: "1.9.3",
    svg: svg,
    markup: function (name, className) { return svg(name, className); },
    mountAll: mountAll,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { mountAll(document); });
  } else {
    mountAll(document);
  }
})();
