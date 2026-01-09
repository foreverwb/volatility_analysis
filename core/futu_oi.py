"""
Futu OpenAPI OI 缓存与 ΔOI 计算
"""
import json
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

OI_CACHE_FILE = "oi_cache.json"
CACHE_LOCK = threading.Lock()


def load_oi_cache() -> dict:
    """加载 OI 缓存（线程安全）"""
    with CACHE_LOCK:
        if not os.path.exists(OI_CACHE_FILE):
            return {}
        try:
            with open(OI_CACHE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return {}


def save_oi_cache(cache: dict) -> None:
    """保存 OI 缓存（线程安全）"""
    with CACHE_LOCK:
        with open(OI_CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)


def batch_compute_delta_oi(
    symbol_to_oi: Dict[str, Optional[int]]
) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
    """
    批量计算 ΔOI_1D（基于 Futu OI）
    """
    cache = load_oi_cache()
    today = datetime.now().strftime('%Y-%m-%d')
    cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    results: Dict[str, Tuple[Optional[int], Optional[int]]] = {}

    for symbol, current_oi in symbol_to_oi.items():
        if current_oi is None:
            results[symbol] = (None, None)
            continue

        symbol_cache = cache.get(symbol, {})
        yesterday_oi = None

        for days_ago in range(1, 8):
            past_date = (datetime.now() - timedelta(days=days_ago)).strftime('%Y-%m-%d')
            if past_date in symbol_cache:
                yesterday_oi = symbol_cache[past_date]
                break

        delta_oi = current_oi - yesterday_oi if yesterday_oi is not None else None

        if symbol not in cache:
            cache[symbol] = {}
        cache[symbol][today] = current_oi
        cache[symbol] = {
            date: oi for date, oi in cache[symbol].items()
            if date >= cutoff
        }

        results[symbol] = (current_oi, delta_oi)

    save_oi_cache(cache)
    return results
