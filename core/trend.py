"""趋势计算工具。

提供方向/波动评分序列的线性斜率计算与趋势标签映射：
- 斜率反映最近 N 日评分的数值变化速度（而非符号一致性）。
- 趋势标签通过阈值映射为“上行/下行/横盘”。
"""

from typing import Any, Dict, List


def _to_float(value: Any):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_linear_slope(scores: List[float], n_days: int) -> float:
    """计算最近 N 日评分序列的线性回归斜率。

    x 取 0..k-1，y 为有效评分值；k=min(n_days, 可用有效点数)。
    数据不足（k<=1）时返回 0.0。
    """

    if not scores or n_days <= 1:
        return 0.0

    valid_scores = []
    for score in scores:
        v = _to_float(score)
        if v is not None:
            valid_scores.append(v)

    k = min(int(n_days), len(valid_scores))
    if k <= 1:
        return 0.0

    y_values = valid_scores[:k]
    x_values = list(range(k))

    mean_x = sum(x_values) / k
    mean_y = sum(y_values) / k

    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values))
    denominator = sum((x - mean_x) ** 2 for x in x_values)

    if denominator == 0:
        return 0.0
    return numerator / denominator


def map_slope_trend(slope: float, cfg: Dict[str, Any]) -> str:
    """根据斜率阈值映射趋势标签。

    - slope > trend_slope_up: 上行
    - slope < -trend_slope_down: 下行
    - 其余: 横盘
    """

    up = float(cfg.get("trend_slope_up", 0.10))
    down = float(cfg.get("trend_slope_down", 0.10))

    if slope > up:
        return "上行"
    if slope < -down:
        return "下行"
    return "横盘"
