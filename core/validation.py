"""
数据质量校验模块

validate_record(record, cfg) → {data_quality, data_quality_issues}

校验项:
- Volume 拆分一致性
- PutPct 与成交占比一致性
- IVR/OI_PctRank/IV_52W_P 是否在 [0, 100]
- Volume/Notional/IV/HV 是否为非负且数量级合理
- 关键字段缺失计数
"""
from typing import Any, Dict, List


def _is_number(val: Any) -> bool:
    return isinstance(val, (int, float))


def _add_issue(issues: List[str], text: str, severity: int, current: int) -> int:
    issues.append(text)
    return max(current, severity)


def validate_record(rec: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    对原始/OCR 输入做一致性校验，输出数据质量等级与问题列表。
    
    Returns:
        {
            "data_quality": "HIGH" | "MED" | "LOW",
            "data_quality_issues": [str, ...]
        }
    """
    issues: List[str] = []
    severity = 0  # 0: none, 1: warn, 2: fail
    
    # 1) 关键字段缺失
    key_fields = [
        "PriceChgPct", "IV30", "HV20", "HV1Y", "IVR", "IV_52W_P",
        "Volume", "CallVolume", "PutVolume", "PutPct",
        "CallNotional", "PutNotional", "OI_PctRank"
    ]
    missing = [k for k in key_fields if rec.get(k) is None]
    missing_warn = int(cfg.get("data_quality_missing_warn", 2))
    missing_fail = int(cfg.get("data_quality_missing_fail", 4))
    if missing:
        severity = _add_issue(
            issues,
            f"缺失字段: {', '.join(missing)}",
            2 if len(missing) >= missing_fail else 1,
            severity
        )
    
    # 2) Volume 拆分一致性
    cv = rec.get("CallVolume")
    pv = rec.get("PutVolume")
    total_vol = rec.get("Volume")
    vol_tol = float(cfg.get("data_quality_volume_tolerance", 0.15))
    if _is_number(total_vol) and _is_number(cv) and _is_number(pv):
        summed = float(cv) + float(pv)
        if total_vol and summed:
            mismatch = abs(summed - float(total_vol)) / max(float(total_vol), 1.0)
            if mismatch > vol_tol:
                severity = _add_issue(
                    issues,
                    f"成交量拆分不一致 (Call+Put vs Volume 偏差 {mismatch:.1%})",
                    1 if mismatch <= vol_tol * 2 else 2,
                    severity
                )
    
    # 3) PutPct 与占比一致性
    put_pct = rec.get("PutPct")
    if _is_number(put_pct) and _is_number(cv) and _is_number(pv):
        total = float(cv) + float(pv)
        if total > 0:
            observed = float(pv) / total
            diff = abs(observed - float(put_pct) / 100.0)
            tol = float(cfg.get("data_quality_putpct_tolerance", 0.12))
            if diff > tol:
                severity = _add_issue(
                    issues,
                    f"PutPct 与成交占比偏差 {diff:.1%}",
                    1 if diff <= tol * 1.5 else 2,
                    severity
                )
    
    # 4) 排名类字段范围
    for key in ["IVR", "IV_52W_P", "OI_PctRank"]:
        val = rec.get(key)
        if val is None:
            continue
        if not _is_number(val) or float(val) < 0 or float(val) > 100:
            severity = _add_issue(
                issues,
                f"{key} 超出范围或不可用 ({val})",
                2,
                severity
            )
    
    # 5) 数值合理性检测（非负且数量级不过大）
    ceilings = {
        "Volume": cfg.get("data_quality_volume_ceiling", 50_000_000),
        "CallVolume": cfg.get("data_quality_volume_ceiling", 50_000_000),
        "PutVolume": cfg.get("data_quality_volume_ceiling", 50_000_000),
        "CallNotional": cfg.get("data_quality_notional_ceiling", 5_000_000_000),
        "PutNotional": cfg.get("data_quality_notional_ceiling", 5_000_000_000),
        "IV30": cfg.get("data_quality_iv_ceiling", 300),
        "IV7": cfg.get("data_quality_iv_ceiling", 300),
        "IV60": cfg.get("data_quality_iv_ceiling", 300),
        "IV90": cfg.get("data_quality_iv_ceiling", 300),
        "HV20": cfg.get("data_quality_iv_ceiling", 300),
        "HV1Y": cfg.get("data_quality_iv_ceiling", 300),
    }
    for key, ceiling in ceilings.items():
        val = rec.get(key)
        if val is None:
            continue
        if not _is_number(val):
            severity = _add_issue(issues, f"{key} 非数字 ({val})", 2, severity)
            continue
        v = float(val)
        if v < 0:
            severity = _add_issue(issues, f"{key} 为负数 ({v})", 2, severity)
        elif ceiling and v > float(ceiling):
            severity = _add_issue(
                issues,
                f"{key} 数量级异常 ({v} > {ceiling})",
                1,
                severity
            )
    
    # 6) 质量等级
    quality = "HIGH"
    if severity >= 2 or len(issues) >= missing_fail or len(missing) >= missing_fail:
        quality = "LOW"
    elif issues or len(missing) >= missing_warn:
        quality = "MED"
    
    return {
        "data_quality": quality,
        "data_quality_issues": issues
    }
