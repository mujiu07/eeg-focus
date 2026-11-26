/* ============================================================
   专注小蛙 · 单轮核心机制
   ------------------------------------------------------------
   把「脑电蓄力 → 宽容期 → 能量衰减 → 唯一金色区域 → 子弹时间
   → 锁定脑电基础得分 → 按点击时机兑现 / 错过归零」抽成不依赖
   DOM 的纯逻辑，浏览器里挂到 window.FocusRound，Node 里可直接
   require 做模拟测试。

   设计约束（对应 docs/TECH-DESIGN.md）：
   - 蓄力速度只由映射分数决定，且永远不为负；
   - 低于蓄力阈值先进入宽容期，超过宽容期才缓慢衰减；
   - 每轮只生成一个金色区域，错过不补、不重掷；
   - 子弹时间固定时长，前 0.6 s 满分，之后最多折损 10%；
   - 脑电基础得分在进入金色区域时锁定，之后不再重算；
   - 非金色区域的无效点击只触发短暂冷却，不扣分、不清空蓄力。
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

    // ---- 子弹时间与点击时机 ----
    bulletTimeSec: 2.5,
    fullScoreGraceSec: 0.6,       // 进入金色区域后的满分宽容期
    maxTimingLoss: 0.10,          // 窗口结束前最多折损 10%
    gainCueSec: 1.0,              // 成功后的 “+N” 显示时长

    // ---- 无效点击冷却 ----
    invalidTapCooldownSec: 0.5,   // 非金色区域点击后的蓄力冷却

    // ---- 计分 ----
    scoreBase: 20,
    scoreSpan: 80,
    scoreMin: 20,
    scoreMax: 100,

    // ---- 积分经济：游戏积分与商城货币分离 ----
    pointsDivisor: 30,            // 商城积分 = max(1, floor(本局累计积分 / 30))（有得分时）
  });

  function clamp(v, lo, hi) {
    return Math.min(hi, Math.max(lo, v));
  }

  function finite(v, fallback) {
    return Number.isFinite(Number(v)) ? Number(v) : fallback;
  }

  /**
   * 参数合法性检查。返回错误列表；空数组表示合法。
   * 满分宽容期必须严格短于子弹时间，避免出现除零或“永远满分”。
   */
  function validateConfig(cfg) {
    const c = Object.assign({}, CONFIG, cfg || {});
    const errors = [];
    if (!(finite(c.bulletTimeSec, 0) > 0)) {
      errors.push("bulletTimeSec 必须大于 0");
    }
    if (!(finite(c.fullScoreGraceSec, -1) >= 0)) {
      errors.push("fullScoreGraceSec 不能为负");
    } else if (finite(c.fullScoreGraceSec, 0) >= finite(c.bulletTimeSec, 0)) {
      errors.push("fullScoreGraceSec 必须短于 bulletTimeSec");
    }
    if (!(finite(c.maxTimingLoss, -1) >= 0 && finite(c.maxTimingLoss, 2) <= 1)) {
      errors.push("maxTimingLoss 必须在 0–1 之间");
    }
    if (!(finite(c.invalidTapCooldownSec, -1) >= 0)) {
      errors.push("invalidTapCooldownSec 不能为负");
    }
    if (!(finite(c.graceSec, -1) >= 0)) {
      errors.push("graceSec 不能为负");
    }
    if (!(finite(c.decayRatio, -1) >= 0 && finite(c.decayRatio, 2) <= 1)) {
      errors.push("decayRatio 必须在 0–1 之间");
    }
    if (!(finite(c.gainCueSec, -1) >= 0)) {
      errors.push("gainCueSec 不能为负");
    }
    return errors;
  }

  /** 把可调参数收敛到安全范围；合法配置不会被改动。 */
  function normalizeConfig(cfg) {
    const c = Object.assign({}, CONFIG, cfg || {});
    c.bulletTimeSec = Math.max(0.1, finite(c.bulletTimeSec, CONFIG.bulletTimeSec));
    c.fullScoreGraceSec = clamp(
      finite(c.fullScoreGraceSec, CONFIG.fullScoreGraceSec), 0, c.bulletTimeSec * 0.95);
    c.maxTimingLoss = clamp(finite(c.maxTimingLoss, CONFIG.maxTimingLoss), 0, 1);
    c.invalidTapCooldownSec = Math.max(
      0, finite(c.invalidTapCooldownSec, CONFIG.invalidTapCooldownSec));
    c.graceSec = Math.max(0, finite(c.graceSec, CONFIG.graceSec));
    c.decayRatio = clamp(finite(c.decayRatio, CONFIG.decayRatio), 0, 1);
    c.gainCueSec = Math.max(0, finite(c.gainCueSec, CONFIG.gainCueSec));
    return c;
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
   * 脑电基础分 B：B = round(20 + 80 × T_ref / (T + T_ref))，T_ref = D / V_ref。
   * D 为回合初始蓄力值到金色区域起点的距离，T 为实际有效蓄力用时。
   * 随机位置被 T_ref 归一化；T 越小（蓄力越快）基础分越高，且始终落在 [20,100]。
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

  /**
   * 点击时机倍率：
   *   0 ≤ t ≤ G       → 1
   *   G < t < W       → 1 − R × (t − G) / (W − G)
   *   t ≥ W           → 0
   * 默认 G=0.6s、W=2.5s、R=0.1，所以窗口内最多折损 10%。
   */
  function timingMultiplier(t, cfg) {
    const c = normalizeConfig(cfg);
    const g = c.fullScoreGraceSec;
    const w = c.bulletTimeSec;
    const loss = c.maxTimingLoss;
    const x = Math.max(0, finite(t, 0));
    if (x >= w) return 0;
    if (x <= g) return 1;
    return clamp(1 - loss * (x - g) / Math.max(1e-9, w - g), 0, 1);
  }

  /** 实际游戏积分 = round(脑电基础得分 × 点击时机倍率)。 */
  function actualScore(base, t, cfg) {
    const b = clamp(finite(base, 0), 0, 100);
    return Math.max(0, Math.min(100, Math.round(b * timingMultiplier(t, cfg))));
  }

  /** 本局游戏积分 → 商城积分。只影响入账，不改变报告里的脑电基础分/实际分。 */
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
      this.config = normalizeConfig(config);
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
      this.multiplier = null;
      this.reactionSec = null;
      this.earlyTaps = 0;
      this.cooldownRemaining = 0;     // 本轮剩余无效点击冷却
      this.cooldownCount = 0;         // 本轮实际触发冷却次数
      this.cooldownSec = 0;           // 本轮累计冷却时长
      this.paused = false;             // 信号异常/主动暂停时，点击不得产生惩罚
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
      this.paused = !signalOk || paused;

      // 设备断流 / 主动暂停：冻结蓄力、衰减与本轮计时，只记录异常时长。
      if (!signalOk) {
        this.staleSec += step;
        return out;
      }
      if (paused) return out;

      const score = finite(input && input.score, c.chargeZeroScore);

      if (this.phase === "CHARGING") {
        // 计时包含正常蓄力、等待、宽容期、衰减与无效点击冷却；
        // 异常帧与暂停在上面已提前返回，不计入本轮 T。
        this.chargeSec += step;
        this._scoreSum += score;
        this._scoreN += 1;
        // 达标 = 本帧实际处于有效蓄力状态（滞回 + 高于零点），与游戏判定口径一致。
        if (input && input.charging) this._aboveN += 1;

        // 冷却只暂停增长；冷却期间的时间仍计入 T，但不执行衰减。
        let cooled = 0;
        if (this.cooldownRemaining > 0) {
          cooled = Math.min(this.cooldownRemaining, step);
          this.cooldownRemaining = Math.max(0, this.cooldownRemaining - cooled);
          this.cooldownSec += cooled;
        }
        const activeStep = Math.max(0, step - cooled);

        if (input && input.charging) {
          this.belowSec = 0;
          this.decaying = false;
          const gain = chargeSpeed(score, c) * activeStep;
          if (gain > 0) this.energy += gain;   // 负增益已被 chargeSpeed 钳成 0
        } else {
          const prevBelow = this.belowSec;
          this.belowSec += step;
          if (activeStep > 0 && this.belowSec >= c.graceSec) {
            // 只对“超过宽容期且不在冷却中”的那一段执行衰减，
            // 避免大帧间隔把宽容期前的时间也算成衰减。
            const graceAt = Math.max(0, c.graceSec - prevBelow);
            const decayStep = Math.max(0, step - Math.max(cooled, graceAt));
            if (decayStep > 0) {
              if (!this.decaying) {
                this.decaying = true;
                this.decayEvents += 1;
              }
              this.energy -= decaySpeed(c) * decayStep;
              this.decaySec += decayStep;
            }
          }
        }

        this.energy = clamp(this.energy, 0, 100);

        // 首次进入金色区域：立即锁定本帧位置与脑电基础得分，进入子弹时间。
        // 冷却期间不进入；冷却结束后若已达标，下一帧再进入。
        if (this.cooldownRemaining <= 1e-9 && this.energy >= this.zone.lo) {
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
          this.multiplier = 0;
          this.reactionSec = null;
          out.push({ type: "miss" });
        }
      }
      return out;
    }

    _startInvalidCooldown() {
      const c = this.config;
      if (this.cooldownRemaining > 1e-9) return false;   // 不叠加、不延长
      const duration = Math.max(0, finite(c.invalidTapCooldownSec, 0));
      if (duration <= 0) return false;
      this.cooldownRemaining = duration;
      this.cooldownCount += 1;
      return true;
    }

    /**
     * 点击。只有子弹时间内第一次点击有效；提前点击只触发冷却，
     * 不扣分、不清空蓄力、不产生跳跃动作。
     * @returns {{type: "success"|"early"|"ignored", score?: number, base?: number,
     *            multiplier?: number, reactionSec?: number, cooldownStarted?: boolean,
     *            cooldownRemaining?: number}}
     */
    tap() {
      const c = this.config;
      if (this.paused) return { type: "ignored" };
      if (this.phase === "BULLET_TIME" && !this.settled) {
        // 帧间事件可能刚好落在窗口末尾：不把超时点击算成功。
        if (this.bulletElapsed >= c.bulletTimeSec - 1e-9) return { type: "ignored" };
        const multiplier = timingMultiplier(this.bulletElapsed, c);
        const base = clamp(finite(this.potential, 0), 0, 100);
        this.settled = true;
        this.multiplier = multiplier;
        this.awarded = Math.max(0, Math.min(100, Math.round(base * multiplier)));
        this.reactionSec = this.bulletElapsed;
        this.phase = "JUMP_SUCCESS";
        return {
          type: "success",
          score: this.awarded,
          base,
          multiplier,
          reactionSec: this.reactionSec,
        };
      }
      if (this.phase === "CHARGING") {
        this.earlyTaps += 1;
        const cooldownStarted = this._startInvalidCooldown();
        return {
          type: "early",
          cooldownStarted,
          cooldownRemaining: this.cooldownRemaining,
        };
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
          // 点击时机倍率：1 = 满分宽容期；0 = 超时/错过。
          multiplier: this.multiplier == null ? null : round3(this.multiplier),
          mean_score: this._scoreN ? round3(this._scoreSum / this._scoreN) : null,
          above_ratio: this._scoreN ? round3(this._aboveN / this._scoreN) : null,
          decay_events: this.decayEvents,
          decay_sec: round3(this.decaySec),
          stale_sec: round3(this.staleSec),
          early_taps: this.earlyTaps,
          cooldown_count: this.cooldownCount,
          cooldown_sec: round3(this.cooldownSec),
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
        multiplier: this.multiplier,
        reactionSec: this.reactionSec,
        earlyTaps: this.earlyTaps,
        cooldownRemaining: round3(this.cooldownRemaining),
        cooldownCount: this.cooldownCount,
        cooldownSec: round3(this.cooldownSec),
        paused: this.paused,
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
    timingMultiplier,
    actualScore,
    pointsForScore,
    validateConfig,
    normalizeConfig,
  };
});
