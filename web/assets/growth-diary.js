/* v1.9.0 小蛙成长日记：只展示真实正式游戏记录，不展示脑电分数。 */
(function () {
  "use strict";
  const C = window.GrowthCommon;

  function set(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function renderRecent(days) {
    const box = document.getElementById("growth-week");
    if (!box) return;
    const dows = ["日", "一", "二", "三", "四", "五", "六"];
    box.innerHTML = (days || []).map(day => {
      const date = new Date(day.date + "T12:00:00");
      const mins = day.played_sec ? Math.max(1, Math.round(day.played_sec / 60)) : 0;
      return '<div class="growth-day ' + (day.has_data ? "has-data" : "") + '">' +
        '<span class="dow">周' + dows[date.getDay()] + '</span>' +
        '<span class="date">' + C.esc(day.date.slice(5)) + '</span>' +
        '<span class="dot">' + (day.has_data ? "🐸" : "·") + '</span>' +
        '<span class="mins">' + (day.has_data ? mins + " 分" : "休息") + '</span>' +
        '</div>';
    }).join("");
  }

  function renderRecentSessions(rows) {
    const box = document.getElementById("growth-recent-list");
    if (!box) return;
    if (!rows || !rows.length) {
      box.innerHTML = '<div class="growth-empty"><strong>还没有正式游戏记录</strong>去池塘陪小蛙跳一会儿，这里就会长出第一片荷叶。</div>';
      return;
    }
    box.innerHTML = rows.slice().reverse().map(row =>
      '<div class="growth-row">' +
      '<div class="main"><strong>' + C.esc(row.kind_label) + '</strong>' +
      '<small>' + C.esc(row.date || "日期未知") + ' · ' + C.duration(row.played_sec) + '</small></div>' +
      '<div class="tail">' + (row.score === null || row.score === undefined ? "—" : C.num(row.score) + " 分") + '</div>' +
      '</div>'
    ).join("");
  }

  function renderCollection(data) {
    const owned = new Set((data.owned || []).map(String));
    const unlocked = new Set((data.achievements || []).map(String));
    const allItems = window.DressUp && window.DressUp.items ? window.DressUp.items() : [];
    const outfits = allItems.filter(item => !item.ach || owned.has(String(item.id)) || unlocked.has(String(item.ach)));
    const outfitBox = document.getElementById("growth-outfits");
    if (outfitBox) {
      outfitBox.innerHTML = outfits.length
        ? outfits.map(item => '<span class="growth-tag">' + C.esc(item.name || item.id) + '</span>').join("")
        : '<span class="growth-tag growth-tag--locked">还没有获得装扮</span>';
    }
    set("growth-outfit-count", outfits.length + " 件");
    const achList = window.Achievements && window.Achievements.list ? window.Achievements.list() : [];
    const got = achList.filter(item => unlocked.has(String(item.id)));
    const achBox = document.getElementById("growth-achievements");
    if (achBox) {
      achBox.innerHTML = got.length
        ? got.map(item => '<span class="growth-tag">' + C.esc(item.icon || "🏅") + " " + C.esc(item.name) + '</span>').join("")
        : '<span class="growth-tag growth-tag--locked">继续玩一玩，会解锁第一枚徽章</span>';
    }
    set("growth-achievement-count", got.length + " / " + achList.length);
    const mileBox = document.getElementById("growth-milestones");
    if (mileBox) {
      mileBox.innerHTML = (data.milestones || []).length
        ? data.milestones.map(m => '<div class="growth-row"><div class="main"><strong>' +
            C.esc(m.label) + '</strong><small>' + C.esc(m.date || "日期未知") + '</small></div><span class="tail">🌱</span></div>').join("")
        : '<div class="growth-empty"><strong>成长纪念会在这里出现</strong>第一次游戏、累计跳跃和游玩时长都会变成小纪念。</div>';
    }
  }

  async function load() {
    if (!window.Profile || !window.Profile.require("growth.html")) return;
    const profile = window.Profile.active();
    if (profile && profile.nickname) set("growth-name", profile.nickname);
    try {
      const data = await C.api("/api/growth/diary", { tz_offset_min: C.tz() });
      set("growth-name", (data.user && data.user.nickname) || "小蛙朋友");
      set("growth-days", C.num((data.summary || {}).play_days));
      set("growth-minutes", C.minutes((data.summary || {}).play_seconds));
      set("growth-jumps", C.num((data.summary || {}).successful_jumps));
      set("growth-score", C.num((data.summary || {}).score));
      set("growth-games", C.num((data.summary || {}).formal_games) + " 次正式游戏");
      renderRecent(data.recent);
      renderRecentSessions(data.recent_sessions);
      renderCollection(data);
      document.getElementById("growth-loading").classList.add("hidden");
      document.getElementById("growth-content").classList.remove("hidden");
      if (!data.has_data) document.getElementById("growth-first-empty").classList.remove("hidden");
    } catch (error) {
      document.getElementById("growth-loading").classList.add("hidden");
      document.getElementById("growth-error").classList.remove("hidden");
      document.getElementById("growth-error-text").textContent = error.message || "加载失败";
    }
  }

  document.addEventListener("DOMContentLoaded", load);
})();
