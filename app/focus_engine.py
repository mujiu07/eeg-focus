"""
专注引擎
========
将 EEG 信号窗口转换为"专注指数"。

流程: 窗口信号 -> 带通滤波 -> 频段特征 -> 模型 predict_proba -> 专注概率
平滑: 指数移动平均 (EMA)，降低逐窗口抖动，提供稳定的游戏反馈。

加载模型: outputs/models/LogisticRegression.joblib（平衡准确率最优的基线模型）
模型训练自 PhysioNet EEGMAT 数据集（心算专注 vs 背景放松）。
"""

import os

import joblib
import numpy as np

from . import features

ROOT = os.path.join(os.path.dirname(__file__), "..")
MODEL_PATH = os.path.join(ROOT, "outputs", "models", "LogisticRegression.joblib")

# 指数平滑系数: 越大越平滑（0.5 = 对历史衰减一半的权重）
EMA_ALPHA = 0.35

# Xmuse 等 4/6 通道设备无法喂给 21 通道 EEGMAT 模型。
# 此时改用神经工效学常用的 beta/(theta+alpha) 工程指标，经 sigmoid 映射到 0..1。
# 它只保证"相对变化"可校准，不声称是临床注意力分数。
BAND_FOCUS_CENTER = 0.70
BAND_FOCUS_SLOPE = 2.5


class FocusEngine:
    """实时专注指数计算器。"""

    def __init__(self, model_path=MODEL_PATH):
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"模型不存在: {model_path}，请先运行 scripts/train.py 训练模型")
        self.model = joblib.load(model_path)
        self._ema = None
        # 训练模型的特征维度（21 通道 × 11 特征 = 231）
        self._expected_dim = getattr(self.model, "n_features_in_", None)
        if self._expected_dim is None:
            self._expected_dim = 21 * len(features.FEAT_NAMES)
        self._model_ok = True
        self._active_mode = "model"
        self._last_model_error = None

    def reset(self):
        self._ema = None
        self._active_mode = "model"

    @property
    def smooth_focus(self):
        return self._ema if self._ema is not None else 0.5

    def _band_focus(self, seg, fs):
        """4/6 通道设备的频段工程指标：beta / (theta + alpha)。"""
        seg_f = features.prepare_signal(seg, fs)
        powers, total = features.band_power(seg_f, fs)
        rel = {b: float(np.mean(powers[b] / total)) for b in features.BAND_NAMES}
        ratio = rel["beta"] / (rel["theta"] + rel["alpha"] + 1e-9)
        focus = 1.0 / (1.0 + np.exp(-BAND_FOCUS_SLOPE * (ratio - BAND_FOCUS_CENTER)))
        return float(np.clip(focus, 0.02, 0.98))

    def compute_raw(self, seg, fs):
        """计算原始专注值（不平滑）。seg: (n_ch, n_samples)。

        通道数/特征维度与模型一致时走模型推理；否则自动回退到频段指标，
        保证 Xmuse（4/6 通道）也能驱动游戏。
        """
        n_ch = int(seg.shape[0])
        n_feat = n_ch * len(features.FEAT_NAMES)
        if not self._model_ok or n_feat != self._expected_dim:
            self._active_mode = "band"
            return self._band_focus(seg, fs)

        seg_f = features.prepare_signal(seg, fs)
        feats = features.window_to_features(seg_f, fs)
        feats = feats.reshape(1, -1)
        try:
            # 部分模型管道自带 StandardScaler，这里统一走 predict_proba
            if hasattr(self.model, "predict_proba"):
                p = self.model.predict_proba(feats)[0, 1]
            else:
                p = float(self.model.predict(feats)[0])
        except ValueError as exc:  # 模型与输入不匹配时不要把会话打死
            self._model_ok = False
            self._last_model_error = str(exc)
            self._active_mode = "band"
            return self._band_focus(seg, fs)

        self._active_mode = "model"
        return float(p)

    def update(self, seg, fs):
        """计算并平滑。返回 (raw_focus, smooth_focus)。"""
        raw = self.compute_raw(seg, fs)
        if self._ema is None:
            self._ema = raw
        else:
            self._ema = EMA_ALPHA * raw + (1 - EMA_ALPHA) * self._ema
        return raw, self._ema

    def describe(self):
        """模型信息（供开发者页展示）。"""
        return {
            "model": os.path.basename(MODEL_PATH),
            "feature_dim": self._expected_dim,
            "window_sec": features.WINDOW_SEC,
            "bands": features.BAND_NAMES,
            "active_mode": self._active_mode,
            "band_focus": {
                "metric": "beta / (theta + alpha)",
                "center": BAND_FOCUS_CENTER,
                "slope": BAND_FOCUS_SLOPE,
                "note": "4/6 通道设备（如 Xmuse）自动启用；仅作游戏机制的相对变化映射，不是临床注意力分数。",
            },
            "last_model_error": self._last_model_error,
        }
