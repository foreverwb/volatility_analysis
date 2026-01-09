"""
数据清洗与标准化模块
v2.3.2 - 支持 ΔOI_1D 字段
"""
import re
import math
import json
from typing import Any, Dict, List, Optional


def clean_percent_string(s: Any) -> Optional[float]:
    """清洗百分比字符串: '+2.7%' -> 2.7"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace('%', '').replace('+', '')
    try:
        return float(s)
    except:
        return None


def clean_number_string(s: Any) -> Optional[float]:
    """清洗数字字符串: '628,528' -> 628528"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace(',', '')
    try:
        return float(s)
    except:
        return None


def clean_notional_string(s: Any) -> Optional[float]:
    """清洗名义金额: '261.75 M' -> 261750000"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace(',', '')
    match = re.match(r'([0-9.]+)\s*([KMBkmb]?)', s)
    if not match:
        try:
            return float(s)
        except:
            return None
    value = float(match.group(1))
    unit = match.group(2).upper()
    multiplier = {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000}.get(unit, 1)
    return value * multiplier


def clean_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """
    清洗单条记录
    
    处理字段:
    - 百分比字段: 去除 %, + 并转换为浮点
    - 数值字段: 去除逗号并转换
    - 名义金额: 解析 K/M/B 单位
    - v2.3.2 新增: ΔOI_1D 字段
    """
    
    cleaned = dict(rec)
    
    # 百分比字段 (包含 IV30ChgPct)
    percent_fields = [
        'PriceChgPct', 'IV30ChgPct', 'IVR', 'IV_52W_P', 'OI_PctRank',
        'PutPct', 'SingleLegPct', 'MultiLegPct', 'ContingentPct'
    ]
    for field in percent_fields:
        if field in cleaned:
            cleaned[field] = clean_percent_string(cleaned[field])
    
    # 数值字段 (v2.3.2: 新增 ΔOI_1D)
    number_fields = [
        'IV7', 'IV30', 'IV60', 'IV90', 'HV20', 'HV1Y', 'Volume', 'RelVolTo90D',
        'CallVolume', 'PutVolume', 'RelNotionalTo90D', 'ΔOI_1D', 'DeltaOI_1D'
    ]
    for field in number_fields:
        if field in cleaned:
            cleaned[field] = clean_number_string(cleaned[field])
    
    # 兼容不同字段名: ΔOI_1D / DeltaOI_1D
    if 'DeltaOI_1D' in cleaned and 'ΔOI_1D' not in cleaned:
        cleaned['ΔOI_1D'] = cleaned['DeltaOI_1D']
    
    # 名义金额字段
    notional_fields = ['CallNotional', 'PutNotional']
    for field in notional_fields:
        if field in cleaned:
            cleaned[field] = clean_notional_string(cleaned[field])
    
    return cleaned


def median(values: List[float]) -> float:
    """计算中位数"""
    vals = [v for v in values if v is not None and not math.isnan(v)]
    if not vals:
        return 0.0
    vals.sort()
    n = len(vals)
    return vals[n // 2] if n % 2 == 1 else 0.5 * (vals[n // 2 - 1] + vals[n // 2])


def detect_scale(records: List[Dict[str, Any]], key: str) -> str:
    """检测数值尺度 (小数 vs 百分比)"""
    vals = [abs(float(r.get(key, 0))) for r in records
            if isinstance(r.get(key), (int, float))]
    med = median(vals)
    return "fraction" if 0 < med <= 1 else "percent"


def normalize_percent_value(value: Optional[float], expected: str) -> Optional[float]:
    """标准化百分比值"""
    if value is None:
        return None
    try:
        v = float(value)
        return v * 100.0 if expected == "fraction" else v
    except:
        return None


def normalize_dataset(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    标准化数据集
    
    - 自动检测百分比字段的尺度
    - 统一转换为百分比形式 (0-100)
    - Cap IVR/IV_52W_P/OI_PctRank 到 [0, 100]
    """
    pct_keys = [
        "PutPct", "SingleLegPct", "MultiLegPct", "ContingentPct",
        "IVR", "IV_52W_P", "OI_PctRank", "PriceChgPct", "IV30ChgPct"
    ]
    scale_map = {k: detect_scale(records, k) for k in pct_keys}
    
    normed = []
    for r in records:
        r2 = dict(r)
        for k in pct_keys:
            r2[k] = normalize_percent_value(r2.get(k), scale_map[k])
        # Cap 到 [0, 100]
        for cap_k in ["IVR", "IV_52W_P", "OI_PctRank"]:
            if isinstance(r2.get(cap_k), (int, float)):
                r2[cap_k] = max(0.0, min(100.0, float(r2[cap_k])))
        normed.append(r2)
    return normed
