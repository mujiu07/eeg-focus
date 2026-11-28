/* ============================================================
   专注小蛙 · 成就解锁动画
   播放时机：本局结束（结算卡片）之后、「专注报告」拉起之前。
   顺序：背景虚化变暗 → 小蛙举着金牌从左侧一跳一跳跳到画面中央
   → 转身面向玩家 → 把金牌递到镜头前、金牌放大发光 → 文案弹出，
   小蛙笑着在原地欢呼跳跃。点击 / 回车 / 空格可提前跳过。
   由 game.html 的 finishGame() 调用，只在本局真的解锁了新成就时播放。
   ============================================================ */
(function () {
  "use strict";

  const REDUCED = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  // 各阶段时长（毫秒），与 achievement-cinematic.css 里的动画时长对应
  const T = {
    veil: 400,     // 遮罩淡入 → 开始跳跃
    hop: 1500,     // 从左侧跳到中央
    face: 560,     // 转身面向玩家
    give: 980,     // 递出金牌、放大
    hold: 4000,    // 光晕 + 文案停留，可点击跳过
    out: 460,      // 淡出
  };

  let layer = null;
  let refs = null;
  let busy = false;
  let dismissNow = null;

  // ---------- 图形 ----------
  // 青蛙：正面蹲坐、圆润 Q 版。睁眼 / 笑眯眯、抿嘴 / 张口笑各一套，
  // 由 .is-burst 切换；两条手臂在递金牌时抬到胸前上方。
  // 使用全站唯一的小蛙几何（与首页池塘 / 游戏画布一致），只保留动作容器。
  const FROG_SVG = window.FrogArt
    ? window.FrogArt.svg({ className: "ach-cine-frog-art" })
    : "";
  // 金牌：红缎带 + 金圆牌 + 青蛙浮雕 + 高光
  const MEDAL_SVG = `
    <svg viewBox="0 0 140 190" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="achCineRibbon" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#e06a5d"/>
          <stop offset=".5" stop-color="#c24a42"/>
          <stop offset="1" stop-color="#9c2f30"/>
        </linearGradient>
        <linearGradient id="achCineGold" x1="24" y1="58" x2="118" y2="180" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#fff8d6"/>
          <stop offset=".4" stop-color="#ffd97c"/>
          <stop offset=".76" stop-color="#f0a93f"/>
          <stop offset="1" stop-color="#d88a26"/>
        </linearGradient>
        <radialGradient id="achCineGoldCore" cx=".36" cy=".28" r=".84">
          <stop offset="0" stop-color="#fffdf0"/>
          <stop offset=".55" stop-color="#ffe3a6"/>
          <stop offset="1" stop-color="#eaa63d"/>
        </radialGradient>
      </defs>

      <!-- 缎带：两条从牌顶向外上方张开的挂带 -->
      <path d="M27 9h24l10 71H33z" fill="url(#achCineRibbon)"/>
      <path d="M113 9H89l-10 71h28z" fill="url(#achCineRibbon)"/>
      <path d="M33 11h8l9 67h-8z" fill="#ffffff" opacity=".18"/>
      <path d="M107 11h-7l-9 67h8z" fill="#7d1f22" opacity=".2"/>
      <!-- 挂环：把带子和牌面连起来，避免两条带子像悬空的耳朵 -->
      <circle cx="70" cy="62" r="8.5" fill="none" stroke="#d9a441" stroke-width="5"/>
      <circle cx="70" cy="62" r="8.5" fill="none" stroke="#fff3c8" stroke-width="1.6" stroke-opacity=".65"/>

      <!-- 牌面 -->
      <circle cx="70" cy="126" r="56" fill="url(#achCineGold)" stroke="#b87c22" stroke-width="3"/>
      <circle cx="70" cy="126" r="45" fill="url(#achCineGoldCore)" stroke="#fff4cf" stroke-width="2.2" stroke-opacity=".85"/>
      <circle cx="70" cy="126" r="39" fill="none" stroke="#b8822c" stroke-width="1.6"
              stroke-opacity=".45" stroke-dasharray="3 6"/>

      <!-- 浮雕小青蛙 -->
      <circle cx="57" cy="112" r="11" fill="#fffaea" opacity=".95"/>
      <circle cx="83" cy="112" r="11" fill="#fffaea" opacity=".95"/>
      <circle cx="57" cy="113" r="4.6" fill="#96601a"/>
      <circle cx="83" cy="113" r="4.6" fill="#96601a"/>
      <path d="M56 134q14 13 28 0" fill="none" stroke="#96601a" stroke-width="4.2" stroke-linecap="round"/>
      <path d="M52 152q18 12 36 0" fill="none" stroke="#96601a" stroke-width="3.2" stroke-linecap="round" stroke-opacity=".55"/>

      <!-- 高光 -->
      <ellipse cx="43" cy="98" rx="14" ry="24" transform="rotate(-26 43 98)" fill="#ffffff" opacity=".24"/>
      <circle cx="104" cy="160" r="5" fill="#ffffff" opacity=".35"/>
    </svg>`;

  // ---------- DOM ----------
  function build() {
    if (layer) return;
    layer = document.createElement("div");
    layer.className = "ach-cine";
    layer.setAttribute("role", "dialog");
    layer.setAttribute("aria-modal", "true");
    layer.setAttribute("aria-label", "成就解锁");
    layer.innerHTML = `
      <div class="ach-cine__veil" aria-hidden="true"></div>
      <div class="ach-cine__stage">
        <div class="ach-cine__halo" aria-hidden="true"></div>
        <div class="ach-cine__rays" aria-hidden="true"></div>
        <div class="ach-cine__sparks" aria-hidden="true"></div>
        <div class="ach-cine__copy" role="status" aria-live="polite">
          <p class="ach-cine__kicker" data-ref="kicker">成 就 解 锁</p>
          <p class="ach-cine__title" data-ref="title"></p>
          <p class="ach-cine__desc" data-ref="desc"></p>
        </div>
        <div class="ach-cine__medal" aria-hidden="true">${MEDAL_SVG}</div>
        <div class="ach-cine__frog" aria-hidden="true">
          <div class="ach-cine__frog-hop">
            <span class="ach-cine__frog-shadow"></span>
            <span class="ach-cine__ripple"></span>
            <div class="ach-cine__frog-body">
              <div class="ach-cine__frog-tilt">${FROG_SVG}</div>
            </div>
          </div>
        </div>
        <p class="ach-cine__hint" data-ref="hint">点击任意处继续 ›</p>
      </div>`;
    document.body.appendChild(layer);
    refs = {
      kicker: layer.querySelector('[data-ref="kicker"]'),
      title: layer.querySelector('[data-ref="title"]'),
      desc: layer.querySelector('[data-ref="desc"]'),
      sparkBox: layer.querySelector(".ach-cine__sparks"),
    };
  }

  function fillCopy(items) {
    const one = items.length === 1;
    refs.kicker.textContent = one ? "成 就 解 锁" : "成 就 解 锁 × " + items.length;

    // 「恭喜你，获得 XX 成就！」：成就名单独成节点，方便上金色渐变
    refs.title.textContent = "";
    refs.title.appendChild(document.createTextNode(one ? "恭喜你，获得" : "恭喜你，一次获得"));
    const name = document.createElement("span");
    name.className = "ach-cine__name";
    name.textContent = one ? items[0].name : items.length + " 枚";
    refs.title.appendChild(name);
    refs.title.appendChild(document.createTextNode(one ? "成就！" : "成就！"));

    refs.desc.textContent = one
      ? (items[0].desc || "")
      : items.map(item => item.name).join(" · ");
  }

  // 金色粒子：位置、大小、时长都随机一点点，避免整齐排队的感觉
  function spawnSparks() {
    if (!refs || REDUCED) return;
    refs.sparkBox.textContent = "";
    for (let i = 0; i < 20; i += 1) {
      const dot = document.createElement("i");
      dot.style.left = (16 + Math.random() * 68).toFixed(1) + "%";
      dot.style.bottom = (8 + Math.random() * 36).toFixed(1) + "%";
      dot.style.setProperty("--s", (3.4 + Math.random() * 4.6).toFixed(1) + "px");
      dot.style.setProperty("--t", (2.1 + Math.random() * 1.6).toFixed(2) + "s");
      dot.style.setProperty("--d", (Math.random() * 2.2).toFixed(2) + "s");
      refs.sparkBox.appendChild(dot);
    }
  }

  // ---------- 等待与跳过 ----------
  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  // 停留阶段：点击 / 回车 / 空格 / Esc 立即继续，超时自动继续。
  // 前 700ms 不接管点击，避免玩家连点跳过整段动画。
  function holdForDismiss(ms) {
    return new Promise(resolve => {
      let settled = false;
      let timer = 0;
      let bindTimer = 0;

      const done = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        clearTimeout(bindTimer);
        layer.removeEventListener("pointerdown", onPress);
        document.removeEventListener("keydown", onKey);
        layer.classList.remove("is-ready");
        dismissNow = null;
        resolve();
      };
      const onPress = event => {
        if (event.cancelable) event.preventDefault();
        done();
      };
      const onKey = event => {
        if (event.key === "Enter" || event.key === " " || event.key === "Escape") {
          event.preventDefault();
          done();
        }
      };

      dismissNow = done;
      timer = setTimeout(done, ms);
      bindTimer = setTimeout(() => {
        if (settled) return;
        layer.addEventListener("pointerdown", onPress, { passive: false });
        document.addEventListener("keydown", onKey);
        if (!REDUCED) layer.classList.add("is-ready");
      }, 700);
    });
  }

  // ---------- 播放 ----------
  function reset() {
    layer.classList.remove("is-on", "is-hop", "is-face", "is-give", "is-burst", "is-off", "is-ready");
    layer.setAttribute("aria-hidden", "false");
    if (refs) refs.sparkBox.textContent = "";
  }

  function clear() {
    layer.classList.remove("is-hop", "is-face", "is-give", "is-burst", "is-ready");
    layer.setAttribute("aria-hidden", "true");
  }

  // 降低动态偏好：不跨越、不放大，静态卡片停留 2.2 秒
  async function playStill(items) {
    fillCopy(items);
    reset();
    void layer.offsetWidth;
    layer.classList.add("is-on", "is-face", "is-give", "is-burst");
    await holdForDismiss(2200);
    layer.classList.add("is-off");
    await sleep(200);
    layer.classList.remove("is-on", "is-off");
    clear();
  }

  async function play(list) {
    const items = (Array.isArray(list) ? list : []).filter(item => item && item.name);
    if (!items.length || busy) return;
    busy = true;
    build();
    try {
      fillCopy(items);
      reset();
      void layer.offsetWidth;

      if (REDUCED) {
        await playStill(items);
        return;
      }

      layer.classList.add("is-on");
      await sleep(T.veil);
      layer.classList.add("is-hop");
      await sleep(T.hop);
      layer.classList.add("is-face");
      await sleep(T.face);
      layer.classList.add("is-give");
      await sleep(T.give);
      spawnSparks();
      layer.classList.add("is-burst");
      await holdForDismiss(T.hold);

      layer.classList.add("is-off");
      await sleep(T.out);
      layer.classList.remove("is-on", "is-off");
      clear();
    } finally {
      dismissNow = null;
      busy = false;
    }
  }

  window.AchievementCinematic = {
    play: play,
    isPlaying: function () { return busy; },
    // 页面被关闭 / 跳转时立刻收起，避免残留在快照里
    stop: function () {
      if (dismissNow) dismissNow();
      if (layer) {
        layer.classList.remove("is-on", "is-hop", "is-face", "is-give", "is-burst", "is-ready");
        layer.classList.add("is-off");
      }
    },
  };
})();
