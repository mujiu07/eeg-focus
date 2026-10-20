# EEG 专注状态分类 - 训练报告

- 数据集: PhysioNet EEGMAT v1.0.0（心算任务 EEG）
- 采样率: 500 Hz, 通道: 21, 被试: 36
- 特征: 每通道 5 频段绝对/相对功率 + theta/beta 比值 (共 231 维)
- 样本数: 4338 (窗口 2s; 专注=1116, 放松=3222)
- 通道: EEG Fp1, EEG Fp2, EEG F3, EEG F4, EEG F7, EEG F8, EEG T3, EEG T4, EEG C3, EEG C4, EEG T5, EEG T6, EEG P3, EEG P4, EEG O1, EEG O2, EEG Fz, EEG Cz, EEG Pz, EEG A2-A1, ECG ECG
- 评估: Leave-One-Subject-Out 交叉验证（按被试划分）

## LogisticRegression

- 准确率: 0.7291
- 平衡准确率: 0.6399
- F1 (专注): 0.4642
- ROC-AUC: 0.7312

混淆矩阵 (行=真实, 列=预测):

| | 预测:放松 | 预测:专注 |
|---|---|---|
| 真实:放松 | 2654 | 568 |
| 真实:专注 | 607 | 509 |

各被试(折)准确率:  Subject00: 0.861 (n=122);  Subject01: 0.803 (n=122);  Subject02: 0.320 (n=122);  Subject03: 0.820 (n=122);  Subject04: 0.759 (n=116);  Subject05: 0.656 (n=122);  Subject06: 0.770 (n=122);  Subject07: 0.721 (n=122);  Subject08: 0.754 (n=122);  Subject09: 0.762 (n=122);  Subject10: 0.816 (n=125);  Subject11: 0.434 (n=122);  Subject12: 0.664 (n=122);  Subject13: 0.697 (n=122);  Subject14: 0.656 (n=122);  Subject15: 0.803 (n=122);  Subject16: 0.672 (n=122);  Subject17: 0.697 (n=122);  Subject18: 0.770 (n=122);  Subject19: 0.885 (n=122);  Subject20: 0.746 (n=122);  Subject21: 0.754 (n=122);  Subject22: 0.877 (n=122);  Subject23: 0.754 (n=122);  Subject24: 0.697 (n=122);  Subject25: 0.689 (n=122);  Subject26: 0.795 (n=122);  Subject27: 0.795 (n=122);  Subject28: 0.926 (n=122);  Subject29: 0.762 (n=122);  Subject30: 0.787 (n=122);  Subject31: 0.606 (n=71);  Subject32: 0.779 (n=122);  Subject33: 0.705 (n=122);  Subject34: 0.697 (n=122);  Subject35: 0.508 (n=122)

## RandomForest

- 准确率: 0.7467
- 平衡准确率: 0.5597
- F1 (专注): 0.2619
- ROC-AUC: 0.7446

混淆矩阵 (行=真实, 列=预测):

| | 预测:放松 | 预测:专注 |
|---|---|---|
| 真实:放松 | 3044 | 178 |
| 真实:专注 | 921 | 195 |

各被试(折)准确率:  Subject00: 0.787 (n=122);  Subject01: 0.811 (n=122);  Subject02: 0.393 (n=122);  Subject03: 0.754 (n=122);  Subject04: 0.741 (n=116);  Subject05: 0.779 (n=122);  Subject06: 0.754 (n=122);  Subject07: 0.746 (n=122);  Subject08: 0.770 (n=122);  Subject09: 0.746 (n=122);  Subject10: 0.768 (n=125);  Subject11: 0.738 (n=122);  Subject12: 0.648 (n=122);  Subject13: 0.541 (n=122);  Subject14: 0.779 (n=122);  Subject15: 0.754 (n=122);  Subject16: 0.770 (n=122);  Subject17: 0.844 (n=122);  Subject18: 0.754 (n=122);  Subject19: 0.779 (n=122);  Subject20: 0.787 (n=122);  Subject21: 0.762 (n=122);  Subject22: 0.844 (n=122);  Subject23: 0.762 (n=122);  Subject24: 0.746 (n=122);  Subject25: 0.787 (n=122);  Subject26: 0.770 (n=122);  Subject27: 0.820 (n=122);  Subject28: 0.803 (n=122);  Subject29: 0.754 (n=122);  Subject30: 0.762 (n=122);  Subject31: 0.592 (n=71);  Subject32: 0.762 (n=122);  Subject33: 0.746 (n=122);  Subject34: 0.762 (n=122);  Subject35: 0.697 (n=122)

## MLP

- 准确率: 0.6996
- 平衡准确率: 0.6247
- F1 (专注): 0.4462
- ROC-AUC: 0.6950

混淆矩阵 (行=真实, 列=预测):

| | 预测:放松 | 预测:专注 |
|---|---|---|
| 真实:放松 | 2510 | 712 |
| 真实:专注 | 591 | 525 |

各被试(折)准确率:  Subject00: 0.910 (n=122);  Subject01: 0.885 (n=122);  Subject02: 0.451 (n=122);  Subject03: 0.762 (n=122);  Subject04: 0.741 (n=116);  Subject05: 0.566 (n=122);  Subject06: 0.738 (n=122);  Subject07: 0.762 (n=122);  Subject08: 0.525 (n=122);  Subject09: 0.738 (n=122);  Subject10: 0.752 (n=125);  Subject11: 0.500 (n=122);  Subject12: 0.451 (n=122);  Subject13: 0.475 (n=122);  Subject14: 0.434 (n=122);  Subject15: 0.762 (n=122);  Subject16: 0.697 (n=122);  Subject17: 0.623 (n=122);  Subject18: 0.738 (n=122);  Subject19: 0.934 (n=122);  Subject20: 0.779 (n=122);  Subject21: 0.705 (n=122);  Subject22: 0.885 (n=122);  Subject23: 0.680 (n=122);  Subject24: 0.779 (n=122);  Subject25: 0.754 (n=122);  Subject26: 0.787 (n=122);  Subject27: 0.754 (n=122);  Subject28: 0.984 (n=122);  Subject29: 0.779 (n=122);  Subject30: 0.770 (n=122);  Subject31: 0.577 (n=71);  Subject32: 0.713 (n=122);  Subject33: 0.516 (n=122);  Subject34: 0.697 (n=122);  Subject35: 0.533 (n=122)

## 汇总

| 模型 | 准确率 | 平衡准确率 | F1 | AUC |
|---|---|---|---|---|
| LogisticRegression | 0.7291 | 0.6399 | 0.4642 | 0.7312 |
| RandomForest | 0.7467 | 0.5597 | 0.2619 | 0.7446 |
| MLP | 0.6996 | 0.6247 | 0.4462 | 0.6950 |

*注: 平衡准确率对放松/专注两类不平衡不敏感, 更贴近实际使用场景。*