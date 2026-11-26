/* ============================================================
   专注小蛙 · 积分钱包
   ------------------------------------------------------------
   · 积分 = 本局游戏积分按固定比例折算（默认 max(1, floor(本局积分 / 30))，有得分时）
   · 游戏积分与商城货币分离：单轮 20–100 分不会直接放大商城经济
   · 以「局」为单位累计：局内不实时入账，本局结束时一次结算
   · 余额只保存在本机 localStorage（bf-wallet），不上传、不联网
   ============================================================ */
(function () {
  "use strict";

  const KEY = "bf-wallet";
  const VERSION = 1;

  function blank() {
    return { v: VERSION, points: 0, rounds: 0, jumps: 0, spent: 0 };
  }

  function read() {
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(KEY)); } catch (_) { raw = null; }
    const out = blank();
    if (!raw || typeof raw !== "object") return out;
    ["points", "rounds", "jumps", "spent"].forEach(key => {
      const n = Number(raw[key]);
      if (Number.isFinite(n) && n > 0) out[key] = Math.floor(n);
    });
    return out;
  }

  let state = read();

  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) { /* 隐私模式忽略 */ }
  }

  function stats() {
    return { points: state.points, rounds: state.rounds, jumps: state.jumps, spent: state.spent };
  }

  function emit() {
    try {
      window.dispatchEvent(new CustomEvent("bf:wallet", { detail: stats() }));
    } catch (_) { /* 老浏览器忽略 */ }
  }

  // 一局结束：把折算后的积分一次性记入
  function settleRound(score) {
    const n = Math.max(0, Math.floor(Number(score) || 0));
    state.rounds += 1;
    if (n) {
      state.points += n;
      state.jumps += n;   // 沿用旧字段名，记录累计入账分值
    }
    save();
    emit();
    return n;
  }

  function add(n) {
    const gain = Math.max(0, Math.floor(Number(n) || 0));
    if (!gain) return 0;
    state.points += gain;
    save();
    emit();
    return gain;
  }

  function spend(n) {
    const cost = Math.max(0, Math.floor(Number(n) || 0));
    if (!cost) return true;
    if (state.points < cost) return false;
    state.points -= cost;
    state.spent += cost;
    save();
    emit();
    return true;
  }

  function reset() {
    state = blank();
    save();
    emit();
  }

  // 存储键被外部改写时（例如测试脚本直接写 localStorage），重新载入
  function reload() {
    state = read();
    emit();
    return stats();
  }

  window.Wallet = {
    key: KEY,
    points: function () { return stats().points; },
    stats: stats,
    settleRound: settleRound,
    add: add,
    spend: spend,
    reset: reset,
    reload: reload,
  };
})();
