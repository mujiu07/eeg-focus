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


class FocusEngine:
    """实时专注指数计算器。"""

    def __init__(self, model_path=MODEL_PATH):
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"模型不存在: {model_path}，请先运行 scripts/train.py 训练模型")
        self.model = joblib.load(model_path)
        self._ema = None

    def reset(self):
        self._ema = None

    @property
    def smooth_focus(self):
        return self._ema if self._ema is not None else 0.5

    def compute_raw(self, seg, fs):
        """计算原始专注概率（不平滑）。seg: (n_ch, n_samples)。"""
        seg_f = features.prepare_signal(seg, fs)
        feats = features.window_to_features(seg_f, fs)
        feats = feats.reshape(1, -1)
        # 部分模型管道自带 StandardScaler，这里统一走 predict_proba
        if hasattr(self.model, "predict_proba"):
            p = self.model.predict_proba(feats)[0, 1]
        else:
            p = float(self.model.predict(feats)[0])
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
            "feature_dim": 21 * len(features.FEAT_NAMES),
            "window_sec": features.WINDOW_SEC,
            "bands": features.BAND_NAMES,
        }
