/* ============================================================
   专注小蛙 v1.8.3 · 开发者实时脑电监测
   ------------------------------------------------------------
   只消费后端已经计算完成的原始/处理后窗口、频段特征、算法中间结果
   与游戏 SSE；不生成随机曲线，不用分数反推波形。
   高频波形用有限环形缓存 + Canvas 2D，儿童模式不会创建本对象。
   ============================================================ */
(function (global) {
  "use strict";

  const BANDS = [
    { name: "delta", label: "δ Delta", color: "#8aa7c7" },
    { name: "theta", label: "θ Theta", color: "#b59bd8" },
    { name: "alpha", label: "α Alpha", color: "#78c9b2" },
    { name: "beta", label: "β Beta", color: "#e2b56f" },
    { name: "gamma", label: "γ Gamma", color: "#d88f8a" },
  ];
  const BAND_COLORS = Object.fromEntries(BANDS.map(b => [b.name, b.color]));
  const CH_COLORS = ["#6ccbd4", "#9ed58b", "#e3b06b", "#cf91c9", "#8da7e8",
    "#e39b86", "#87d0b1", "#c4b676", "#b995e2", "#71b9e0"];
  const EVENT_META = {
    round_start: { label: "开始新一轮蓄力", cls: "game", color: "#e2b56f", symbol: "●" },
    decay_start: { label: "开始能量衰减", cls: "game", color: "#d88f8a", symbol: "▼" },
    decay_end: { label: "结束能量衰减", cls: "game", color: "#78c9b2", symbol: "▲" },
    invalid_tap: { label: "无效点击", cls: "game", color: "#9d9190", symbol: "×" },
    cooldown_start: { label: "开始点击冷却", cls: "game", color: "#b59bd8", symbol: "▮" },
    bullet_enter: { label: "进入金色区域", cls: "game", color: "#ffc37e", symbol: "◆" },
    success: { label: "成功点击", cls: "game", color: "#8fe3bc", symbol: "●" },
    miss: { label: "错过点击", cls: "game", color: "#e6a29a", symbol: "○" },
    score_settle: { label: "积分结算", cls: "game", color: "#6ccbd4", symbol: "■" },
    signal_lost: { label: "信号异常", cls: "signal", color: "#e6a29a", symbol: "!" },
    signal_recover: { label: "信号恢复", cls: "signal", color: "#74a8d6", symbol: "+" },
    game_pause: { label: "游戏暂停", cls: "game", color: "#9d9190", symbol: "Ⅱ" },
    game_resume: { label: "游戏恢复", cls: "game", color: "#8fd0c3", symbol: "▶" },
  };

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const finite = v => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v));
  const num = (v, digits = 1) => finite(v) ? Number(v).toFixed(digits) : "—";
  const pct = v => finite(v) ? (Number(v) * 100).toFixed(1) + "%" : "—";
  const esc = s => String(s == null ? "—" : s);
  const detailValue = v => {
    if (v == null) return "—";
    if (typeof v === "number") return String(Math.round(v * 100) / 100);
    if (Array.isArray(v)) return v.join("/");
    if (typeof v === "object") return Object.entries(v).map(([k, x]) => `${k}=${detailValue(x)}`).join(" ");
    return String(v);
  };

  function canvasSize(canvas, ctx) {
    const rect = canvas.getBoundingClientRect();
    const dpr = Math.min(global.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(rect.width));
    const h = Math.max(1, Math.round(rect.height));
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { w, h, dpr };
  }

  class EEGMonitor {
    constructor(opts) {
      this.opts = opts || {};
      this.$ = id => document.getElementById(id);
      this.sessionId = this.opts.sessionId;
      this.initialSource = this.opts.source || {};
      this.mode = this.opts.mode || "manual";
      this.demo = !!this.opts.demo;
      this.testMode = this.opts.testMode || null;
      this.getState = this.opts.getState || (() => null);
      this.getRound = this.opts.getRound || (() => null);
      this.roundConfig = this.opts.roundConfig || global.FocusRound?.CONFIG || {};
      this.thresholds = this.opts.thresholds || { enter: 45, exit: 38 };

      this.monitorEs = null;
      this.streamState = "未连接";
      this.hello = null;
      this.unavailableReason = "";
      this.lastBatch = null;
      this.lastBatchSeq = -1;
      this.latestT = null;
      this.lastSampleSeq = null;
      this.waveBatches = [];
      this.sampleGaps = [];
      this.channelNames = [];
      this.channelOk = [];
      this.channelScaleRaw = [];
      this.channelScaleProc = [];
      this.channelOn = {};
      this.unit = "未确认";
      this.unitConfidence = "unknown";
      this.fs = null;
      this.lastReceive = 0;
      this.paused = false;
      this.pauseT = null;
      this.waveMode = "raw";
      this.windowSec = 5;
      this.gain = 1;
      this.bandFilter = new Set(BANDS.map(b => b.name));
      this.currentBands = null;
      this.bandHistory = [];
      this.scorePoints = [];
      this.baselinePoints = [];
      this.events = [];
      this.eventFilter = "all";
      this.latestGameT = null;
      this.scoreHits = [];
      this.raf = 0;
      this.statusTimer = 0;
      this.lastDraw = 0;
      this.destroyed = false;
      this._bound = false;

      this._bindUI();
    }

    start() {
      if (!this.sessionId || this.destroyed) return this;
      document.documentElement.classList.add("monitor-mode");
      const left = this.$("monitor-left"), right = this.$("monitor-right");
      if (left) left.setAttribute("aria-hidden", "false");
      if (right) right.setAttribute("aria-hidden", "false");
      this._startedAt = performance.now();
      this._setSourceBadge();
      ["left", "right"].forEach(side => {
        const btn = document.querySelector(`[data-monitor-show="${side}"]`);
        if (btn) {
          btn.setAttribute("aria-pressed", "true");
          btn.textContent = side === "left" ? "隐藏波形" : "隐藏算法";
        }
      });
      // 小窗口默认收起两侧面板，避免把游戏操作区挤到首屏之外；仍可从顶部恢复。
      if (global.matchMedia && global.matchMedia("(max-width: 1220px)").matches) {
        this.setPanel("left", false);
        this.setPanel("right", false);
      }
      this._connect();
      this.statusTimer = global.setInterval(() => { this._watchDataFreshness(); this.renderStatus(); }, 250);
      this.raf = requestAnimationFrame(ts => this._loop(ts));
      return this;
    }

    stop() {
      this.destroyed = true;
      if (this.monitorEs) { this.monitorEs.close(); this.monitorEs = null; }
      if (this.statusTimer) clearInterval(this.statusTimer);
      if (this.raf) cancelAnimationFrame(this.raf);
      if (this.resizeObserver) this.resizeObserver.disconnect();
      document.documentElement.classList.remove("monitor-mode");
      this.streamState = "已停止";
    }

    _bindUI() {
      if (this._bound) return;
      this._bound = true;
      document.querySelectorAll("[data-wave-mode]").forEach(btn => {
        btn.addEventListener("click", () => {
          this.waveMode = btn.dataset.waveMode;
          document.querySelectorAll("[data-wave-mode]").forEach(b => b.classList.toggle("active", b === btn));
          this.draw();
        });
      });
      this.$("mon-window-select")?.addEventListener("change", e => {
        this.windowSec = Number(e.target.value) || 5;
        this.draw();
      });
      this.$("mon-gain")?.addEventListener("input", e => {
        this.gain = clamp(Number(e.target.value) || 1, 0.5, 3);
        this.draw();
      });
      this.$("mon-pause-wave")?.addEventListener("click", () => {
        this.paused = !this.paused;
        if (this.paused) this.pauseT = this.latestT;
        const b = this.$("mon-pause-wave");
        if (b) { b.textContent = this.paused ? "恢复" : "暂停"; b.classList.toggle("active", this.paused); }
        this.draw();
      });
      this.$("mon-wave-legend")?.addEventListener("click", e => {
        const b = e.target.closest("[data-channel]");
        if (!b) return;
        const i = Number(b.dataset.channel);
        this.channelOn[i] = !this.channelOn[i];
        b.classList.toggle("off", !this.channelOn[i]);
        this.draw();
      });
      this.$("mon-band-history")?.addEventListener("toggle", () => this.drawBands());
      this.$("mon-band-legend")?.addEventListener("click", e => {
        const b = e.target.closest("[data-band]");
        if (!b) return;
        const name = b.dataset.band;
        if (this.bandFilter.has(name)) this.bandFilter.delete(name); else this.bandFilter.add(name);
        b.classList.toggle("off", !this.bandFilter.has(name));
        this.drawBands();
      });
      document.querySelectorAll("[data-event-filter]").forEach(btn => {
        btn.addEventListener("click", () => {
          this.eventFilter = btn.dataset.eventFilter;
          document.querySelectorAll("[data-event-filter]").forEach(b => b.classList.toggle("active", b === btn));
          this.renderEvents();
          this.drawScore();
        });
      });
      this.$("monitor-hide-left")?.addEventListener("click", () => this.setPanel("left", false));
      this.$("monitor-hide-right")?.addEventListener("click", () => this.setPanel("right", false));
      document.querySelectorAll("[data-monitor-show]").forEach(btn => {
        btn.addEventListener("click", () => {
          const side = btn.dataset.monitorShow;
          const layout = this.$("game-layout");
          const off = layout?.classList.contains(side + "-off");
          this.setPanel(side, !!off);
        });
      });
      this.$("mon-score-canvas")?.addEventListener("mousemove", e => this._showScoreTip(e));
      this.$("mon-score-canvas")?.addEventListener("mouseleave", () => {
        const tip = this.$("mon-score-tip"); if (tip) tip.style.display = "none";
      });
      this.resizeObserver = new ResizeObserver(() => this.draw());
      [this.$("mon-wave-canvas"), this.$("mon-score-canvas"), this.$("mon-band-canvas"),
       this.$("mon-baseline-canvas")]
        .filter(Boolean).forEach(c => c.parentElement && this.resizeObserver.observe(c.parentElement));
      this._buildBandLegend();
    }

    setPanel(side, visible) {
      const layout = this.$("game-layout");
      if (!layout) return;
      layout.classList.toggle(side + "-off", !visible);
      const panel = this.$(side === "left" ? "monitor-left" : "monitor-right");
      if (panel) panel.setAttribute("aria-hidden", String(!visible));
      const btn = document.querySelector(`[data-monitor-show="${side}"]`);
      if (btn) {
        btn.setAttribute("aria-pressed", String(visible));
        btn.textContent = visible ? (side === "left" ? "隐藏波形" : "隐藏算法") : (side === "left" ? "显示波形" : "显示算法");
        btn.title = visible
          ? (side === "left" ? "隐藏波形面板（监测继续）" : "隐藏开发者工作台（监测继续）")
          : (side === "left" ? "重新显示波形面板" : "重新显示开发者工作台");
      }
      this.draw();
      // 侧栏显隐改变的是 CSS Grid 列宽，canvas 自身不会收到 resize；
      // 等下一帧布局完成后再通知游戏页重算画布与指针映射。
      requestAnimationFrame(() => {
        window.dispatchEvent(new Event("resize"));
        this.draw();
      });
    }

    _setSourceBadge() {
      const s = this.initialSource || {};
      const label = s.label || s.name || "信号源";
      const name = s.name || this.mode || "—";
      const el = this.$("mon-source-label"); if (el) el.textContent = label;
      const mode = this.$("mon-mode-label");
      if (mode) {
        if (name === "hardware") mode.textContent = "Xmuse 真机";
        else if (name === "replay") mode.textContent = "EDF 回放";
        else if (name === "heart") mode.textContent = "仅心率";
        else if (this.demo) mode.textContent = "模拟试玩";
        else mode.textContent = "无脑电";
      }
    }

    _connect() {
      if (this.monitorEs) this.monitorEs.close();
      this.streamState = "连接中";
      this.renderStreamState();
      let uid = null;
      try {
        const profile = JSON.parse(localStorage.getItem("bf-active-user") || "null");
        uid = profile && profile.user_id;
      } catch (_) { uid = null; }
      const url = `/api/session/${encodeURIComponent(this.sessionId)}/monitor`
        + (uid ? `?user_id=${encodeURIComponent(uid)}` : "");
      const es = new EventSource(url);
      this.monitorEs = es;
      es.addEventListener("hello", ev => {
        try { this.hello = JSON.parse(ev.data); } catch (_) { this.hello = null; }
        this.streamState = this.hello?.available ? "已连接" : "无脑电采样";
        this.unavailableReason = this.hello?.available ? "" : "当前模式无脑电采样数据";
        if (this.hello?.ch_names) this.channelNames = this.hello.ch_names;
        if (this.hello?.fs) this.fs = this.hello.fs;
        this.renderStreamState();
        this._setSourceBadge();
        if (this.hello && !this.hello.available) {
          this._showWaveEmpty(this.unavailableReason || "当前模式无脑电采样数据");
        }
        this.render();
      });
      es.addEventListener("monitor", ev => {
        let b;
        try { b = JSON.parse(ev.data); } catch (_) { return; }
        this._ingest(b);
      });
      es.addEventListener("unavailable", ev => {
        try { this.unavailableReason = JSON.parse(ev.data).reason || "当前模式无脑电采样数据"; }
        catch (_) { this.unavailableReason = "当前模式无脑电采样数据"; }
        this.streamState = "无脑电采样";
        this.renderStreamState();
        this._showWaveEmpty(this.unavailableReason);
        this.render();
      });
      es.addEventListener("end", () => {
        this.streamState = "已结束";
        this.renderStreamState();
        this.monitorEs?.close();
      });
      es.onopen = () => {
        if (!this.hello) this.streamState = "已连接";
        this.renderStreamState();
      };
      es.onerror = () => {
        if (this.streamState !== "已结束") this.streamState = "重连中";
        this.renderStreamState();
      };
    }

    _watchDataFreshness() {
      if (this.destroyed) return;
      if (!this.hello?.available) return;
      const age = this.lastReceive ? (performance.now() - this.lastReceive) / 1000 : null;
      if (age != null && age > 3) {
        if (this.streamState !== "数据中断") {
          this.streamState = "数据中断";
          this.renderStreamState();
          this._showWaveEmpty("设备已停止更新，保留历史波形");
          this.draw();
        }
      } else if (age == null && this.hello && performance.now() - (this._startedAt || 0) > 4000) {
        if (this.streamState !== "等待数据") {
          this.streamState = "等待数据";
          this.renderStreamState();
          this._showWaveEmpty("等待脑电数据…");
        }
      }
    }

    renderStreamState() {
      const el = this.$("mon-stream-label");
      if (!el) return;
      el.textContent = this.streamState;
      el.classList.toggle("ok", this.streamState === "已连接");
      el.classList.toggle("bad", /断开|异常|无脑电|重连/.test(this.streamState));
    }

    _ingest(b) {
      if (!b || !finite(b.seq)) return;
      if (b.seq <= this.lastBatchSeq) return;
      if (this.lastBatchSeq >= 0 && b.seq > this.lastBatchSeq + 1) {
        const prevT = this.latestT;
        if (prevT != null && b.t0 != null) this.sampleGaps.push({ t0: prevT, t1: Number(b.t0) });
      }
      this.lastBatchSeq = b.seq;
      this.lastBatch = b;
      this.lastReceive = performance.now();
      this.streamState = "已连接";
      this.renderStreamState();
      if (b.fs) this.fs = b.fs;
      if (b.unit) this.unit = b.unit;
      if (b.unit_confidence) this.unitConfidence = b.unit_confidence;
      if (b.ch_names?.length) this.channelNames = b.ch_names;
      if (b.channels?.length) {
        this.channelOk = b.channels.map(c => !!c.ok);
      }
      const hasWave = this._ingestWave(b);
      this._ingestBands(b);
      if (this.unit) {
        const u = this.$("mon-unit-label");
        if (u) u.textContent = `单位：${this.unit}`;
      }
      this._setSourceBadge();
      if (hasWave) this._showWaveEmpty("");
      this.renderBands();
      this.renderAlgo();
      this.renderStatus();
      this.draw();
    }

    _ingestWave(b) {
      const raw = Array.isArray(b.raw) ? b.raw : null;
      const proc = Array.isArray(b.processed) ? b.processed : null;
      if (!raw && !proc) {
        this._showWaveEmpty(this.unavailableReason || "当前窗口没有可显示的脑电数据");
        return false;
      }
      const n = Math.min(
        raw?.[0]?.length || Infinity,
        proc?.[0]?.length || Infinity,
        Number(b.n) || Infinity
      );
      if (!Number.isFinite(n) || n <= 0) return false;
      let skip = 0;
      const replayTime = b.time_basis === "edf_file";
      if (!replayTime && this.lastSampleSeq != null && finite(b.sample_seq0)) {
        skip = Math.max(0, this.lastSampleSeq - Number(b.sample_seq0) + 1);
      }
      if (skip >= n) return false;
      const slice = arr => arr ? arr.map(ch => ch.slice(skip, skip + n)) : null;
      const t0 = b.t0 == null ? null : Number(b.t0) + skip / (Number(b.fs) || 1);
      const t1 = b.t1 == null ? null : Number(b.t1);
      const batch = {
        t0, t1, fs: Number(b.fs) || this.fs || 1,
        raw: slice(raw), processed: slice(proc),
        sample_seq0: finite(b.sample_seq0) ? Number(b.sample_seq0) + skip : null,
        sample_seq1: b.sample_seq1,
        time_basis: b.time_basis || "session_clock",
      };
      if (!replayTime && batch.sample_seq0 != null && this.lastSampleSeq != null
          && batch.sample_seq0 > this.lastSampleSeq + 1
          && this.latestT != null && t0 != null) {
        this.sampleGaps.push({ t0: this.latestT, t1: t0 });
      }
      if (!replayTime && batch.sample_seq1 != null) this.lastSampleSeq = Number(batch.sample_seq1);
      if (t0 != null) this.latestT = Math.max(this.latestT ?? -Infinity, t0 + (n - 1) / batch.fs);
      // 每个通道用当前窗的稳健峰值做显示尺度；不改变数据本身。
      const updateScale = (arr, target) => {
        if (!arr) return;
        arr.forEach((ch, i) => {
          const vals = ch.filter(v => Number.isFinite(v)).map(v => Math.abs(v)).sort((a, b) => a - b);
          if (!vals.length) return;
          const p95 = vals[Math.min(vals.length - 1, Math.floor(vals.length * 0.95))] || 1;
          const next = Math.max(1e-6, p95 * 1.35);
          target[i] = target[i] ? target[i] * 0.7 + next * 0.3 : next;
          if (!(i in this.channelOn)) this.channelOn[i] = true;
        });
      };
      updateScale(batch.raw, this.channelScaleRaw);
      updateScale(batch.processed, this.channelScaleProc);
      this.waveBatches.push(batch);
      const keepAfter = (this.latestT ?? 0) - 12.5;
      this.waveBatches = this.waveBatches.filter(x => x.t1 == null || x.t1 >= keepAfter).slice(-80);
      this.sampleGaps = this.sampleGaps.filter(g => g.t1 >= keepAfter).slice(-30);
      this._renderWaveLegend();
      return true;
    }

    _ingestBands(b) {
      if (!Array.isArray(b.bands)) return;
      // 即使本窗异常/不可用也要清空当前条，不能把上一窗的数值继续当成当前条形图。
      this.currentBands = b.bands;
      if (!b.bands.some(x => x.available)) return;
      const t = b.t1 == null ? this.latestT : Number(b.t1);
      if (!finite(t)) return;
      const by = {};
      b.bands.forEach(x => { by[x.name] = x; });
      this.bandHistory.push({ t, by });
      const cutoff = t - 32;
      this.bandHistory = this.bandHistory.filter(x => x.t >= cutoff).slice(-160);
    }

    ingestFrame(f) {
      if (!f) return;
      const t = finite(f.t) ? Number(f.t) : this.latestGameT;
      if (!finite(t)) return;
      this.latestGameT = t;
      const prev = this.scorePoints[this.scorePoints.length - 1];
      if (prev && t < prev.t - 0.05) this.scorePoints = [];
      const valid = !!f.valid && f.focus != null;
      const point = {
        t, valid,
        raw: finite(f.score_raw) ? Number(f.score_raw) : (finite(f.raw) ? Number(f.raw) * 100 : null),
        smooth: finite(f.score_smooth) ? Number(f.score_smooth) : (finite(f.score) ? Number(f.score) : null),
        game: finite(f.score) ? Number(f.score) : null,
        daily: finite(f.daily_score) ? Number(f.daily_score) : (finite(f.score) ? Number(f.score) : null),
        reference: finite(f.reference_score) ? Number(f.reference_score) : null,
        reason: f.reason || "",
      };
      this.scorePoints.push(point);
      this.baselinePoints.push(point);
      const cutoff = t - 31.5;
      this.scorePoints = this.scorePoints.filter(p => p.t >= cutoff).slice(-140);
      this.baselinePoints = this.baselinePoints.filter(p => p.t >= cutoff).slice(-140);
    }

    event(type, label, extra) {
      const meta = EVENT_META[type] || { label: label || type, cls: "game" };
      const s = this.getState?.() || {};
      let t = finite(s.signalTime) ? Number(s.signalTime) : (this.latestGameT ?? this.latestT ?? 0);
      if (!s.stale && s.lastFrameTs) t += Math.max(0, (performance.now() - s.lastFrameTs) / 1000);
      this.events.push({
        t: Math.max(0, t), type, label: label || meta.label, cls: meta.cls,
        detail: extra && Object.keys(extra).length ? extra : null,
      });
      if (this.events.length > 240) this.events = this.events.slice(-180);
      this.renderEvents();
      this.drawScore();
    }

    _buildBandLegend() {
      const el = this.$("mon-band-legend");
      if (!el) return;
      el.innerHTML = BANDS.map(b => `<button type="button" data-band="${b.name}">${b.label}</button>`).join("");
    }

    _renderWaveLegend() {
      const el = this.$("mon-wave-legend");
      if (!el || !this.channelNames.length) return;
      el.innerHTML = this.channelNames.map((name, i) => {
        const off = this.channelOn[i] === false;
        const bad = this.channelOk[i] === false;
        return `<button type="button" class="mon-channel${off ? " off" : ""}" data-channel="${i}" title="${bad ? "该通道被去噪模块剔除" : "点击显示/隐藏"}">
          <i style="background:${CH_COLORS[i % CH_COLORS.length]}"></i>${esc(name)}${bad ? " ×" : ""}</button>`;
      }).join("");
    }

    _showWaveEmpty(text) {
      const el = this.$("mon-wave-empty");
      if (!el) return;
      if (text) {
        el.textContent = text;
        el.classList.remove("hidden");
      } else {
        el.classList.add("hidden");
      }
    }

    _loop(ts) {
      if (this.destroyed) return;
      this.raf = requestAnimationFrame(t => this._loop(t));
      if (ts - this.lastDraw < 33) return;
      this.lastDraw = ts;
      if (document.hidden) return;
      this.draw();
    }

    _isSideVisible(side) {
      const panel = this.$(side === "left" ? "monitor-left" : "monitor-right");
      return !!(panel && panel.offsetParent !== null);
    }

    draw() {
      // 折叠/隐藏的面板不再遍历波形或重绘图表；采集与缓存仍由数据流继续。
      if (this._isSideVisible("left")) this.drawWave();
      if (this._isSideVisible("right")) {
        this.drawBands();
        this.drawScore();
        this.drawBaseline();
      }
    }

    _visibleT() {
      if (this.paused && this.pauseT != null) return this.pauseT;
      return this.latestT;
    }

    drawWave() {
      const canvas = this.$("mon-wave-canvas");
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      const { w, h } = canvasSize(canvas, ctx);
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#0a1217"; ctx.fillRect(0, 0, w, h);
      if (!this.waveBatches.length) return;
      const tEnd = this._visibleT();
      if (!finite(tEnd)) return;
      const windowSec = this.windowSec;
      const tStart = tEnd - windowSec;
      const names = this.channelNames;
      const visible = names.map((n, i) => i).filter(i => this.channelOn[i] !== false);
      const plot = { x0: 38, x1: Math.max(42, w - 5), y0: 29, y1: h - 15 };
      const laneH = Math.max(12, (plot.y1 - plot.y0) / Math.max(1, visible.length));
      const plotW = Math.max(1, plot.x1 - plot.x0);

      // 时间网格
      ctx.font = "9px Menlo, Consolas, monospace";
      ctx.textBaseline = "middle";
      const step = windowSec <= 2 ? 0.5 : windowSec <= 5 ? 1 : 2;
      for (let t = 0; t <= windowSec + 1e-9; t += step) {
        const x = plot.x0 + plotW * t / windowSec;
        ctx.strokeStyle = "rgba(127, 183, 190, .13)";
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, plot.y0); ctx.lineTo(x, plot.y1); ctx.stroke();
        ctx.fillStyle = "#9ab6bd";
        const age = windowSec - t;
        ctx.fillText(age <= 1e-9 ? "now" : `-${age.toFixed(1)}s`, Math.min(x, w - 28), 10);
      }
      ctx.strokeStyle = "rgba(127, 183, 190, .18)";
      ctx.beginPath(); ctx.moveTo(plot.x0, plot.y1); ctx.lineTo(plot.x1, plot.y1); ctx.stroke();

      // 采样中断区间：涂灰，不补点、不连续连接
      this.sampleGaps.forEach(g => {
        const a = Math.max(tStart, g.t0), b = Math.min(tEnd, g.t1);
        if (b <= a) return;
        const x = plot.x0 + plotW * (a - tStart) / windowSec;
        const ww = plotW * (b - a) / windowSec;
        ctx.fillStyle = "rgba(208, 111, 104, .13)";
        ctx.fillRect(x, plot.y0, Math.max(2, ww), plot.y1 - plot.y0);
      });

      visible.forEach((ci, lane) => {
        const yMid = plot.y0 + laneH * (lane + 0.5);
        const amp = Math.max(3, laneH * 0.36);
        const activeScale = this.waveMode === "raw" ? this.channelScaleRaw[ci] : this.channelScaleProc[ci];
        const scale = Math.max(1e-6, (activeScale || 1) / this.gain);
        ctx.strokeStyle = CH_COLORS[ci % CH_COLORS.length];
        ctx.globalAlpha = 0.95;
        ctx.lineWidth = 1;
        // 每像素 min/max：保留峰值/瞬态，而不是简单丢弃采样点
        const buckets = Math.max(1, Math.round(plotW));
        const mins = new Float32Array(buckets); mins.fill(Infinity);
        const maxs = new Float32Array(buckets); maxs.fill(-Infinity);
        this.waveBatches.forEach(b => {
          const arr = this.waveMode === "raw" ? b.raw : b.processed;
          if (!arr || !arr[ci] || b.t0 == null) return;
          const ch = arr[ci], fs = b.fs || 1;
          for (let i = 0; i < ch.length; i++) {
            const v = ch[i];
            if (!Number.isFinite(v)) continue;
            const t = b.t0 + i / fs;
            if (t < tStart || t > tEnd) continue;
            const bi = clamp(Math.floor((t - tStart) / windowSec * (buckets - 1)), 0, buckets - 1);
            if (v < mins[bi]) mins[bi] = v;
            if (v > maxs[bi]) maxs[bi] = v;
          }
        });
        ctx.beginPath();
        let open = false;
        for (let bi = 0; bi < buckets; bi++) {
          if (!Number.isFinite(mins[bi])) { open = false; continue; }
          const x = plot.x0 + (bi + 0.5) / buckets * plotW;
          const yA = yMid - clamp(maxs[bi] / scale, -3, 3) * amp;
          const yB = yMid - clamp(mins[bi] / scale, -3, 3) * amp;
          if (!open) { ctx.moveTo(x, yA); open = true; } else ctx.lineTo(x, yA);
          ctx.lineTo(x, yB);
        }
        ctx.stroke();
        // lane 分隔和通道名
        ctx.globalAlpha = 1;
        ctx.strokeStyle = "rgba(127, 183, 190, .10)";
        ctx.beginPath(); ctx.moveTo(plot.x0, yMid + laneH / 2); ctx.lineTo(plot.x1, yMid + laneH / 2); ctx.stroke();
        ctx.fillStyle = CH_COLORS[ci % CH_COLORS.length];
        ctx.font = "9px Menlo, Consolas, monospace";
        ctx.fillText(String(names[ci] || `CH${ci + 1}`).slice(0, 8), 3, yMid);
        ctx.fillStyle = "#9ab6bd";
        ctx.fillText(`±${scale >= 10 ? scale.toFixed(0) : scale.toFixed(2)}`, Math.max(3, plot.x1 - 28), yMid);
        if (this.channelOk[ci] === false) {
          ctx.fillStyle = "#e6a29a"; ctx.fillText("×", 3, yMid + 10);
        }
      });
      ctx.globalAlpha = 1;
      const foot = this.$("mon-wave-note");
      if (foot) {
        const progress = this.lastBatch?.source_name === "replay" && this.lastBatch.replay?.progress != null
          ? ` · 进度 ${(Number(this.lastBatch.replay.progress) * 100).toFixed(1)}%` : "";
        foot.textContent = this.streamState === "重连中" ? "数据已停止更新，保留历史波形" :
          (this.paused ? "波形暂停（采集继续）" :
            (this.waveMode === "processed" && !this.waveBatches.some(x => x.processed)
              ? "本窗异常：无处理后波形（未进入算法）" :
              (this.lastBatch?.time_basis === "edf_file" ? "历史 EDF 回放 · 文件内时间" + progress :
                (this.lastBatch?.time_basis === "device_packet_arrival" ? "设备报文到达时间（按 fs 重建）" : ""))));
      }
    }

    renderBands() {
      const el = this.$("mon-bands");
      if (!el) return;
      if (!el.children.length) {
        el.innerHTML = BANDS.map(b => `<div class="mon-band-row" data-band-row="${b.name}">
          <span class="mon-band-name">${b.label}<small></small></span>
          <span class="mon-band-track"><i class="mon-band-fill" style="background:${b.color}"></i></span>
          <span class="mon-band-val">N/A</span></div>`).join("");
      }
      const rows = this.currentBands || [];
      BANDS.forEach(b => {
        const row = el.querySelector(`[data-band-row="${b.name}"]`);
        if (!row) return;
        const item = rows.find(x => x.name === b.name);
        const available = !!item?.available;
        row.classList.toggle("unavailable", !available);
        row.querySelector("small").textContent = item?.range ? `${item.range[0]}–${item.range[1]} Hz` : "";
        const v = available ? clamp(Number(item.rel), 0, 1) : 0;
        row.querySelector(".mon-band-fill").style.width = (v * 100).toFixed(1) + "%";
        row.querySelector(".mon-band-val").textContent = available ? pct(item.rel) : "N/A";
      });
      const note = this.$("mon-band-note");
      if (note) {
        const rp = this.lastBatch?.relative_power;
        const hi = rp?.range_hz?.[1];
        note.textContent = this.currentBands?.some(x => x.available)
          ? `相对功率 · 分母 0–${hi != null ? Math.round(hi) : "Nyquist"} Hz Welch 总功率`
          : "N/A · 当前无特征";
        note.title = rp?.note || "";
      }
    }

    drawBands() {
      const canvas = this.$("mon-band-canvas");
      const details = this.$("mon-band-history");
      if (!canvas || details?.open === false) return;
      const ctx = canvas.getContext("2d");
      const { w, h } = canvasSize(canvas, ctx);
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#0a1217"; ctx.fillRect(0, 0, w, h);
      if (!this.bandHistory.length) return;
      const tEnd = this.latestT ?? this.bandHistory[this.bandHistory.length - 1].t;
      const tStart = tEnd - 30;
      const plot = { x0: 28, x1: w - 5, y0: 8, y1: h - 16 };
      ctx.font = "8px Menlo, Consolas, monospace";
      ctx.textBaseline = "middle";
      [0, 50, 100].forEach(v => {
        const y = plot.y1 - (plot.y1 - plot.y0) * v / 100;
        ctx.strokeStyle = "rgba(127,183,190,.13)"; ctx.beginPath(); ctx.moveTo(plot.x0, y); ctx.lineTo(plot.x1, y); ctx.stroke();
        ctx.fillStyle = "#9ab6bd"; ctx.fillText(v + "%", 1, y);
      });
      BANDS.forEach(b => {
        if (!this.bandFilter.has(b.name)) return;
        ctx.strokeStyle = b.color; ctx.lineWidth = 1.2; ctx.beginPath();
        let open = false, prevT = null;
        this.bandHistory.forEach(pt => {
          const item = pt.by[b.name];
          if (!item?.available || !finite(item.rel)) { open = false; return; }
          if (pt.t < tStart || pt.t > tEnd) { open = false; return; }
          if (prevT != null && pt.t - prevT > 2.2) open = false;
          prevT = pt.t;
          const x = plot.x0 + (plot.x1 - plot.x0) * (pt.t - tStart) / 30;
          const y = plot.y1 - (plot.y1 - plot.y0) * clamp(Number(item.rel), 0, 1);
          if (!open) { ctx.moveTo(x, y); open = true; } else ctx.lineTo(x, y);
        });
        ctx.stroke();
      });
      ctx.fillStyle = "#9ab6bd"; ctx.fillText("-30s", plot.x0, h - 6); ctx.fillText("now", plot.x1 - 18, h - 6);
    }

    drawScore() {
      const canvas = this.$("mon-score-canvas");
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      const { w, h } = canvasSize(canvas, ctx);
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#0a1217"; ctx.fillRect(0, 0, w, h);
      const plot = { x0: 27, x1: w - 5, y0: 8, y1: h - 17 };
      const tNow = this.latestGameT ?? this.latestT;
      if (!finite(tNow)) {
        ctx.fillStyle = "#9ab6bd"; ctx.font = "10px Menlo, monospace"; ctx.fillText("等待游戏驱动分数…", 10, h / 2);
        return;
      }
      const tStart = tNow - 30;
      const xOf = t => plot.x0 + (plot.x1 - plot.x0) * clamp((t - tStart) / 30, 0, 1);
      const yOf = v => plot.y1 - (plot.y1 - plot.y0) * clamp(v, 0, 100) / 100;
      ctx.font = "8px Menlo, Consolas, monospace";
      ctx.textBaseline = "middle";
      [0, 50, 100].forEach(v => {
        const y = yOf(v);
        ctx.strokeStyle = "rgba(127,183,190,.13)"; ctx.beginPath(); ctx.moveTo(plot.x0, y); ctx.lineTo(plot.x1, y); ctx.stroke();
        ctx.fillStyle = "#9ab6bd"; ctx.fillText(String(v), 2, y);
      });
      [this.thresholds.enter, this.thresholds.exit].forEach(v => {
        const y = yOf(v);
        ctx.setLineDash([3, 3]); ctx.strokeStyle = "rgba(226,181,111,.44)";
        ctx.beginPath(); ctx.moveTo(plot.x0, y); ctx.lineTo(plot.x1, y); ctx.stroke(); ctx.setLineDash([]);
      });
      // 信号异常区间：灰色/红色底，不跨断流连线
      for (let i = 1; i < this.scorePoints.length; i++) {
        const a = this.scorePoints[i - 1], b = this.scorePoints[i];
        if (!a.valid || !b.valid || b.t - a.t > 1.5) {
          const x0 = xOf(a.t), x1 = xOf(b.t);
          ctx.fillStyle = "rgba(208,111,104,.14)";
          ctx.fillRect(x0, plot.y0, Math.max(2, x1 - x0), plot.y1 - plot.y0);
        }
      }
      const line = (key, color, width) => {
        ctx.strokeStyle = color; ctx.lineWidth = width; ctx.beginPath();
        let open = false, prevT = null;
        this.scorePoints.forEach(p => {
          if (!p.valid || !finite(p[key])) { open = false; return; }
          if (p.t < tStart || p.t > tNow) { open = false; return; }
          if (prevT != null && p.t - prevT > 1.5) open = false;
          prevT = p.t;
          const x = xOf(p.t), y = yOf(p[key]);
          if (!open) { ctx.moveTo(x, y); open = true; } else ctx.lineTo(x, y);
        });
        ctx.stroke();
      };
      line("raw", "#74a8d6", 1);
      line("smooth", "#8fe3d0", 1.6);
      // 事件标记 + hover 命中区
      this.scoreHits = [];
      this.events.forEach(ev => {
        if (this.eventFilter !== "all" && ev.cls !== this.eventFilter) return;
        if (ev.t < tStart || ev.t > tNow) return;
        const x = xOf(ev.t), y = plot.y0 + 7;
        const meta = EVENT_META[ev.type] || { color: "#ffc37e", symbol: "●" };
        ctx.fillStyle = meta.color;
        ctx.font = "bold 10px Menlo, Consolas, monospace";
        ctx.textAlign = "center";
        ctx.fillText(meta.symbol, x, y + 3);
        ctx.textAlign = "left";
        ctx.strokeStyle = "rgba(255,255,255,.18)"; ctx.beginPath(); ctx.moveTo(x, y + 5); ctx.lineTo(x, plot.y1); ctx.stroke();
        this.scoreHits.push({ x, y, ev });
      });
      ctx.fillStyle = "#9ab6bd"; ctx.fillText("-30s", plot.x0, h - 6);
      ctx.fillText("now", plot.x1 - 18, h - 6);
      // 阈值标注
      ctx.fillStyle = "rgba(226,181,111,.7)";
      ctx.fillText(String(this.thresholds.enter), plot.x1 - 14, yOf(this.thresholds.enter));
      ctx.fillText(String(this.thresholds.exit), plot.x1 - 14, yOf(this.thresholds.exit));
    }

    drawBaseline() {
      const canvas = this.$("mon-baseline-canvas");
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      const { w, h } = canvasSize(canvas, ctx);
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#0a1217"; ctx.fillRect(0, 0, w, h);
      const tNow = this.latestGameT ?? this.latestT;
      if (!finite(tNow)) {
        ctx.fillStyle = "#9ab6bd"; ctx.font = "10px Menlo, monospace";
        ctx.fillText("等待同一算法输出的双基线…", 10, h / 2);
        return;
      }
      const tStart = tNow - 30;
      const plot = { x0: 27, x1: w - 5, y0: 8, y1: h - 17 };
      const xOf = t => plot.x0 + (plot.x1 - plot.x0) * clamp((t - tStart) / 30, 0, 1);
      const yOf = v => plot.y1 - (plot.y1 - plot.y0) * clamp(v, 0, 100) / 100;
      ctx.font = "8px Menlo, Consolas, monospace";
      ctx.textBaseline = "middle";
      [0, 50, 100].forEach(v => {
        const y = yOf(v);
        ctx.strokeStyle = "rgba(127,183,190,.13)";
        ctx.beginPath(); ctx.moveTo(plot.x0, y); ctx.lineTo(plot.x1, y); ctx.stroke();
        ctx.fillStyle = "#9ab6bd"; ctx.fillText(String(v), 2, y);
      });
      // 无效信号区间只标底，不跨越断流连线；不插值。
      for (let i = 1; i < this.baselinePoints.length; i++) {
        const a = this.baselinePoints[i - 1], b = this.baselinePoints[i];
        if (!a.valid || !b.valid || b.t - a.t > 1.5) {
          ctx.fillStyle = "rgba(208,111,104,.14)";
          ctx.fillRect(xOf(a.t), plot.y0, Math.max(2, xOf(b.t) - xOf(a.t)),
                       plot.y1 - plot.y0);
        }
      }
      const line = (key, color, width, dashed) => {
        ctx.strokeStyle = color; ctx.lineWidth = width;
        ctx.setLineDash(dashed ? [4, 3] : []);
        ctx.beginPath();
        let open = false, prevT = null;
        this.baselinePoints.forEach(p => {
          const value = p[key];
          if (!p.valid || !finite(value)) { open = false; return; }
          if (p.t < tStart || p.t > tNow) { open = false; return; }
          if (prevT != null && p.t - prevT > 1.5) open = false;
          prevT = p.t;
          const x = xOf(p.t), y = yOf(value);
          if (!open) { ctx.moveTo(x, y); open = true; } else ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.setLineDash([]);
      };
      line("daily", "#8fe3d0", 2.0, false);
      line("reference", "#c49bea", 1.6, true);
      // 末端点标记：即使两条线短暂重合，也能看出各自最新值。
      const latest = this.baselinePoints[this.baselinePoints.length - 1];
      if (latest && latest.valid) {
        [[latest.daily, "#8fe3d0"], [latest.reference, "#c49bea"]].forEach(([v, color]) => {
          if (!finite(v)) return;
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(xOf(latest.t), yOf(v), 2.4, 0, Math.PI * 2);
          ctx.fill();
        });
      }
      ctx.fillStyle = "#9ab6bd";
      ctx.fillText("-30s", plot.x0, h - 6);
      ctx.fillText("now", plot.x1 - 18, h - 6);
    }

    _showScoreTip(e) {
      const tip = this.$("mon-score-tip");
      const canvas = this.$("mon-score-canvas");
      if (!tip || !canvas || !this.scoreHits.length) return;
      const r = canvas.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      let best = null, bestD = 12;
      this.scoreHits.forEach(h => {
        const d = Math.hypot(h.x - x, h.y - y);
        if (d < bestD) { bestD = d; best = h; }
      });
      if (!best) { tip.style.display = "none"; return; }
      const ev = best.ev;
      let detail = "";
      if (ev.detail) {
        detail = Object.entries(ev.detail).slice(0, 4)
          .map(([k, v]) => `${k}: ${detailValue(v)}`).join("\n");
      }
      tip.textContent = `${ev.t.toFixed(1)}s · ${ev.label}${detail ? "\n" + detail : ""}`;
      tip.style.display = "block";
      tip.style.left = Math.min(r.width - 150, Math.max(4, x + 8)) + "px";
      tip.style.top = Math.max(4, Math.min(r.height - 40, y + 8)) + "px";
    }

    renderAlgo() {
      const el = this.$("mon-algo");
      if (!el) return;
      const b = this.lastBatch;
      const a = b?.algorithm || {};
      const modeEl = this.$("mon-algo-mode");
      if (modeEl) modeEl.textContent = a.available
        ? (a.mode === "band" ? "频段工程指标" : "模型推理") : "N/A";
      const rows = [];
      const add = (k, v, em = false, title = "") => rows.push(
        `<dt title="${esc(title)}">${k}</dt><dd class="${em ? "em" : ""}">${esc(v)}</dd>`);
      add("特征模式", a.available ? a.mode : "N/A");
      if (a.mode === "band") {
        add("β/(θ+α) 比值", num(a.ratio, 3), true, "实际算法使用相对功率均值");
        add("Sigmoid 映射", pct(a.sigmoid), true);
        add("中心 / 斜率", a.band_focus ? `${a.band_focus.center} / ${a.band_focus.slope}` : "N/A");
      } else {
        add("θ/β 比值（特征）", num(a.ratio, 3), true);
        add("模型概率", pct(a.probability), true);
      }
      add("平滑前专注值", pct(a.raw_focus));
      add("平滑后专注值", pct(a.smooth_focus), true);
      add("游戏驱动分数 S_daily", num(a.game_score, 1) + " / 100", true);
      const cal = b?.calibration || {};
      add("当日校准", cal.id ? `${cal.id} · ${cal.status || "unknown"}` : "N/A");
      add("长期参考基线", cal.reference_baseline_id
        ? `${cal.reference_baseline_id} · ${cal.reference_version || "?"}` : "N/A");
      add("参考映射 S_reference", num(cal.reference_score, 1) + " / 100",
        false, "仅后台趋势记录，不参与蓄力/得分/商城");
      const diff = b?.difficulty || {};
      add("自动难度系数", diff.factor != null ? num(diff.factor, 3) : "—",
        true, "只影响黄色区域起点随机范围");
      add("黄色区域起点", diff.zone_low_min != null && diff.zone_low_max != null
        ? `${num(diff.zone_low_min, 1)} – ${num(diff.zone_low_max, 1)}%` : "—");
      add("难度策略版本", diff.strategy_version || "—");
      add("有效采集", cal.effective_sec != null ? `${num(cal.effective_sec, 1)}s` : "N/A");
      add("平滑系数 α", num(a.ema_alpha, 2));
      add("个人校准区间", a.score_range ? `${a.score_range.low.toFixed(3)} – ${a.score_range.high.toFixed(3)}` : "N/A");
      add("蓄力阈值（零点/进/出）",
        `${this.roundConfig.chargeZeroScore ?? 42} / ${this.thresholds.enter} / ${this.thresholds.exit}`);
      add("宽容/冷却/子弹",
        `${num(this.roundConfig.graceSec, 1)}s / ${num(this.roundConfig.invalidTapCooldownSec, 1)}s / ${num(this.roundConfig.bulletTimeSec, 1)}s`);
      if (a.fused_focus != null) add("融合后专注值", pct(a.fused_focus), false, "无新鲜心率读数时等于平滑后专注值");
      add("说明", "游戏相对指标，不是临床注意力判断");
      el.innerHTML = rows.join("");
    }

    renderStatus() {
      const el = this.$("mon-status");
      if (!el) return;
      const s = this.getState?.() || {};
      const b = this.lastBatch;
      const cfg = this.roundConfig || {};
      const stale = !!s.stale;
      const phase = s.phase || "—";
      const round = this.getRound?.() || null;
      const chargeSpeed = !stale && phase === "CHARGING" && s.scoreSmooth > (cfg.chargeZeroScore ?? 42)
        ? global.FocusRound?.chargeSpeed(s.scoreSmooth, cfg) : null;
      const bulletElapsed = round?.bulletElapsed ?? s.bulletElapsed;
      const bulletLeft = phase === "BULLET_TIME" && finite(bulletElapsed)
        ? Math.max(0, (cfg.bulletTimeSec ?? 2.5) - Number(bulletElapsed)) : null;
      const multiplier = phase === "BULLET_TIME" && global.FocusRound
        ? global.FocusRound.timingMultiplier(Number(bulletElapsed || 0), cfg)
        : (finite(round?.multiplier) ? Number(round.multiplier) : null);
      const potential = round?.potential ?? s.potential;
      const quality = b?.quality;
      const qText = quality
        ? `${quality.level || "—"} · ${(quality.flags || []).join(", ")}`
        : (b?.source_name === "replay" ? "历史回放（无实时质量）" : "—");
      const source = this.initialSource?.label || this.initialSource?.name || "—";
      const rows = [
        ["当前信号源", source],
        ["连接状态", this.streamState],
        ["实际采样率", b?.fs ? `${b.fs} Hz（配置值）` : "—"],
        ["通道数量", this.channelNames.length || "—"],
        ["信号质量", qText],
        ["最近数据", b?.t1 != null
          ? `${Number(b.t1).toFixed(2)} s${this.lastReceive ? ` · ${Math.max(0, (performance.now() - this.lastReceive) / 1000).toFixed(1)}s 前` : ""}`
          : "—"],
        ["脑电驱动分数", stale ? "—" : num(s.norm, 1)],
        ["当前蓄力速度", chargeSpeed == null ? "—" : `${chargeSpeed.toFixed(2)} %/s`],
        ["当前蓄力进度", !stale && phase === "CHARGING" ? `${num(s.energy, 0)} %` : "—"],
        ["黄色区域范围", cfg.zoneLoMin != null
          ? `${num(cfg.zoneLoMin, 1)} – ${num(cfg.zoneLoMax, 1)}%` : "—"],
        ["游戏阶段", phase],
        ["冷却剩余", phase === "CHARGING" && s.cooldownRemaining > 0 ? `${num(s.cooldownRemaining, 2)} s` : "—"],
        ["子弹时间剩余", bulletLeft == null ? "—" : `${num(bulletLeft, 2)} s`],
        ["本轮基础得分", finite(potential) ? num(potential, 0) : "—"],
        ["当前点击倍率", multiplier == null ? "—" : num(multiplier, 2)],
        ["本局累计积分", num(s.score, 0)],
      ];
      if (b?.source_name === "replay" && b.replay?.progress != null) {
        rows.splice(6, 0, ["回放进度", `${(Number(b.replay.progress) * 100).toFixed(1)}%`]);
      }
      el.innerHTML = rows.map(([k, v]) =>
        `<div class="mon-stat"><span>${k}</span><b class="${v === "—" ? "muted" : ""}" title="${esc(v)}">${esc(v)}</b></div>`).join("");
      const fresh = this.$("mon-status-fresh");
      if (fresh) {
        fresh.textContent = stale ? "信号冻结" : (this.paused ? "波形暂停" : "实时");
        fresh.style.color = stale ? "#e6a29a" : "#6f9aa3";
      }
    }

    renderEvents() {
      const el = this.$("mon-events");
      if (!el) return;
      let list = this.events.slice(-80);
      if (this.eventFilter !== "all") list = list.filter(e => e.cls === this.eventFilter);
      list = list.slice(-10).reverse();
      if (!list.length) { el.innerHTML = `<li class="empty">暂无事件</li>`; return; }
      el.innerHTML = list.map(e => {
        let detail = "";
        if (e.detail) {
          detail = " · " + Object.entries(e.detail).slice(0, 3)
            .map(([k, v]) => `${k}=${detailValue(v)}`).join(" ");
        }
        const meta = EVENT_META[e.type] || { symbol: "·" };
        return `<li class="${e.cls}"><time>${e.t.toFixed(1)}s</time><span>${meta.symbol} ${esc(e.label)}${esc(detail)}</span></li>`;
      }).join("");
    }

    render() {
      this.renderBands();
      this.renderAlgo();
      this.renderStatus();
      this.renderEvents();
      this.draw();
    }
  }

  global.EEGMonitor = {
    create(opts) { return new EEGMonitor(opts); },
    BANDS,
  };
})(typeof window !== "undefined" ? window : globalThis);
