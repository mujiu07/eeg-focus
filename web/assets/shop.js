/* ============================================================
   专注小蛙 · 积分商城
   ------------------------------------------------------------
   · 入口排在成就与装扮之间
   · 积分 = 本局游戏积分按比例折算，局末结算；右上角显示余额
   · 成就专属（小红花 / 单片眼镜 / 学士帽 / 守护神系列）不在售
   · 其余装扮都能用积分买，5-18 分一件（肤色 ×1.5、背饰/头饰 ×1.2、手持 ×1.1，向上取整）
   ============================================================ */
(function () {
  "use strict";

  const ALL = "all";
  const CONFIRM_MS = 4200;

  let mask = null;
  let card = null;
  let chip = null;
  let chipCount = null;
  let grid = null;
  let filter = ALL;
  let pendingId = null;
  let pendingTimer = 0;
  let toastTimer = 0;
  let lastFocus = null;

  function walletPoints() {
    return window.Wallet ? window.Wallet.points() : 0;
  }

  function fmt(n) {
    return String(Math.max(0, Math.round(n))).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  // ---------- 入口 chip ----------
  function coinSvg() {
    return `<svg viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <circle cx="24" cy="24" r="15" fill="#f7c96b" stroke="#d9a441" stroke-width="2.4"/>
      <circle cx="24" cy="24" r="10.6" fill="none" stroke="#ffe9b5" stroke-width="1.8" opacity=".9"/>
      <path d="M24 15.6 27.2 21.6 33.8 22.5 29 27.1 30.2 33.6 24 30.5 17.8 33.6 19 27.1 14.2 22.5 20.8 21.6Z"
            fill="#8a5f14" opacity=".78"/>
      <path d="M15.4 17.2A12.6 12.6 0 0 1 22.4 12" fill="none" stroke="#fff6dc" stroke-width="2.2"
            stroke-linecap="round" opacity=".8"/>
    </svg>`;
  }

  function buildChip(entry) {
    entry.innerHTML = `
      <button type="button" class="shop-chip" id="shop-open" aria-haspopup="dialog" aria-label="积分商城">
        <span class="shop-chip__badge">${coinSvg()}</span>
        <span class="shop-chip__meta">
          <span class="shop-chip__title">商城</span>
          <span class="shop-chip__count" id="shop-chip-count">积分 0</span>
        </span>
      </button>`;
    chip = entry.querySelector("#shop-open");
    chipCount = entry.querySelector("#shop-chip-count");
    chip.addEventListener("click", function () { openPanel(); });
    refreshChip();
  }

  function refreshChip() {
    if (!chipCount) return;
    const n = walletPoints();
    chipCount.textContent = "积分 " + fmt(n);
    if (chip) chip.setAttribute("aria-label", "积分商城，余额 " + n + " 积分");
  }

  // ---------- 面板 ----------
  function buildPanel() {
    mask = document.createElement("div");
    mask.className = "shop-mask hidden";
    mask.id = "shop-mask";
    mask.innerHTML = `
      <div class="shop-sheet" role="dialog" aria-modal="true" aria-labelledby="shop-title">
        <button type="button" class="shop-close" id="shop-close" aria-label="关闭商城">
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5.5 5.5l9 9M14.5 5.5l-9 9" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>
        </button>
        <div class="shop-head">
          <div class="shop-head__icon">${coinSvg()}</div>
          <div class="shop-head__text">
            <h2 id="shop-title">积分商城</h2>
            <p>每局游戏积分按 30:1 折算为商城积分，整局结束后结算到账</p>
          </div>
          <div class="shop-balance" title="积分余额">
            <span class="shop-balance__label">积分余额</span>
            <strong class="shop-balance__num" id="shop-balance">0</strong>
          </div>
        </div>
        <div class="shop-filters" id="shop-filters" role="tablist" aria-label="商品分类"></div>
        <div class="shop-body">
          <div class="shop-grid" id="shop-grid"></div>
        </div>
        <p class="shop-foot">积分只保存在这台设备上。成就依然可以免费解锁装扮，商城是另一条捷径；成就专属装扮不在售。</p>
        <div class="shop-toast" id="shop-toast" role="status" aria-live="polite"></div>
      </div>`;
    document.body.appendChild(mask);
    card = mask.querySelector(".shop-sheet");
    grid = mask.querySelector("#shop-grid");

    mask.querySelector("#shop-close").addEventListener("click", closePanel);
    mask.addEventListener("click", function (event) {
      if (event.target === mask) closePanel();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && mask && !mask.classList.contains("hidden")) closePanel();
    });
    mask.querySelector("#shop-filters").addEventListener("click", function (event) {
      const btn = event.target.closest(".shop-filter");
      if (!btn) return;
      filter = btn.dataset.cat || ALL;
      clearPending(false);
      renderFilters();
      renderGrid();
    });
    grid.addEventListener("click", onGridClick);
  }

  function catsOfShop() {
    if (!window.DressUp) return [];
    // 分类筛选用全部类别，空分类也保留入口（点进去显示「还没有上架」）
    return DressUp.categories ? DressUp.categories() : [];
  }

  function renderFilters() {
    const box = mask.querySelector("#shop-filters");
    if (!box) return;
    const cats = catsOfShop();
    const opts = [{ id: ALL, name: "全部" }].concat(cats);
    box.innerHTML = opts.map(opt => `
      <button type="button" class="shop-filter${opt.id === filter ? " is-active" : ""}"
              role="tab" data-cat="${opt.id}" aria-selected="${opt.id === filter}">${opt.name}</button>`).join("");
  }

  function renderBalance() {
    const el = mask.querySelector("#shop-balance");
    if (el) el.textContent = fmt(walletPoints());
  }

  function renderGrid() {
    if (!grid || !window.DressUp) return;
    const points = walletPoints();
    const items = DressUp.shopItems().filter(item => filter === ALL || item.cat === filter);
    // 想买的（未拥有、买得起）排前面，其次买不起的，最后已拥有
    const rank = item => (item.owned ? 3 : item.price <= points ? 1 : 2);
    items.sort((a, b) => rank(a) - rank(b) || a.price - b.price || a.name.localeCompare(b.name, "zh"));

    if (!items.length) {
      grid.innerHTML = `<p class="shop-empty">这个分类还没有上架商品。</p>`;
      return;
    }

    grid.innerHTML = items.map(item => {
      const confirm = pendingId === item.id;
      let state = "";
      let foot = "";
      if (item.owned) {
        state = " is-owned";
        foot = `<span class="shop-card__price">已拥有</span>`;
      } else if (confirm) {
        state = " is-confirm";
        foot = `<span class="shop-card__price shop-card__price--go">再点一次 · ${item.price} 分</span>`;
      } else if (item.price > points) {
        state = " is-poor";
        foot = `<span class="shop-card__price">${item.price} 分</span>`;
      } else {
        foot = `<span class="shop-card__price">${item.price} 分</span>`;
      }
      return `
        <button type="button" class="shop-card${state}" data-id="${item.id}"
                aria-label="${item.name}，${item.price} 积分${item.owned ? "，已拥有" : ""}">
          <span class="shop-card__art">${DressUp.frogSvg({ [item.cat]: item.id })}</span>
          <span class="shop-card__name">${item.name}</span>
          <span class="shop-card__foot">
            <span class="shop-card__cat">${item.catName}</span>
            ${foot}
          </span>
          ${item.owned ? "" : `<span class="shop-card__coin" aria-hidden="true">${coinMini()}</span>`}
        </button>`;
    }).join("");
  }

  function coinMini() {
    return `<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="8" r="6.2" fill="#f7c96b" stroke="#d9a441" stroke-width="1.3"/>
      <path d="M8 5.2 9.1 7.2 11.3 7.5 9.6 9.1 10 11.3 8 10.2 6 11.3 6.4 9.1 4.7 7.5 6.9 7.2Z" fill="#8a5f14" opacity=".7"/>
    </svg>`;
  }

  function clearPending(rerender) {
    pendingId = null;
    clearTimeout(pendingTimer);
    if (rerender) renderGrid();
  }

  function onGridClick(event) {
    const btn = event.target.closest(".shop-card");
    if (!btn) return;
    const id = btn.dataset.id;
    const item = window.DressUp && DressUp.shopItems().find(x => x.id === id);
    if (!item) return;

    if (item.owned) {
      toast("已经拥有「" + item.name + "」了");
      return;
    }
    if (item.price > walletPoints()) {
      const lack = item.price - walletPoints();
      toast("还差 " + lack + " 积分 · 再攒一攒就能买下");
      return;
    }
    if (pendingId === id) {
      clearPending(false);
      const res = DressUp.buy(id);
      if (res.ok) {
        renderBalance();
        refreshChip();
        renderGrid();
        toast("已买下「" + res.name + "」，剩余 " + fmt(res.points) + " 积分");
      } else if (res.reason === "poor") {
        renderGrid();
        toast("积分不够了 · 需要 " + res.price + " 积分");
      } else {
        renderGrid();
        toast("暂时买不了「" + item.name + "」");
      }
      return;
    }
    pendingId = id;
    clearTimeout(pendingTimer);
    pendingTimer = setTimeout(function () { clearPending(true); }, CONFIRM_MS);
    renderGrid();
    toast("再点一次确认购买「" + item.name + "」· " + item.price + " 积分");
  }

  function toast(text) {
    const el = mask && mask.querySelector("#shop-toast");
    if (!el) return;
    el.textContent = text;
    el.classList.add("is-show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove("is-show"); }, 2400);
  }

  function openPanel() {
    if (!mask) buildPanel();
    lastFocus = document.activeElement;
    if (window.DressUp && DressUp.reloadOwned) DressUp.reloadOwned();
    mask.classList.remove("hidden");
    filter = ALL;
    pendingId = null;
    renderFilters();
    renderBalance();
    renderGrid();
    const closeBtn = mask.querySelector("#shop-close");
    if (closeBtn) closeBtn.focus({ preventScroll: true });
    document.addEventListener("keydown", trapFocus);
  }

  function closePanel() {
    if (!mask) return;
    mask.classList.add("hidden");
    clearPending(false);
    document.removeEventListener("keydown", trapFocus);
    if (lastFocus && typeof lastFocus.focus === "function") {
      lastFocus.focus({ preventScroll: true });
    }
  }

  function trapFocus(event) {
    if (event.key !== "Tab" || !card) return;
    const list = card.querySelectorAll(
      "button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"
    );
    if (!list.length) return;
    const first = list[0];
    const last = list[list.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  // ---------- 初始化 ----------
  function init() {
    const entry = document.getElementById("shop-entry");
    if (entry) buildChip(entry);

    window.addEventListener("bf:wallet", function () {
      refreshChip();
      if (mask && !mask.classList.contains("hidden")) {
        renderBalance();
        renderGrid();
      }
    });
    window.addEventListener("pageshow", function () {
      if (window.Wallet && Wallet.reload) Wallet.reload();
      refreshChip();
    });
  }

  window.Shop = {
    open: function () {
      if (!mask) buildPanel();
      openPanel();
    },
    close: closePanel,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
