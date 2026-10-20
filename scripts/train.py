"""
训练基线模型: EEG 专注 vs 放松 二分类
=====================================
使用 EEGMAT 数据集预处理后的特征 (data/processed/features.npz)

评估方案: Leave-One-Subject-Out (LOSO) 交叉验证
  - 每轮: 1 名被试作为测试, 其余作为训练
  - 严格按被试划分, 避免同一被试的窗口同时出现在训练/测试集
  - 最终准确率报告的是"对新用户的泛化能力", 而非记忆性得分

模型:
  1. Logistic Regression (基线)
  2. Random Forest
  3. 简单 MLP (可选)

输出: outputs/train_report.md, outputs/models/
"""

import os
import json
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, f1_score,
    roc_auc_score, confusion_matrix, classification_report,
)
from sklearn.pipeline import make_pipeline

ROOT = os.path.join(os.path.dirname(__file__), "..")
PROCESSED = os.path.join(ROOT, "data", "processed", "features.npz")
OUT_REPORT = os.path.join(ROOT, "outputs", "train_report.md")
MODEL_DIR = os.path.join(ROOT, "outputs", "models")

MODELS = {
    "LogisticRegression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)),
    "RandomForest": RandomForestClassifier(
        n_estimators=300, max_depth=12, min_samples_leaf=3,
        n_jobs=-1, random_state=42),
    "MLP": make_pipeline(StandardScaler(), MLPClassifier(
        hidden_layer_sizes=(128, 64), max_iter=500, random_state=42)),
}


def main():
    data = np.load(PROCESSED)
    X, y, subjects = data["X"], data["y"], data["subjects"]
    ch_names = data["ch_names"].tolist()
    feat_names = data["feat_names"].tolist()
    fs = int(data["fs"])
    print(f"载入: X={X.shape}, y 分布={np.bincount(y.astype(int))}, 被试={len(np.unique(subjects))}")

    logo = LeaveOneGroupOut()
    report_lines = []
    report_lines.append("# EEG 专注状态分类 - 训练报告")
    report_lines.append("")
    report_lines.append(f"- 数据集: PhysioNet EEGMAT v1.0.0（心算任务 EEG）")
    report_lines.append(f"- 采样率: {fs} Hz, 通道: {len(ch_names)}, 被试: {len(np.unique(subjects))}")
    report_lines.append(f"- 特征: 每通道 5 频段绝对/相对功率 + theta/beta 比值 (共 {X.shape[1]} 维)")
    report_lines.append(f"- 样本数: {X.shape[0]} (窗口 2s; 专注={int(y.sum())}, 放松={int(y.size-y.sum())})")
    report_lines.append(f"- 通道: {', '.join(ch_names)}")
    report_lines.append(f"- 评估: Leave-One-Subject-Out 交叉验证（按被试划分）")
    report_lines.append("")

    results = {}
    for name, model in MODELS.items():
        print(f"\n=== {name} (LOSO CV) ===")
        preds = cross_val_predict(model, X, y, groups=subjects, cv=logo,
                                  method="predict", n_jobs=1)
        probs = cross_val_predict(model, X, y, groups=subjects, cv=logo,
                                  method="predict_proba", n_jobs=1)[:, 1]

        acc = accuracy_score(y, preds)
        bal_acc = balanced_accuracy_score(y, preds)
        f1 = f1_score(y, preds)
        auc = roc_auc_score(y, probs)
        cm = confusion_matrix(y, preds)

        results[name] = {"acc": acc, "balanced_acc": bal_acc, "f1": f1, "auc": auc}

        report_lines.append(f"## {name}")
        report_lines.append("")
        report_lines.append(f"- 准确率: {acc:.4f}")
        report_lines.append(f"- 平衡准确率: {bal_acc:.4f}")
        report_lines.append(f"- F1 (专注): {f1:.4f}")
        report_lines.append(f"- ROC-AUC: {auc:.4f}")
        report_lines.append("")
        report_lines.append("混淆矩阵 (行=真实, 列=预测):")
        report_lines.append("")
        report_lines.append("| | 预测:放松 | 预测:专注 |")
        report_lines.append("|---|---|---|")
        report_lines.append(f"| 真实:放松 | {cm[0,0]} | {cm[0,1]} |")
        report_lines.append(f"| 真实:专注 | {cm[1,0]} | {cm[1,1]} |")
        report_lines.append("")

        # 每被试逐折准确率
        per_subj = []
        for tr_idx, te_idx in logo.split(X, y, groups=subjects):
            s = int(subjects[te_idx[0]])
            acc_s = accuracy_score(y[te_idx], preds[te_idx])
            per_subj.append(f"Subject{s:02d}: {acc_s:.3f} (n={len(te_idx)})")
        report_lines.append("各被试(折)准确率:  " + ";  ".join(per_subj))
        report_lines.append("")

        # 保存模型: 用全部数据重训一份 (部署用)
        os.makedirs(MODEL_DIR, exist_ok=True)
        model_full = model
        model_full.fit(X, y)
        import joblib
        joblib.dump(model_full, os.path.join(MODEL_DIR, f"{name}.joblib"))

    # 汇总表
    report_lines.append("## 汇总")
    report_lines.append("")
    report_lines.append("| 模型 | 准确率 | 平衡准确率 | F1 | AUC |")
    report_lines.append("|---|---|---|---|---|")
    for name, r in results.items():
        report_lines.append(
            f"| {name} | {r['acc']:.4f} | {r['balanced_acc']:.4f} | {r['f1']:.4f} | {r['auc']:.4f} |")
    report_lines.append("")
    report_lines.append("*注: 平衡准确率对放松/专注两类不平衡不敏感, 更贴近实际使用场景。*")

    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"\n报告已保存: {OUT_REPORT}")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
