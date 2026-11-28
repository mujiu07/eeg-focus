/* v1.9.0 家长成长中心：本地报告、离线图表、分段评估和导出。 */
(function () {
  "use strict";
  const C = window.GrowthCommon;
  const state = { range: "7d", start: "", end: "", report: null, behaviorMetric: "click_success_rate" };
  const metricMeta = {
    click_success_rate: { label: "点击成功率", percent: true, empty: "没有可用的点击成功率数据" },
    reaction_median: { label: "反应时间中位数", unit: "秒", empty: "没有有效反应时间记录" },
    net_charge_median: { label: "净蓄力中位数", unit: "秒", empty: "没有完整蓄力轮次" },
    valid_signal_ratio: { label: "有效信号比例", percent: true, empty: "没有有效信号帧记录" },
  };

  function set(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function h(value) { return C.esc(value); }

  function kpi(label, value, hint) {
    return '<div class="parent-kpi"><div class="label">' + h(label) + '</div>' +
      '<div class="value">' + h(value) + '</div><div class="hint">' + h(hint || "") + '</div></div>';
  }

  function showError(message) {
    document.getElementById("parent-loading").classList.add("hidden");
    document.getElementById("parent-error").classList.remove("hidden");
    set("parent-error-text", message || "加载失败");
  }

  function setStatus(text, error) {
    const el = document.getElementById("parent-status");
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("error", !!error);
  }

  function renderUsage(report) {
    const usage = report.usage || {};
    document.getElementById("usage-kpis").innerHTML = [
      kpi("累计使用天数", usage.usage_days == null ? "数据不足" : usage.usage_days + " 天",
        "正式游戏 / 真实评估 / 有效校准去重"),
      kpi("正式游戏", usage.formal_game_count == null ? "数据不足" : usage.formal_game_count + " 次",
        "不含模拟、回放、标准评估"),
      kpi("实际游戏时长", C.duration(usage.play_seconds), "正式游戏 played_sec"),
      kpi("有效信号采集时长", C.duration(usage.effective_signal_seconds), "按时长 × 有效帧比例折算"),
      kpi("最近一次使用", usage.last_use || "数据不足", "本地时间"),
    ].join("");
    const counts = usage.category_counts || {};
    document.getElementById("category-kpis").innerHTML = [
      kpi("正式游戏", C.num(counts.formal_game), "纳入成长与行为统计"),
      kpi("校准教学", C.num(counts.calibration), "校准记录，不是游戏局数"),
      kpi("标准评估", C.num(counts.assessment), "真实硬件标准评估"),
      kpi("模拟 / 回放", C.num((counts.simulation || 0) + (counts.replay || 0) + (counts.assessment_simulation || 0)),
        "保留用于区分，不进入真实趋势"),
    ].join("");
    set("parent-range-label", (report.range || {}).label || "");
    if (!report.has_data) {
      setStatus("所选范围内没有可统计的真实记录。");
    }
  }

  function renderBehavior(report) {
    const b = report.behavior || {};
    document.getElementById("behavior-kpis").innerHTML = [
      kpi("成功跳跃", C.num(b.successful_jumps), "完整轮次 success 之和"),
      kpi("进入黄色区域", C.num(b.zone_entries), "完成 + 已进入未完成轮次"),
      kpi("点击成功率", C.pct(b.click_success_rate), "成功 ÷（成功 + 未成功完成）"),
      kpi("反应时间中位数", b.reaction_median == null ? "数据不足" : C.num(b.reaction_median, 2) + " 秒", "仅有效成功反应"),
      kpi("提前点击", C.num(b.early_taps), "正式游戏 actions.early_taps"),
      kpi("净蓄力中位数", b.net_charge_median == null ? "数据不足" : C.num(b.net_charge_median, 2) + " 秒", "完整轮次 eval_sec"),
      kpi("有效信号比例", C.pct(b.valid_signal_ratio), "有效帧 ÷ 总帧"),
      kpi("当前难度", (report.difficulty || {}).current_factor == null ? "数据不足" : C.num(report.difficulty.current_factor, 2), "黄色区域起点"),
    ].join("");
    document.getElementById("behavior-extra").innerHTML = [
      kpi("未完成蓄力轮次", C.num(b.incomplete_rounds), "单独保留，不混入净蓄力中位数"),
      kpi("点击成功率分母", C.num(b.click_denominator), "成功 + 未成功完成"),
      kpi("有反应时间轮次", C.num(b.reaction_count), "仅这些轮次参与中位数"),
      kpi("有净蓄力轮次", C.num(b.net_charge_count), "仅完整轮次参与中位数"),
    ].join("");
    const defs = report.definitions || {};
    document.getElementById("behavior-definitions").innerHTML =
      ["successful_jumps", "zone_entries", "click_success_rate", "reaction_median",
       "net_charge_median", "valid_signal_ratio"].map(key => {
        const d = defs[key] || {};
        return "<div><b>" + h(d.label || key) + "：</b>" + h(d.denominator || "数据不足") + "</div>";
      }).join("");
  }

  function renderCalendar(report) {
    const box = document.getElementById("parent-calendar");
    const days = report.daily || [];
    if (!days.length) {
      box.innerHTML = '<div class="growth-empty">所选范围内没有日历记录。</div>';
      return;
    }
    const max = Math.max.apply(null, days.map(d => d.played_sec || 0).concat([1]));
    const dows = ["日", "一", "二", "三", "四", "五", "六"];
    box.innerHTML = days.map(day => {
      const date = new Date(day.date + "T12:00:00");
      const intensity = day.played_sec ? Math.max(.18, day.played_sec / max) : 0;
      const low = (day.low_quality_sessions || 0) > 0;
      return '<div class="growth-day ' + (day.has_data ? "has-data" : "") + '" ' +
        'style="' + (intensity ? "background:rgba(63,157,112," + Math.min(.55, .12 + intensity * .38) + ")" : "") + '" ' +
        'title="' + h(day.date + (day.has_data ? " · " + C.duration(day.played_sec) : " · 无记录")) + '">' +
        '<span class="dow">周' + dows[date.getDay()] + '</span>' +
        '<span class="date">' + h(day.date.slice(5)) + '</span>' +
        '<span class="dot">' + (low && window.Icons ? window.Icons.markup("warning") : (day.has_data && window.FrogArt ? window.FrogArt.svg({ className: "growth-day-frog" }) : "·")) + '</span>' +
        '<span class="mins">' + (day.has_data ? Math.max(1, Math.round(day.played_sec / 60)) + " 分" : "—") + '</span>' +
        '</div>';
    }).join("");
  }

  function chartLabels(report) {
    return (report.daily || []).map(d => d.date);
  }

  function renderCharts(report) {
    const daily = (report.daily || []).map(d => ({
      label: d.date,
      value: d.played_sec == null ? 0 : d.played_sec / 60,
      quality: (d.low_quality_sessions || 0) > 0,
    }));
    window.GrowthCharts.bar(document.getElementById("daily-chart"), daily, { unit: "分钟" });
    renderBehaviorChart(report);
    renderAssessmentChart(report);
    window.GrowthCharts.step(document.getElementById("difficulty-chart"),
      (report.difficulty || {}).points || []);
  }

  function renderBehaviorChart(report) {
    const meta = metricMeta[state.behaviorMetric] || metricMeta.click_success_rate;
    const series = [{
      name: meta.label,
      points: (report.daily || []).map(d => ({
        label: d.date,
        value: d[state.behaviorMetric] == null ? null : d[state.behaviorMetric],
      })),
    }];
    window.GrowthCharts.line(document.getElementById("behavior-chart"), series, {
      labels: chartLabels(report), percent: !!meta.percent, unit: meta.label,
      empty: meta.empty,
    });
    const buttons = document.querySelectorAll("#behavior-tabs button");
    buttons.forEach(btn => btn.setAttribute("aria-pressed",
      btn.getAttribute("data-metric") === state.behaviorMetric ? "true" : "false"));
    set("behavior-caption", meta.empty + "；按日汇总，缺失日期不连线。");
  }

  function assessmentSeries(report, metric) {
    const groups = ((report.assessments || {}).trend || {}).segments || [];
    return groups.map(group => {
      const series = (group.series || []).find(item => item.metric === metric);
      return {
        name: group.label || "条件段",
        points: (series && series.points || []).map(p => ({ label: p.date, value: p.value })),
      };
    }).filter(s => s.points.length);
  }

  function renderAssessmentChart(report) {
    const series = assessmentSeries(report, "reference_score");
    const labels = [];
    series.forEach(s => s.points.forEach(p => { if (labels.indexOf(p.label) < 0) labels.push(p.label); }));
    labels.sort();
    window.GrowthCharts.line(document.getElementById("assessment-chart"), series, {
      labels: labels, unit: "S_reference", empty: "不足两次有效且可比较的标准评估时不计算趋势",
    });
  }

  function renderAssessments(report) {
    const section = report.assessments || {};
    const items = section.items || [];
    const table = document.getElementById("assessment-table");
    table.innerHTML = '<thead><tr><th>日期</th><th>来源</th><th>S_reference</th><th>映射前</th><th>有效信号</th><th>点击成功</th><th>可比性</th></tr></thead><tbody>' +
      (items.length ? items.map(item =>
        '<tr><td>' + h(item.date || "—") + '</td><td>' + h(item.source_label || "") +
        '</td><td class="numeric">' + h(C.num(item.reference_score, 1)) +
        '</td><td class="numeric">' + h(C.num(item.pre_map_score, 3)) +
        '</td><td class="numeric">' + h(C.pct(item.valid_signal_ratio)) +
        '</td><td class="numeric">' + h(C.pct(item.click_success_rate)) +
        '</td><td>' + (item.comparable ? "可比较" : h((item.comparison_reasons || []).join("；") || "不参与趋势")) + '</td></tr>'
      ).join("") : '<tr><td colspan="7" class="muted">所选范围内没有标准评估记录。</td></tr>') +
      '</tbody>';
    const box = document.getElementById("assessment-segments");
    const groups = (section.trend || {}).segments || [];
    if (!groups.length) {
      box.innerHTML = '<div class="growth-empty"><strong>还没有可比较的标准评估</strong>先完成标准评估；只有条件一致且质量合格的结果才进入同一段趋势。</div>';
    } else {
      box.innerHTML = groups.map(group => {
        const rows = (group.series || []).map(s => '<tr><td>' + h(s.label) + '</td><td class="numeric">' +
          h(C.num(s.first, 3)) + '</td><td class="numeric">' + h(C.num(s.last, 3)) +
          '</td><td class="numeric">' + (s.trend_available ? h(C.num(s.change, 3)) : "不计算") + '</td></tr>').join("");
        return '<details class="growth-details" ' + (group === groups[0] ? "open" : "") + '>' +
          '<summary>' + h(group.label || "条件段") + ' · ' + h(group.count) + ' 次 · ' + h(group.segment_reason || "") + '</summary>' +
          '<div class="inside"><p class="chart-caption">' + h(group.trend_note) + '</p>' +
          '<table class="parent-table"><thead><tr><th>指标</th><th>首次</th><th>末次</th><th>变化（仅同段）</th></tr></thead><tbody>' +
          (rows || '<tr><td colspan="4" class="muted">数据不足</td></tr>') + '</tbody></table></div></details>';
      }).join("");
    }
    document.getElementById("assessment-notes").innerHTML =
      '<div><b>比较规则：</b>' + h((section.trend || {}).policy || "") + '</div>' +
      '<div><b>随机任务：</b>' + h((section.trend || {}).seed_policy || "") + '</div>' +
      '<div><b>已记录：</b>真实 ' + h(section.real_count || 0) + ' 次，模拟/回放 ' + h(section.simulation_count || 0) + ' 次。</div>';
  }

  function renderSessions(report) {
    const rows = report.sessions || [];
    const table = document.getElementById("sessions-table");
    table.innerHTML = '<thead><tr><th>日期</th><th>来源</th><th>时长</th><th>积分</th><th>成功</th><th>点击成功率</th><th>反应中位数</th><th>净蓄力</th><th>信号</th><th>详情</th></tr></thead><tbody>' +
      (rows.length ? rows.map(row => {
        const m = row.metrics || {};
        return '<tr><td>' + h(row.date || "—") + '</td><td>' + h(row.source_label || "") +
          (row.low_quality ? ' <span class="growth-badge growth-badge--low">低质量</span>' : '') +
          '</td><td>' + h(C.duration(row.played_sec)) + '</td><td class="numeric">' + h(C.num(row.score)) +
          '</td><td class="numeric">' + h(C.num(m.successful_jumps)) +
          '</td><td class="numeric">' + h(C.pct(m.click_success_rate)) +
          '</td><td class="numeric">' + h(m.reaction_median == null ? "数据不足" : C.num(m.reaction_median, 2) + "s") +
          '</td><td class="numeric">' + h(m.net_charge_median == null ? "数据不足" : C.num(m.net_charge_median, 2) + "s") +
          '</td><td class="numeric">' + h(C.pct(m.valid_signal_ratio)) +
          '</td><td><a class="linkish" href="history.html?id=' + encodeURIComponent(row.session_id) + '">查看详情</a></td></tr>';
      }).join("") : '<tr><td colspan="10" class="muted">数据不足</td></tr>') + '</tbody>';
    document.getElementById("sessions-empty").classList.toggle("hidden", !!rows.length);
  }

  function renderQuality(report) {
    const q = report.quality || {};
    document.getElementById("quality-summary").innerHTML = [
      ["正式游戏", q.sessions_total],
      ["低信号质量局", q.sessions_low_quality],
      ["缺少逐轮数据", q.sessions_missing_rounds],
      ["缺少反应时间", q.sessions_missing_reaction],
      ["缺少净蓄力", q.sessions_missing_net_charge],
      ["不参与趋势的评估", q.assessment_uncomparable],
      ["模拟/回放评估", q.assessment_simulation],
    ].map(row => '<div><b>' + h(row[0]) + '：</b>' + h(C.num(row[1])) + '</div>').join("") +
      '<div><b>低质量阈值：</b>' + h(C.pct((report.data_quality || {}).low_signal_threshold)) + '</div>';
  }

  function renderDefinitions(report) {
    document.getElementById("definitions").innerHTML = Object.keys(report.definitions || {}).map(key => {
      const d = report.definitions[key];
      return '<div><b>' + h(d.label || key) + '：</b>' + h(d.denominator || "") + '（' + h(d.unit || "") + '）</div>';
    }).join("");
    document.getElementById("limitations").innerHTML = (report.limitations || []).map(x => '<div>• ' + h(x) + '</div>').join("");
  }

  function renderExport(report) {
    const buttons = document.querySelectorAll("#export-buttons button");
    buttons.forEach(btn => btn.disabled = !report.has_data);
    if (!report.has_data) setStatus("没有可导出的记录；不会生成空白文件。");
  }

  function render(report) {
    state.report = report;
    document.getElementById("parent-loading").classList.add("hidden");
    document.getElementById("parent-content").classList.remove("hidden");
    const staleEmpty = document.getElementById("parent-empty");
    if (staleEmpty) staleEmpty.remove();
    renderUsage(report);
    renderBehavior(report);
    renderCalendar(report);
    renderCharts(report);
    renderAssessments(report);
    renderSessions(report);
    renderQuality(report);
    renderDefinitions(report);
    renderExport(report);
    if (!report.has_data) {
      const box = document.createElement("div");
      box.className = "growth-empty";
      box.style.marginBottom = "14px";
      box.innerHTML = "<strong>所选范围还没有真实成长记录</strong>建议先完成一次正式游戏或标准评估；模拟和回放不会进入真实趋势。";
      const content = document.getElementById("parent-content");
      if (!document.getElementById("parent-empty")) {
        box.id = "parent-empty";
        content.insertBefore(box, content.firstChild);
      }
    }
  }

  async function load() {
    setStatus("正在读取本地记录…");
    document.getElementById("parent-loading").classList.remove("hidden");
    document.getElementById("parent-error").classList.add("hidden");
    document.getElementById("parent-content").classList.add("hidden");
    try {
      const data = await C.api("/api/growth/report", {
        range: state.range, start: state.start, end: state.end, tz_offset_min: C.tz(),
      });
      setStatus("已更新：" + ((data.range || {}).label || ""));
      render(data);
    } catch (error) {
      showError(error.message);
    }
  }

  function bindRange() {
    document.querySelectorAll("#parent-range button").forEach(btn => {
      btn.addEventListener("click", () => {
        const value = btn.getAttribute("data-range");
        state.range = value;
        document.querySelectorAll("#parent-range button").forEach(b =>
          b.setAttribute("aria-pressed", b === btn ? "true" : "false"));
        if (value === "custom") {
          if (!state.start || !state.end) {
            const end = new Date();
            const start = new Date(Date.now() - 13 * 86400000);
            state.end = end.toISOString().slice(0, 10);
            state.start = start.toISOString().slice(0, 10);
          }
          document.getElementById("parent-start").value = state.start;
          document.getElementById("parent-end").value = state.end;
          setStatus("请选择日期后点击“应用”。");
        } else {
          load();
        }
      });
    });
    document.getElementById("parent-apply").addEventListener("click", () => {
      state.start = document.getElementById("parent-start").value;
      state.end = document.getElementById("parent-end").value;
      if (!state.start || !state.end) { setStatus("请选择开始和结束日期", true); return; }
      state.range = "custom";
      document.querySelectorAll("#parent-range button").forEach(b =>
        b.setAttribute("aria-pressed", b.getAttribute("data-range") === "custom" ? "true" : "false"));
      load();
    });
  }

  function bindBehaviorTabs() {
    document.querySelectorAll("#behavior-tabs button").forEach(btn => {
      btn.addEventListener("click", () => {
        state.behaviorMetric = btn.getAttribute("data-metric");
        renderBehaviorChart(state.report);
      });
    });
  }

  function bindExport() {
    document.querySelectorAll("#export-buttons button").forEach(btn => {
      btn.addEventListener("click", async () => {
        const fmt = btn.getAttribute("data-fmt");
        const status = document.getElementById("export-status");
        status.classList.remove("error");
        status.textContent = "正在生成 " + fmt.toUpperCase() + "…";
        btn.disabled = true;
        try {
          const out = await C.download(fmt, state.range, state.start, state.end);
          status.textContent = "已生成并保存到 " + (out.saved || "reports/") + "；浏览器下载：" + out.filename;
        } catch (error) {
          status.classList.add("error");
          status.textContent = "导出失败：" + (error.message || "未知错误");
        } finally {
          btn.disabled = !(state.report && state.report.has_data);
        }
      });
    });
  }

  function bindGate() {
    const gate = document.getElementById("parent-gate");
    const ok = document.getElementById("parent-gate-ok");
    let entered = false;
    try { entered = sessionStorage.getItem("bf-parent-ok") === "1"; } catch (_) {}
    if (entered) {
      gate.classList.add("hidden");
      load();
      return;
    }
    ok.addEventListener("click", () => {
      try { sessionStorage.setItem("bf-parent-ok", "1"); } catch (_) {}
      gate.classList.add("hidden");
      load();
    });
  }

  function init() {
    if (!window.Profile || !window.Profile.require("parent.html")) return;
    bindRange();
    bindBehaviorTabs();
    bindExport();
    bindGate();
    let timer = null;
    window.addEventListener("resize", () => {
      clearTimeout(timer);
      timer = setTimeout(() => { if (state.report) renderCharts(state.report); }, 120);
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
