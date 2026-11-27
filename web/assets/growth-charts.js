/* 原生 Canvas 图表，完全离线；缺失值断开，不插值。 */
(function () {
  "use strict";
  const DPR = () => Math.min(2, window.devicePixelRatio || 1);
  const COLORS = ["#4c9a6e", "#d29a45", "#6c86c9", "#b16aa0", "#5aa6b4"];

  function prep(canvas) {
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(280, Math.floor(rect.width || canvas.parentElement.clientWidth || 640));
    const height = Math.max(150, Math.floor(rect.height || 220));
    const dpr = DPR();
    if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
      canvas.width = width * dpr;
      canvas.height = height * dpr;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.font = '11px "PingFang SC", "Hiragino Sans GB", sans-serif';
    ctx.fillStyle = "#5c7b83";
    return { ctx, width, height };
  }

  function drawEmpty(ctx, width, height, text) {
    ctx.fillStyle = "#8aa0a6";
    ctx.textAlign = "center";
    ctx.fillText(text || "暂无可绘制数据", width / 2, height / 2);
    ctx.textAlign = "left";
  }

  function axis(ctx, left, top, right, bottom) {
    ctx.strokeStyle = "rgba(92,123,131,.25)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(left, top);
    ctx.lineTo(left, bottom);
    ctx.lineTo(right, bottom);
    ctx.stroke();
  }

  function collectNumbers(series) {
    const out = [];
    (series || []).forEach(s => (s.points || []).forEach(p => {
      if (p && p.value !== null && p.value !== undefined && Number.isFinite(Number(p.value))) {
        out.push(Number(p.value));
      }
    }));
    return out;
  }

  function bar(canvas, points, opts) {
    const p = prep(canvas);
    if (!p) return;
    const { ctx, width, height } = p;
    if (!points || !points.length) { drawEmpty(ctx, width, height); return; }
    const left = 38, right = width - 12, top = 14, bottom = height - 30;
    const values = points.map(d => d.value === null || d.value === undefined ? 0 : Number(d.value) || 0);
    const maxValue = Math.max.apply(null, values.concat([1]));
    axis(ctx, left, top, right, bottom);
    const slot = (right - left) / Math.max(1, points.length);
    points.forEach((d, i) => {
      const raw = d.value === null || d.value === undefined ? 0 : Number(d.value) || 0;
      const h = (raw / maxValue) * (bottom - top);
      const x = left + i * slot + 2;
      const w = Math.max(1, slot - 4);
      const grd = ctx.createLinearGradient(0, bottom - h, 0, bottom);
      grd.addColorStop(0, d.quality ? "#d8a25a" : "#6cc18a");
      grd.addColorStop(1, d.quality ? "#f3d4a6" : "#b8e5c7");
      ctx.fillStyle = grd;
      ctx.fillRect(x, bottom - h, w, h);
    });
    const step = Math.max(1, Math.ceil(points.length / 7));
    ctx.fillStyle = "#5c7b83";
    points.forEach((d, i) => {
      if (i % step === 0 || i === points.length - 1) {
        ctx.textAlign = i === 0 ? "left" : (i === points.length - 1 ? "right" : "center");
        ctx.fillText(String(d.label || "").slice(5), left + i * slot + slot / 2, bottom + 16);
      }
    });
    ctx.textAlign = "left";
    ctx.fillStyle = "#23464f";
    ctx.fillText((opts && opts.unit) || "", 4, 10);
  }

  function line(canvas, series, opts) {
    const p = prep(canvas);
    if (!p) return;
    const { ctx, width, height } = p;
    const all = collectNumbers(series);
    if (!all.length) { drawEmpty(ctx, width, height, (opts && opts.empty) || "数据不足，暂不绘制趋势"); return; }
    const left = 40, right = width - 12, top = 14, bottom = height - 30;
    let low = Math.min.apply(null, all);
    let high = Math.max.apply(null, all);
    if (opts && opts.percent) { low = 0; high = 1; }
    if (low === high) { low = Math.max(0, low - 0.5); high = high + 0.5; }
    const labels = (opts && opts.labels) || [];
    const labelIndex = {};
    labels.forEach((label, i) => { labelIndex[label] = i; });
    const xFor = (point, seriesIndex, seriesCount, length) => {
      if (Object.prototype.hasOwnProperty.call(labelIndex, point.label)) {
        return left + (right - left) * (labels.length <= 1 ? 0.5 : labelIndex[point.label] / (labels.length - 1));
      }
      return left + (right - left) * (length <= 1 ? 0.5 : seriesIndex / Math.max(1, length - 1));
    };
    const yFor = value => bottom - ((Number(value) - low) / (high - low)) * (bottom - top);
    axis(ctx, left, top, right, bottom);
    if (opts && opts.percent) {
      ctx.fillStyle = "#8aa0a6";
      ctx.fillText("100%", 4, top + 4);
      ctx.fillText("0%", 4, bottom - 2);
    }
    (series || []).forEach((s, si) => {
      const color = s.color || COLORS[si % COLORS.length];
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 2;
      const points = s.points || [];
      let previous = null;
      points.forEach((point, i) => {
        if (!point || point.value === null || point.value === undefined || !Number.isFinite(Number(point.value))) {
          previous = null;
          return;
        }
        const x = xFor(point, i, si, points.length);
        const y = yFor(point.value);
        if (previous) {
          ctx.beginPath();
          ctx.moveTo(previous.x, previous.y);
          ctx.lineTo(x, y);
          ctx.stroke();
        }
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fill();
        previous = { x, y };
      });
    });
    const step = Math.max(1, Math.ceil(labels.length / 7));
    ctx.fillStyle = "#5c7b83";
    labels.forEach((label, i) => {
      if (i % step === 0 || i === labels.length - 1) {
        const x = left + (right - left) * (labels.length <= 1 ? 0.5 : i / (labels.length - 1));
        ctx.textAlign = i === 0 ? "left" : (i === labels.length - 1 ? "right" : "center");
        ctx.fillText(String(label).slice(5), x, bottom + 16);
      }
    });
    ctx.textAlign = "left";
    ctx.fillStyle = "#23464f";
    if (opts && opts.unit) ctx.fillText(opts.unit, 4, 10);
  }

  function step(canvas, points, opts) {
    const p = prep(canvas);
    if (!p) return;
    const { ctx, width, height } = p;
    if (!points || !points.length) { drawEmpty(ctx, width, height, "暂无难度调整记录"); return; }
    const values = [];
    points.forEach(d => {
      if (Number.isFinite(Number(d.before))) values.push(Number(d.before));
      if (Number.isFinite(Number(d.after))) values.push(Number(d.after));
    });
    if (!values.length) { drawEmpty(ctx, width, height); return; }
    const left = 40, right = width - 12, top = 14, bottom = height - 30;
    const low = Math.min.apply(null, values) - 0.03;
    const high = Math.max.apply(null, values) + 0.03;
    const yFor = v => bottom - ((v - low) / Math.max(0.01, high - low)) * (bottom - top);
    axis(ctx, left, top, right, bottom);
    ctx.strokeStyle = "#d29a45";
    ctx.lineWidth = 2;
    let previous = null;
    points.forEach((d, i) => {
      const x = left + (right - left) * (points.length <= 1 ? 0.5 : i / (points.length - 1));
      const before = Number(d.before);
      const after = Number(d.after);
      if (!Number.isFinite(before) || !Number.isFinite(after)) return;
      if (previous) {
        ctx.beginPath();
        ctx.moveTo(previous.x, previous.y);
        ctx.lineTo(x, previous.y);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(x, previous.y);
        ctx.lineTo(x, yFor(after));
        ctx.stroke();
      }
      ctx.fillStyle = d.direction === "down" ? "#c78336" : "#4c9a6e";
      ctx.beginPath();
      ctx.arc(x, yFor(after), 3.5, 0, Math.PI * 2);
      ctx.fill();
      previous = { x, y: yFor(after) };
    });
    ctx.fillStyle = "#5c7b83";
    points.forEach((d, i) => {
      if (points.length <= 7 || i === 0 || i === points.length - 1) {
        const x = left + (right - left) * (points.length <= 1 ? 0.5 : i / (points.length - 1));
        ctx.textAlign = i === 0 ? "left" : (i === points.length - 1 ? "right" : "center");
        ctx.fillText(String(d.date || "").slice(5), x, bottom + 16);
      }
    });
    ctx.textAlign = "left";
    ctx.fillStyle = "#23464f";
    ctx.fillText("难度系数", 4, 10);
  }

  window.GrowthCharts = { bar, line, step, COLORS };
})();
