/* v1.8.4 开发者工作台：运行时、双基线、难度、诊断、标准评估与导出。
 * 只在开发者模式实例化；儿童模式不会请求 /api/dev/workbench 或额外订阅。
 * 数据来源：同一 Session 的真实 SSE/监测批次 + 已完成报告；不生成随机曲线。
 */
(function (global) {
  "use strict";

  const TAB_LABELS = {
    overview: "概览", baseline: "基线", difficulty: "难度",
    diagnostics: "诊断", assessment: "评估/导出",
  };
  const SOURCE_LABELS = {
    hardware: "Xmuse 真实硬件", replay: "EDF 真实回放",
    manual: "手动模拟", heart: "仅心率", "—": "未知",
  };
  const DECISION_LABELS = {
    TOO_HARD: "偏高", SUITABLE: "适宜", TOO_EASY: "偏低",
    INSUFFICIENT_DATA: "数据不足", SIGNAL_OR_CALIBRATION_CHECK: "检查信号/校准",
    BEHAVIOR_BOTTLENECK: "操作瓶颈", MANUAL_CONTROL: "手动控制",
    MANUAL_RESET: "恢复标准",
  };

  function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }
  function num(v, digits = 1, suffix = "") {
    return v == null || !Number.isFinite(Number(v)) ? "—" : Number(v).toFixed(digits) + suffix;
  }
  function pct(v, digits = 0) {
    return v == null || !Number.isFinite(Number(v)) ? "—" : (Number(v) * 100).toFixed(digits) + "%";
  }
  function clock(sec) {
    const s = Math.max(0, Math.round(Number(sec) || 0));
    return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  }
  function shortId(v) { return v ? String(v).slice(0, 12) : "—"; }
  function kv(rows) {
    return rows.map(([k, v, cls]) =>
      `<div class="dw-row"><span>${esc(k)}</span><b class="${cls || ""}" title="${esc(v)}">${esc(v)}</b></div>`
    ).join("");
  }
  function evidenceText(item) {
    return Object.entries(item.evidence || {})
      .filter(([, v]) => v != null && v !== "")
      .slice(0, 5)
      .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`)
      .join(" · ");
  }
  function statusClass(item) {
    if (item.active) return "active";
    return item.status === "insufficient" ? "clear" : "clear";
  }

  class DevWorkbench {
    constructor(opts) {
      this.opts = opts || {};
      this.sessionId = this.opts.sessionId;
      this.userId = this.opts.userId || null;
      this.monitor = this.opts.monitor || null;
      this.getState = this.opts.getState || (() => null);
      this.getRound = this.opts.getRound || (() => null);
      this.data = null;
      this.tab = "overview";
      this.timer = 0;
      this.lastError = "";
      this._bind();
      this.load();
      this.timer = global.setInterval(() => this.load(), 5000);
    }

    $id(id) { return document.getElementById(id); }

    _bind() {
      document.querySelectorAll("[data-dw-tab]").forEach(btn => {
        btn.addEventListener("click", () => this.setTab(btn.dataset.dwTab));
      });
      this.$id("dw-diff-auto")?.addEventListener("click", () => this.control({ auto_enabled: !this.data?.difficulty?.profile?.auto_enabled }));
      this.$id("dw-diff-lock")?.addEventListener("click", () => {
        const p = this.data?.difficulty?.profile;
        if (!p) return;
        this.control(p.manual_lock ? { manual_lock: false }
          : { manual_lock: true, factor: p.factor });
      });
      this.$id("dw-diff-reset")?.addEventListener("click", () => this.control({ reset: true }));
      this.$id("dw-export-json")?.addEventListener("click", () => this.export("json"));
      this.$id("dw-export-csv")?.addEventListener("click", () => this.export("csv"));
      this.$id("dw-start-assessment")?.addEventListener("click", e => {
        const href = this.assessmentHref();
        if (href) e.currentTarget.href = href; else e.preventDefault();
      });
      this._syncTabs();
    }

    setTab(tab) {
      if (!TAB_LABELS[tab]) return;
      this.tab = tab;
      this._syncTabs();
      this.monitor?.draw?.();
    }

    _syncTabs() {
      document.querySelectorAll("[data-dw-tab]").forEach(btn => {
        const active = btn.dataset.dwTab === this.tab;
        btn.classList.toggle("active", active);
        btn.setAttribute("aria-selected", String(active));
      });
      document.querySelectorAll("[data-dw-pane]").forEach(pane => {
        pane.classList.toggle("hidden", pane.dataset.dwPane !== this.tab);
      });
    }

    async load() {
      try {
        const q = new URLSearchParams();
        if (this.sessionId) q.set("session_id", this.sessionId);
        if (this.userId) q.set("user_id", this.userId);
        this.data = await API.get("/api/dev/workbench?" + q.toString());
        this.lastError = "";
        this.render();
      } catch (e) {
        this.lastError = e.message || String(e);
        this.renderError();
      }
    }

    renderError() {
      const el = this.$id("dw-runtime");
      if (el) el.innerHTML = `<div class="dw-summary">工作台读取失败：${esc(this.lastError)}</div>`;
    }

    render() {
      const d = this.data;
      if (!d) return;
      this.renderRuntime(d);
      this.renderBaseline(d);
      this.renderDifficulty(d);
      this.renderDiagnostics(d);
      this.renderAssessment(d);
      this.renderLive();
    }

    renderRuntime(d) {
      const r = d.runtime || {};
      const source = r.source || {};
      const mode = r.mode || source.name || "—";
      const user = d.user || {};
      const real = r.source_is_real ? "真实硬件" : (SOURCE_LABELS[mode] || mode);
      const rows = [
        ["用户", user.nickname ? `${user.nickname} · ${shortId(user.user_id)}` : "未选择", user.nickname ? "" : "warn"],
        ["Session", shortId(r.session_id)],
        ["用途", r.purpose || "—"],
        ["应用版本", d.app?.version || "—"],
        ["Schema", d.app?.schema_version != null ? "v" + d.app.schema_version : "—"],
        ["信号源", real, r.source_is_real ? "warn" : ""],
        ["运行模式", source.mode || mode],
        ["设备/配置", r.device_key || "—"],
        ["通道", Array.isArray(r.channels) && r.channels.length ? r.channels.join(", ") : "—"],
        ["采样率", r.fs ? `${r.fs} Hz（配置/文件值）` : "—"],
        ["开始时间", r.started_at || "—"],
        ["运行时长", r.elapsed_sec != null ? clock(r.elapsed_sec) : "—"],
        ["监测订阅", String(r.monitor_clients ?? 0)],
        ["服务端 Session", String(r.session_count ?? "—")],
        ["数据库", d.storage?.data_dir || "—"],
        ["加密", d.app?.encrypted ? "是" : "SQLite 未静态加密", d.app?.encrypted ? "" : "warn"],
      ];
      const el = this.$id("dw-runtime");
      if (el) el.innerHTML = `<div class="dw-kv">${kv(rows)}</div>`;
    }

    _live() {
      const state = this.getState() || {};
      const round = this.getRound()?.snapshot?.() || {};
      const batch = this.monitor?.lastBatch || {};
      return { state, round, batch };
    }

    onFrame(frame) {
      this.lastFrame = frame || null;
      this.renderLive();
    }

    renderLive() {
      const { state, round, batch } = this._live();
      const el = this.$id("dw-diff-live");
      if (el) {
        const cfg = this.getRound()?.config || this.monitor?.roundConfig || {};
        const zone = round.zone || {};
        el.innerHTML = `<div class="dw-kv">${kv([
          ["当前轮", round.roundIndex ?? "—"],
          ["阶段", round.phase || state.phase || "—"],
          ["黄色区域", zone.lo != null ? `${num(zone.lo)}–${num(zone.hi)}%` : "—"],
          ["当前能量", num(round.energy, 1, "%")],
          ["本轮有效蓄力", num(round.chargeActiveSec, 1, "s")],
          ["本轮 eval", num(round.evalSec, 1, "s")],
          ["本轮冷却", num(round.cooldownSec, 1, "s")],
          ["提前点击", round.earlyTaps ?? state.actions?.early_taps ?? "—"],
          ["子弹时间", num(round.bulletSec, 1, "s")],
          ["上一轮动画", num(state.roundAnimSec, 1, "s")],
        ])}</div>`;
      }
      const live = this.monitor?.baselinePoints || [];
      const last = live[live.length - 1];
      const frame = this.lastFrame || {};
      const dailyValue = last?.daily ?? frame.daily_score;
      const referenceValue = last?.reference ?? frame.reference_score;
      const note = this.$id("dw-baseline-note");
      if (note) {
        note.textContent = `S_daily ${num(dailyValue, 1)} · S_reference ${num(referenceValue, 1)}`;
      }
      const summary = this.$id("dw-baseline-summary");
      if (summary) {
        summary.innerHTML = `最近帧：S_daily <b>${num(dailyValue, 1)}</b> / S_reference <b>${num(referenceValue, 1)}</b>；两条曲线使用同一时间戳与同一算法输出，异常区间只标记，不做插值。`;
      }
    }

    renderBaseline(d) {
      const c = d.calibration || {};
      const cur = c.current || {};
      const daily = c.daily || {};
      const ref = c.reference || {};
      const range = cur.range || {};
      const refRange = ref.range || {};
      const rows = [
        ["当日校准 ID", cur.id || cur.calibration_id || "—"],
        ["校准时间", cur.calibrated_at || cur.at || "—"],
        ["剩余有效", daily.expires_at ? this._remain(daily.expires_at) : (daily.valid ? "有效" : "—"), daily.valid ? "" : "warn"],
        ["状态", daily.status_text || cur.status || "—"],
        ["设备匹配", daily.device_key && (cur.device_key || daily.device_key) ? (daily.valid ? "匹配" : "需检查") : "—", daily.valid ? "" : "warn"],
        ["当日 L / H", range.low != null ? `${num(range.low, 3)} / ${num(range.high, 3)}` : "—"],
        ["长期参考 ID", ref.id || ref.baseline_id || "—"],
        ["参考版本", ref.version || "—"],
        ["参考 L / H", refRange.low != null ? `${num(refRange.low, 3)} / ${num(refRange.high, 3)}` : "—"],
        ["有效样本", cur.n_frames ?? cur.stage_samples ?? "—"],
        ["有效采集", cur.effective_sec != null ? `${num(cur.effective_sec, 1)}s` : "—"],
        ["信号有效比例", d.latest_report?.valid_signal_ratio != null
          ? pct(d.latest_report.valid_signal_ratio) : "本局结束后生成"],
        ["平滑前 x", this.monitor?.lastBatch?.algorithm?.raw_focus != null ? num(this.monitor.lastBatch.algorithm.raw_focus, 3) : "—"],
      ];
      const el = this.$id("dw-calib-summary");
      if (el) el.innerHTML = kv(rows);
      const stateEl = this.$id("dw-calib-state");
      if (stateEl) {
        stateEl.textContent = daily.valid ? "今日有效" : (daily.status_text || "需检查");
        stateEl.className = daily.valid ? "dw-tag" : "dw-tag warn";
      }
      const refEl = this.$id("dw-reference-summary");
      if (refEl) refEl.innerHTML = kv([
        ["版本", ref.version || "—"], ["状态", ref.status || "—"],
        ["基线", num(ref.baseline, 3)], ["设备", ref.device_key || "—"],
        ["算法", ref.algorithm_version || "—"],
        ["协议", ref.protocol_version || "—"],
        ["创建", ref.created_at || "—"],
      ]);
      const hEl = this.$id("dw-calib-history");
      if (hEl) {
        const list = c.history || [];
        hEl.innerHTML = list.length ? list.map(x => `<div class="dw-item">
          <time>${esc((x.calibrated_at || "").slice(0, 19))}</time>
          <b>${esc(x.id || "")}</b> · ${esc(x.status || "—")} · ${esc(x.source_name || "—")}
          ${x.range ? ` · ${num(x.range.low, 3)}–${num(x.range.high, 3)}` : ""}</div>`).join("")
          : `<div class="dw-item">暂无校准历史</div>`;
      }
      const rhEl = this.$id("dw-reference-history");
      if (rhEl) {
        const list = c.reference_history || [];
        rhEl.innerHTML = list.length ? list.map(x => `<div class="dw-item">
          <time>${esc((x.created_at || "").slice(0, 19))}</time>
          <b>${esc(x.version || "")}</b> · ${esc(x.status || "—")} · ${esc(x.baseline_id || "")}</div>`).join("")
          : `<div class="dw-item">暂无长期参考版本</div>`;
      }
    }

    _remain(expiresAt) {
      const ms = Number(expiresAt) - Date.now();
      if (!Number.isFinite(ms) || ms <= 0) return "已过期";
      const m = Math.round(ms / 60000);
      return m >= 60 ? `${Math.floor(m / 60)}h${m % 60}m` : `${m} 分钟`;
    }

    renderDifficulty(d) {
      const p = d.difficulty?.profile || {};
      const snap = d.difficulty?.snapshot || {};
      const cfg = p.config || {};
      const rows = [
        ["当前系数", num(p.factor ?? snap.factor, 3)],
        ["自动适配", p.auto_enabled ? "开启" : "关闭", p.auto_enabled ? "" : "warn"],
        ["手动锁定", p.manual_lock ? "是" : "否", p.manual_lock ? "warn" : ""],
        ["下一局预定", num(p.next_factor ?? p.factor ?? snap.factor, 3)],
        ["名义随机范围", cfg.zone_low_min != null ? `${num(cfg.zone_low_min)}–${num(cfg.zone_low_max)}%` : "—"],
        ["安全实际范围", snap.zone_low_min != null ? `${num(snap.zone_low_min)}–${num(snap.zone_low_max)}%` : "—"],
        ["中位净蓄力", num(p.last_metrics?.median_net_charge_sec, 1, "s")],
        ["点击成功率", pct(p.last_metrics?.click_rate)],
        ["信号比例", pct(p.last_metrics?.signal_ratio)],
        ["连续偏高/偏低", `${p.streak_hard || 0} / ${p.streak_easy || 0}`],
        ["最近判定", DECISION_LABELS[p.last_decision] || p.last_decision || "—"],
        ["策略版本", p.strategy_version || snap.strategy_version || "—"],
      ];
      const el = this.$id("dw-diff-summary");
      if (el) el.innerHTML = kv(rows);
      const stateEl = this.$id("dw-diff-state");
      if (stateEl) stateEl.textContent = p.factor != null ? `factor ${num(p.factor, 3)}` : "—";
      const controls = ["dw-diff-auto", "dw-diff-lock", "dw-diff-reset"];
      controls.forEach(id => { const b = this.$id(id); if (b) b.disabled = !p.factor; });
      const auto = this.$id("dw-diff-auto");
      if (auto) auto.textContent = p.auto_enabled ? "关闭自动适配" : "开启自动适配";
      const lock = this.$id("dw-diff-lock");
      if (lock) lock.textContent = p.manual_lock ? "解除手动锁定" : "锁定当前难度";
      const hEl = this.$id("dw-diff-history");
      if (hEl) {
        const list = d.difficulty?.history || [];
        hEl.innerHTML = list.length ? list.map(x => `<div class="dw-item">
          <time>${esc((x.created_at || "").slice(0, 19))}</time>
          <b>${num(x.before_factor, 2)} → ${num(x.after_factor, 2)}</b>
          · ${esc(DECISION_LABELS[x.decision] || x.decision || "—")}
          ${x.session_id ? ` · ${esc(shortId(x.session_id))}` : ""}
          ${x.metrics?.median_net_charge_sec != null ? ` · ${num(x.metrics.median_net_charge_sec, 1)}s` : ""}</div>`).join("")
          : `<div class="dw-item">暂无难度调整历史</div>`;
      }
    }

    renderDiagnostics(d) {
      const report = d.latest_report || {};
      const diag = d.diagnostics || report.diagnostics || {};
      const items = diag.items || [];
      const sum = this.$id("dw-diag-summary");
      if (sum) {
        const quality = report.data_quality?.warnings || [];
        sum.innerHTML = report.session_id
          ? `<b>最近完成报告</b> ${esc(shortId(report.session_id))}：${esc(diag.summary || "暂无诊断")}`
            + (quality.length ? `<br><span class="dw-tag warn">数据边界</span> ${esc(quality.slice(0, 2).join("；"))}` : "")
          : "本局仍在运行；完整瓶颈诊断在本局结束后生成。下方显示上一份已完成报告。";
      }
      const list = this.$id("dw-diag-list");
      if (list) {
        list.innerHTML = items.length ? items.map(x => `<div class="dw-diag ${statusClass(x)}">
          <div class="dw-diag-head"><span>${esc(x.label)}</span><em>${x.active ? "成立" : (x.status === "insufficient" ? "数据不足" : "未成立")}</em></div>
          <p>${esc(x.summary)}</p>
          <div class="dw-evidence">${esc(evidenceText(x))}</div>
        </div>`).join("") : `<div class="dw-item">暂无诊断数据</div>`;
      }
      const p = report.charge_process || {};
      const grid = this.$id("dw-process-grid");
      if (grid) grid.innerHTML = kv([
        ["charge_sec", num(p.charge_sec, 1, "s")], ["eval_sec", num(p.eval_sec, 1, "s")],
        ["有效蓄力", num(p.charge_active_sec, 1, "s")], ["低于阈值", num(p.below_threshold_sec, 1, "s")],
        ["冷却", num(p.cooldown_sec, 1, "s")], ["衰减时间", num(p.decay_sec, 1, "s")],
        ["能量增长", num(p.energy_gain_total ?? p.energy_gain, 1, "%")], ["能量损失", num(p.energy_loss, 1, "%")],
        ["净变化", num(p.energy_net, 1, "%")], ["信号冻结", num(p.stale_sec, 1, "s")],
        ["子弹时间", num(p.bullet_sec, 1, "s")], ["跳跃动画", num(p.jump_anim_sec, 1, "s")],
        ["有效/评估", pct(p.active_ratio_of_eval)], ["衰减/评估", pct(p.decay_ratio_of_eval)],
      ]);
    }

    renderAssessment(d) {
      const a = d.assessment || {};
      const rows = [
        ["可开始", a.eligible ? "是" : "否", a.eligible ? "" : "warn"],
        ["可纵向比较", a.comparable ? "是" : "否（模拟/条件不足）", a.comparable ? "" : "warn"],
        ["协议", `${a.protocol?.version || "standard_v1"} · ${a.protocol?.planned_sec || 90}s`],
        ["固定难度", num(a.protocol?.fixed_factor ?? 1, 2)],
        ["模拟标记", a.simulation ? "是" : "否", a.simulation ? "warn" : ""],
        ["原因", (a.reasons || []).join("；") || "条件满足"],
      ];
      const el = this.$id("dw-assessment-status");
      if (el) el.innerHTML = kv(rows);
      const link = this.$id("dw-start-assessment");
      if (link) {
        link.href = this.assessmentHref() || "#";
        link.classList.toggle("disabled", !a.eligible);
        link.setAttribute("aria-disabled", String(!a.eligible));
      }
      const list = this.$id("dw-assessment-list");
      if (list) {
        const items = a.recent || [];
        list.innerHTML = items.length ? items.map(x => `<div class="dw-item">
          <time>${esc((x.started_at || "").slice(0, 19))}</time>
          <b>${esc(x.assessment_id)}</b> · ${esc(x.status)}${x.simulation ? " · 模拟" : ""}
          · ${num(x.planned_sec, 0, "s")} · ${shortId(x.session_id)}</div>`).join("")
          : `<div class="dw-item">暂无评估记录</div>`;
      }
      const count = this.$id("dw-assessment-count");
      if (count) count.textContent = `${(a.recent || []).length} 项`;
    }

    assessmentHref() {
      const d = this.data;
      if (!d || !d.assessment?.eligible) return null;
      const p = new URLSearchParams({ assessment: "1", sec: "90" });
      const mode = d.runtime?.mode;
      if (mode === "manual" || mode === "replay") p.set("test", mode);
      return "game.html?" + p.toString();
    }

    async control(body) {
      if (!this.userId) return;
      try {
        await API.post(`/api/profiles/${encodeURIComponent(this.userId)}/difficulty`, body);
        await this.load();
      } catch (e) { this._status("难度控制失败：" + e.message); }
    }

    async export(fmt) {
      const sid = this.data?.latest_report?.session_id || this.sessionId;
      const status = this.$id("dw-export-status");
      if (!sid) { if (status) status.textContent = "没有可导出的已完成 Session。"; return; }
      try {
        const res = await API.post(`/api/dev/diagnostics/${encodeURIComponent(sid)}/export?fmt=${fmt}`);
        const blob = new Blob([res.content], { type: res.media_type || "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = res.filename;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
        if (status) status.textContent = `已写入 ${res.path}；已开始下载 ${res.filename}`;
      } catch (e) {
        if (status) status.textContent = "导出失败：" + e.message;
      }
    }

    _status(text) {
      const el = this.$id("dw-export-status");
      if (el) el.textContent = text;
    }

    destroy() {
      if (this.timer) clearInterval(this.timer);
      this.timer = 0;
    }
  }

  global.DevWorkbench = { create(opts) { return new DevWorkbench(opts); } };
})(typeof window !== "undefined" ? window : globalThis);
