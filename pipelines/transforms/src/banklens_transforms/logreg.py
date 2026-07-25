"""Minimal logistic regression (batch gradient descent, L2, class-weighted).

Dependency-free and fully inspectable. Chosen over XGBoost on purpose: the labeled
set (a handful of real bank failures) is tiny, so a linear model with strong
regularization is the statistically honest choice and its coefficients are directly
interpretable (the plan's "coefficient inspection" alternative to SHAP). XGBoost +
SHAP is the documented upgrade once there is more labeled history.
"""

from __future__ import annotations

import math


def sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


class LogisticRegression:
    def __init__(self, lr: float = 0.1, epochs: int = 3000, l2: float = 1.0,
                 class_weight: bool = True):
        self.lr = lr
        self.epochs = epochs
        self.l2 = l2
        self.class_weight = class_weight
        self.w: list[float] = []
        self.b: float = 0.0

    def fit(self, X: list[list[float]], y: list[int]) -> "LogisticRegression":
        n, d = len(X), len(X[0])
        self.w = [0.0] * d
        self.b = 0.0
        npos = sum(y)
        wpos = (n - npos) / npos if (self.class_weight and 0 < npos < n) else 1.0

        for _ in range(self.epochs):
            gw = [0.0] * d
            gb = 0.0
            wsum = 0.0
            for i in range(n):
                z = self.b + sum(self.w[j] * X[i][j] for j in range(d))
                p = sigmoid(z)
                sw = wpos if y[i] == 1 else 1.0
                err = sw * (p - y[i])
                for j in range(d):
                    gw[j] += err * X[i][j]
                gb += err
                wsum += sw
            for j in range(d):
                self.w[j] -= self.lr * (gw[j] / wsum + self.l2 * self.w[j] / n)
            self.b -= self.lr * (gb / wsum)
        return self

    def predict_proba(self, X: list[list[float]]) -> list[float]:
        return [sigmoid(self.b + sum(self.w[j] * x[j] for j in range(len(x)))) for x in X]


def auc(y: list[int], scores: list[float]) -> float:
    """Rank-based ROC-AUC: P(random positive scores above random negative)."""
    pos = [s for s, t in zip(scores, y) if t == 1]
    neg = [s for s, t in zip(scores, y) if t == 0]
    if not pos or not neg:
        return float("nan")
    wins = sum((1.0 if p > n else 0.5 if p == n else 0.0) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 4)
