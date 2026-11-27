/* v1.9.0 历史游戏详情：从 SQLite/已保存报告读取，含可选逐轮数据。 */
(function () {
  "use strict";
  const C = window.GrowthCommon;

  function h(v) { return C.esc(v); }

  function set(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function item(label, value, sub) {
    return '<div class="detail-item"><div class="label">' + h(label) + '</div>' +
      '<div class="value">' + h(value) + '</div>' +
      (sub ? '<div class="sub">' + h(sub) + '</div>' : '') + '</div>';
  }

  function renderSummary(d) {
    const m = d.metrics || {};
    document.getElementById("detail-summary").innerHTML = [
      item("游戏时长", C.duration(d.played_sec), d.kind_label || ""),
      item("游戏积分", C.num(d.score), "不是商城余额"),
      item("成功跳跃", C.num(m.successful_jumps), "完整轮次"),
      item("点击成功率", C.pct(m.click_success_rate), "分母：" + C.num(m.click_denominator)),
      item("反应时间中位数", m.reaction_median == null ? "数据不足" : C.num(m.reaction_median, 2) + " 秒", "仅有效成功反应"),
      item("净蓄力中位数", m.net_charge_median == null ? "数据不足" : C.num(m.net_charge_median, 2) + " 秒", "仅完整轮次 eval_sec"),
      item("有效信号比例", C.pct(m.valid_signal_ratio), "有效帧 ÷ 总帧"),
      item("当前难度快照", d.difficulty && d.difficulty.factor != null ? C.num(d.difficulty.factor, 2) : "数据不足", "黄色区域起点"),
    ].join("");
  }

  function renderMeta(d) {
    const cal = d.calibration || {};
    const ref = d.reference || {};
    const m = d.metrics || {};
    document.getElementById("detail-meta").innerHTML = [
      item("Session", d.session_id || "—", d.storage === "sqlite" ? "SQLite / 已保存报告" : ""),
      item("日期", d.date || "—", d.source_label || ""),
      item("未完成蓄力轮次", C.num(m.incomplete_rounds), "单独保留，不混入完整轮次中位数"),
      item("校准状态", cal.status || "数据不足", cal.device_key || "报告未包含校准"),
      item("长期参考", ref.version || "数据不足", ref.label || ref.id || ""),
      item("信号质量", d.low_quality ? "低质量" : "可用", m.n_valid_frames == null ? "无帧统计" : C.num(m.n_valid_frames) + " / " + C.num(m.n_frames) + " 帧"),
    ].join("");
    document.getElementById("detail-flags").innerHTML =
      '<span class="growth-badge growth-badge--' + h(d.kind || "other") + '">' + h(d.kind_label || "记录") + '</span>' +
      (d.low_quality ? '<span class="growth-badge growth-badge--low">低质量信号</span>' : "") +
      (d.eeg_available === false ? '<span class="growth-badge">无 EEG</span>' : "");
  }

  function renderDiagnostics(d) {
    const items = (d.diagnostics || {}).items || [];
    const active = items.filter(x => x.active);
    const box = document.getElementById("detail-diagnostics");
    if (!active.length) {
      box.innerHTML = '<div class="growth-empty">没有触发的工程瓶颈；这不代表临床评价。</div>';
      return;
    }
    box.innerHTML = active.map(x => '<div class="diag-item"><strong>' + h(x.label || x.id) + '</strong>' +
      h(x.detail || "") + '<div class="muted" style="margin-top:3px;font-size:10px">工程诊断，不是医学结论</div></div>').join("");
  }

  function renderRounds(d) {
    const box = document.getElementById("detail-rounds");
    const rows = d.rounds || [];
    if (!rows.length) {
      box.innerHTML = '<div class="growth-empty">本局没有逐轮数据，或报告来自旧版本。历史汇总仍可读取。</div>';
      return;
    }
    box.innerHTML = '<div style="overflow:auto"><table class="parent-table rounds-table"><thead><tr>' +
      '<th>#</th><th>成功</th><th>进入黄区</th><th>反应(s)</th><th>计分用时(s)</th><th>净蓄力(s)</th><th>提前点击</th><th>潜在分</th></tr></thead><tbody>' +
      rows.map((r, i) => '<tr><td>' + (i + 1) + (r._incomplete ? " 未完成" : "") + '</td><td>' +
        (r.success ? "是" : "否") + '</td><td>' + (r.entered ? "是" : "否") + '</td><td>' +
        h(C.num(r.reaction_sec, 2)) + '</td><td>' + h(C.num(r.charge_sec, 2)) + '</td><td>' +
        h(C.num(r.eval_sec, 2)) + '</td><td>' + h(C.num(r.early_taps)) + '</td><td>' +
        h(C.num(r.potential)) + '</td></tr>').join("") + '</tbody></table></div>' +
      '<p class="chart-caption">逐轮数据用于开发者/研究查看；不包含原始高频 EEG 波形。</p>';
  }

  async function load() {
    if (!window.Profile || !window.Profile.require("history.html")) return;
    const id = new URLSearchParams(location.search).get("id");
    if (!id) {
      document.getElementById("history-loading").classList.add("hidden");
      document.getElementById("history-error").classList.remove("hidden");
      set("history-error-text", "缺少 session id。");
      return;
    }
    try {
      const d = await C.api("/api/growth/sessions/" + encodeURIComponent(id), {
        include_rounds: true, tz_offset_min: C.tz(),
      });
      set("history-title", "游戏详情 · " + (d.date || ""));
      renderSummary(d);
      renderMeta(d);
      renderDiagnostics(d);
      renderRounds(d);
      document.getElementById("history-content").classList.remove("hidden");
      document.getElementById("history-loading").classList.add("hidden");
    } catch (error) {
      document.getElementById("history-loading").classList.add("hidden");
      document.getElementById("history-error").classList.remove("hidden");
      set("history-error-text", error.message || "读取失败");
    }
  }

  document.addEventListener("DOMContentLoaded", load);
})();
