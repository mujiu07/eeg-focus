/* ============================================================
   专注小蛙 · 单轮核心机制
   ------------------------------------------------------------
   把「脑电蓄力 → 宽容期 → 能量衰减 → 唯一金色区域 → 子弹时间
   → 锁定潜在得分 → 点击兑现 / 错过归零」抽成不依赖 DOM 的纯逻辑，
   浏览器里挂到 window.FocusRound，Node 里可直接 require 做模拟测试。

   设计约束（对应 docs/TECH-DESIGN.md）：
   - 蓄力速度只由映射分数决定，且永远不为负；
   - 低于蓄力阈值先进入宽容期，超过宽容期才缓慢衰减；
   - 每轮只生成一个金色区域，错过不补、不重掷；
   - 子弹时间以固定时长穿过金色区域，所有玩家窗口一致；
   - 潜在得分在进入金色区域时锁定，之后不再重算。
   ============================================================ */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.FocusRound = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const CONFIG = Object.freeze({
    // ---- 蓄力：沿用既有分数口径 ----
    chargeZeroScore: 42,          // 低于此分蓄力速度为 0（原公式的零点）
    chargeGainPerScoreSec: 0.16,  // 每 1 分超出零点，每秒增加的蓄力百分点
    vRefScore: 65,                // 基准蓄力速度对应的映射分数
    startEnergy: 15,              // 每轮起始蓄力值（原实现落地后为 15）

    // ---- 宽容期与衰减 ----
    graceSec: 1.5,                // 连续低于阈值多久后开始衰减
    decayRatio: 0.30,             // 衰减速度 = 基准蓄力速度 × 30%

    // ---- 金色区域：每轮只生成一次 ----
    zoneLoMin: 24,
    zoneLoMax: 55,
    zoneWidth: 6,
    firstRoundLoMin: 22,          // 第一轮稍早出现，避免开局干等
    firstRoundLoMax: 34,
    zoneHiMax: 92,                // 金色区域末端上限，避免贴满

    // ---- 子弹时间 ----
    bulletTimeSec: 2.5,

    // ---- 计分 ----
    scoreBase: 20,
    scoreSpan: 80,
    scoreMin: 20,
    scoreMax: 100,

    // ---- 积分经济：表现分与商城积分分离 ----
    pointsDivisor: 30,            // 商城积分 = max(1, floor(本局表现分 / 30))（有得分时）
  });

  function clamp(v, lo, hi) {
    return Math.min(hi, Math.max(lo, v));
  }

  function finite(v, fallback) {
    return Number.isFinite(Number(v)) ? Number(v) : fallback;
  }

  /** 某一映射分数下的蓄力速度（百分点/秒）。分数低于零点时返回 0，绝不出现负增益。 */
  function chargeSpeed(score, cfg) {
    const c = cfg || CONFIG;
    const s = finite(score, c.chargeZeroScore);
    return Math.max(0, (s - c.chargeZeroScore) * c.chargeGainPerScoreSec);
  }

  /** 基准蓄力速度 V_ref（百分点/秒）。 */
  function referenceSpeed(cfg) {
    const c = cfg || CONFIG;
    return chargeSpeed(c.vRefScore, c);
  }

  /** 衰减速度（百分点/秒）= V_ref × decayRatio。 */
  function decaySpeed(cfg) {
    const c = cfg || CONFIG;
    return referenceSpeed(c) * c.decayRatio;
  }

  /**
   * 潜在得分：S = round(20 + 80 × T_ref / (T + T_ref))，T_ref = D / V_ref。
   * D 为回合初始蓄力值到金色区域起点的距离，T 为实际有效蓄力用时。
   * 随机位置被 T_ref 归一化；T 越小（蓄力越快）得分越高，且始终落在 [20,100]。
   */
  function computePotentialScore(distance, chargeSec, cfg) {
    const c = cfg || CONFIG;
    const d = Math.max(0, finite(distance, 0));
    const t = Math.max(0, finite(chargeSec, 0));
    const vRef = referenceSpeed(c);
    const tRef = vRef > 0 ? d / vRef : 0;
    if (tRef <= 0) return c.scoreMin;
    const raw = c.scoreBase + c.scoreSpan * (tRef / (t + tRef));
    return clamp(Math.round(raw), c.scoreMin, c.scoreMax);
  }

  function referenceTime(distance, cfg) {
    const c = cfg || CONFIG;
    const vRef = referenceSpeed(c);
    return vRef > 0 ? Math.max(0, finite(distance, 0)) / vRef : 0;
  }

  /** 表现分 → 商城积分。只影响入账，不改变报告里的表现分。 */
  function pointsForScore(score, cfg) {
    const c = cfg || CONFIG;
    const n = Math.max(0, finite(score, 0));
    if (n <= 0) return 0;
    const divisor = Math.max(1, c.pointsDivisor);
    // 有得分至少 1 积分，避免一次成功的低分跳跃在结算时显示 +0。
    return Math.max(1, Math.floor(n / divisor));
  }

  function round3(v) {
    return Math.round(v * 1000) / 1000;
  }

  class RoundEngine {
    /**
     * @param {object} [config] 覆盖 CONFIG 的参数（便于真机调参）
     * @param {function} [rng] 随机源，默认 Math.random
     * @param {object} [options] { firstRound: boolean }
     */
    constructor(config, rng, options) {
      this.config = Object.assign({}, CONFIG, config || {});
      this.rng = typeof rng === "function" ? rng : Math.random;
      this.records = [];
      this.roundIndex = 0;
      this._opts = options || {};
      this._startRound(!!this._opts.firstRound);
    }

    _startRound(firstRound) {
      const c = this.config;
      const loMin = firstRound ? c.firstRoundLoMin : c.zoneLoMin;
      const loMax = firstRound
        ? Math.max(loMin, c.firstRoundLoMax)
        : Math.max(loMin, c.zoneLoMax);
      const r = clamp(finite(this.rng(), 0.5), 0, 1);
      const lo = loMin + (loMax - loMin) * r;
      const hi = Math.min(c.zoneHiMax, lo + c.zoneWidth);

      this.roundIndex += 1;
      this.phase = "CHARGING";        // CHARGING | BULLET_TIME | JUMP_SUCCESS | JUMP_MISSED
      this.zone = { lo: round3(lo), hi: round3(hi), width: round3(hi - lo) };
      this.startEnergy = c.startEnergy;
      this.energy = c.startEnergy;
      this.chargeSec = 0;             // 本轮有效蓄力用时（含等待/宽容/衰减，不含异常与子弹时间）
      this.belowSec = 0;              // 连续低于阈值的时长
      this.decaying = false;
      this.decayEvents = 0;
      this.decaySec = 0;
      this.staleSec = 0;              // 本轮信号异常累计时长
      this.bulletElapsed = 0;
      this.potential = null;
      this.awarded = null;
      this.reactionSec = null;
      this.earlyTaps = 0;
      this.settled = false;
      this._scoreSum = 0;
      this._scoreN = 0;
      this._aboveN = 0;
    }

    /**
     * 推进一帧。
     * @param {number} dt 秒
     * @param {{signalOk: boolean, charging: boolean, score: number, paused?: boolean}} input
     * @returns {Array<{type: string, potential?: number}>} 事件
     */
    update(dt, input) {
      const c = this.config;
      const step = Math.max(0, finite(dt, 0));
      const out = [];
      if (step <= 0) return out;
      if (this.phase === "JUMP_SUCCESS" || this.phase === "JUMP_MISSED") return out;

      const signalOk = !(input && input.signalOk === false);
      const paused = !!(input && input.paused);

      // 设备断流 / 主动暂停：冻结蓄力、衰减与本轮计时，只记录异常时长。
      if (!signalOk) {
        this.staleSec += step;
        return out;
      }
      if (paused) return out;

      const score = finite(input && input.score, c.chargeZeroScore);

      if (this.phase === "CHARGING") {
        // 计时包含正常蓄力、等待、宽容期与衰减；异常帧与暂停在上面已提前返回。
        this.chargeSec += step;
        this._scoreSum += score;
        this._scoreN += 1;
        // 达标 = 本帧实际处于有效蓄力状态（滞回 + 高于零点），与游戏判定口径一致。
        if (input && input.charging) this._aboveN += 1;

        if (input && input.charging) {
          this.belowSec = 0;
          this.decaying = false;
          const gain = chargeSpeed(score, c) * step;
          if (gain > 0) this.energy += gain;   // 负增益已被 chargeSpeed 钳成 0
        } else {
          this.belowSec += step;
          if (this.belowSec >= c.graceSec) {
            if (!this.decaying) {
              this.decaying = true;
              this.decayEvents += 1;
            }
            this.energy -= decaySpeed(c) * step;
            this.decaySec += step;
          }
        }

        this.energy = clamp(this.energy, 0, 100);

        // 首次进入金色区域：立即锁定本帧位置与潜在得分，进入子弹时间。
        if (this.energy >= this.zone.lo) {
          this.energy = this.zone.lo;
          this.potential = computePotentialScore(
            this.zone.lo - this.startEnergy, this.chargeSec, c);
          this.phase = "BULLET_TIME";
          this.bulletElapsed = 0;
          out.push({ type: "bullet_enter", potential: this.potential });
        }
        return out;
      }

      if (this.phase === "BULLET_TIME") {
        // 固定时长穿过整个金色区域：slowSpeed = width / bulletTimeSec。
        this.bulletElapsed = Math.min(c.bulletTimeSec, this.bulletElapsed + step);
        const k = c.bulletTimeSec > 0 ? this.bulletElapsed / c.bulletTimeSec : 1;
        this.energy = clamp(this.zone.lo + this.zone.width * k, this.zone.lo, this.zone.hi);

        if (this.bulletElapsed >= c.bulletTimeSec - 1e-9) {
          // 错过：普通跳跃、零分，本轮不再等待蓄满、不再生成第二个金色区域。
          this.phase = "JUMP_MISSED";
          this.settled = true;
          this.awarded = 0;
          this.reactionSec = null;
          out.push({ type: "miss" });
        }
      }
      return out;
    }

    /**
     * 点击。只有子弹时间内第一次点击有效；提前点击只计数，不扣分也不清空蓄力。
     * @returns {{type: "success"|"early"|"ignored", score?: number, reactionSec?: number}}
     */
    tap() {
      if (this.phase === "BULLET_TIME" && !this.settled) {
        this.settled = true;
        this.awarded = this.potential;
        this.reactionSec = this.bulletElapsed;
        this.phase = "JUMP_SUCCESS";
        return { type: "success", score: this.potential, reactionSec: this.reactionSec };
      }
      if (this.phase === "CHARGING") {
        this.earlyTaps += 1;
        return { type: "early" };
      }
      return { type: "ignored" };
    }

    /** 结算本轮并开始下一轮。只在跳跃动画与视角归位结束后调用。 */
    finishRound() {
      let record = null;
      if (this.phase === "JUMP_SUCCESS" || this.phase === "JUMP_MISSED") {
        const c = this.config;
        const distance = Math.max(0, this.zone.lo - this.startEnergy);
        record = {
          round: this.roundIndex,
          charge_sec: round3(this.chargeSec),
          zone_lo: round3(this.zone.lo),
          zone_hi: round3(this.zone.hi),
          t_ref: round3(referenceTime(distance, c)),
          potential: this.potential,
          awarded: this.awarded,
          success: this.phase === "JUMP_SUCCESS",
          reaction_sec: this.reactionSec == null ? null : round3(this.reactionSec),
          mean_score: this._scoreN ? round3(this._scoreSum / this._scoreN) : null,
          above_ratio: this._scoreN ? round3(this._aboveN / this._scoreN) : null,
          decay_events: this.decayEvents,
          decay_sec: round3(this.decaySec),
          stale_sec: round3(this.staleSec),
          early_taps: this.earlyTaps,
        };
        this.records.push(record);
      }
      this._startRound(false);
      return record;
    }

    /** 当前帧的只读快照，便于 HUD / 测试。 */
    snapshot() {
      return {
        phase: this.phase,
        energy: round3(this.energy),
        zone: Object.assign({}, this.zone),
        chargeSec: round3(this.chargeSec),
        belowSec: round3(this.belowSec),
        decaying: this.decaying,
        decayEvents: this.decayEvents,
        decaySec: round3(this.decaySec),
        staleSec: round3(this.staleSec),
        bulletElapsed: round3(this.bulletElapsed),
        potential: this.potential,
        awarded: this.awarded,
        reactionSec: this.reactionSec,
        earlyTaps: this.earlyTaps,
        settled: this.settled,
        roundIndex: this.roundIndex,
      };
    }
  }

  return {
    CONFIG,
    RoundEngine,
    chargeSpeed,
    referenceSpeed,
    referenceTime,
    decaySpeed,
    computePotentialScore,
    pointsForScore,
  };
});
