"""
score_model.py
---------------
本模块为 MCP 工具包示例：计算模型预测结果的评分指标。

功能：
- 计算 Accuracy（准确率）
- 计算 Balanced Accuracy（平衡准确率）
- 计算 Balanced Error Rate (BER)
- 支持 numpy 数组或 Python 列表输入

作者：Zhiting Hu
"""

import numpy as np
from sklearn.metrics import balanced_accuracy_score, accuracy_score


def score_model(y_true, y_pred):
    """
    计算模型预测的多种评估指标。

    参数：
    ----------
    y_true : list[int] or np.ndarray
        真实标签
    y_pred : list[int] or np.ndarray
        预测标签

    返回：
    ----------
    dict 包含以下键：
        - "accuracy" : 准确率
        - "balanced_accuracy" : 平衡准确率
        - "BER" : 平衡错误率 (1 - 平衡准确率)
    """
    y_true = np.array(y_true)
    y_pred = np.array(y_pred)

    if len(y_true) != len(y_pred):
        raise ValueError("y_true 与 y_pred 长度不一致！")

    acc = accuracy_score(y_true, y_pred)
    bal_acc = balanced_accuracy_score(y_true, y_pred)
    ber = 1 - bal_acc

    return {
        "accuracy": round(acc, 4),
        "balanced_accuracy": round(bal_acc, 4),
        "BER": round(ber, 4)
    }


# ✅ 测试函数（可独立运行）
if __name__ == "__main__":
    # 模拟预测结果
    y_true = [0, 1, 1, 0, 1, 0, 1, 1]
    y_pred = [0, 0, 1, 0, 1, 1, 1, 0]

    scores = score_model(y_true, y_pred)
    print("✅ 模型评估结果：")
    for k, v in scores.items():
        print(f"  {k}: {v}")
