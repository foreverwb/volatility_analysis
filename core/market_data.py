"""
市场数据获取模块 - v2.3.3
Market Data API for VIX

数据源：
- Alpha Vantage (替代 yfinance)
- 本地缓存机制（避免频繁请求）
"""
import os
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import time
import requests
import math


# VIX 缓存文件
VIX_CACHE_FILE = "vix_cache.json"
VIX_CACHE_TTL = 21600  # 缓存有效期 6 小时（秒）
ALPHA_VANTAGE_API_URL = "https://www.alphavantage.co/query"
ALPHA_VANTAGE_ENV = "ALPHA_VANTAGE_API_KEY"
ALPHA_VANTAGE_KEY='STB6RITIM7Q71O1L'
YAHOO_VIX_URL = "https://query1.finance.yahoo.com/v8/finance/chart/^VIX"
YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def _get_alpha_vantage_key() -> Optional[str]:
    env_key = os.environ.get(ALPHA_VANTAGE_ENV)
    if env_key:
        return env_key
    if ALPHA_VANTAGE_KEY:
        print(f"⚠️ 使用内置 Alpha Vantage Key（建议改为环境变量 {ALPHA_VANTAGE_ENV}）")
        return ALPHA_VANTAGE_KEY
    return None


def _fetch_vix_alpha_vantage_latest(api_key: str) -> Optional[float]:
    params = {
        "function": "GLOBAL_QUOTE",
        "symbol": "VIX",
        "apikey": api_key,
    }
    try:
        resp = requests.get(ALPHA_VANTAGE_API_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("Note"):
            print("⚠️ Alpha Vantage rate limit Note: ", data.get("Note"))
        quote = data.get("Global Quote") or {}
        price_str = quote.get("05. price")
        if price_str is None:
            print(f"⚠️ Alpha Vantage 无 VIX 价格字段: {data}")
            return None
        return float(price_str)
    except Exception as e:
        print(f"Error: Alpha Vantage VIX 请求失败: {e}")
        return None


def _fetch_vix_alpha_vantage_history(days: int, api_key: str) -> List[float]:
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": "VIX",
        "outputsize": "compact",
        "apikey": api_key,
    }
    try:
        resp = requests.get(ALPHA_VANTAGE_API_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("Note"):
            print("⚠️ Alpha Vantage rate limit Note: ", data.get("Note"))
        ts = data.get("Time Series (Daily)") or {}
        if not ts:
            print(f"⚠️ Alpha Vantage 无历史数据: {data}")
            return []
        # 按日期排序
        dates = sorted(ts.keys())
        closes = [float(ts[d]["4. close"]) for d in dates if "4. close" in ts[d]]
        return closes[-days:] if len(closes) > days else closes
    except Exception as e:
        print(f"Error: Alpha Vantage VIX 历史请求失败: {e}")
        return []


def _fetch_vix_yahoo_latest() -> Optional[float]:
    params = {"interval": "1d", "range": "1mo"}
    try:
        resp = requests.get(YAHOO_VIX_URL, params=params, headers=YAHOO_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("chart", {}).get("result") or []
        if not result:
            print("⚠️ Yahoo 返回空 result")
            return None
        node = result[0]
        closes = node.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        # 取最后一个非空收盘
        closes = [c for c in closes if c is not None and not (isinstance(c, float) and math.isnan(c))]
        if not closes:
            print("⚠️ Yahoo 收盘数据为空")
            return None
        return float(closes[-1])
    except Exception as e:
        print(f"Error: Yahoo VIX 请求失败: {e}")
        return None


def _fetch_vix_yahoo_history(days: int) -> List[float]:
    # 使用 3 个月窗口足够覆盖 days 需求
    params = {"interval": "1d", "range": "3mo"}
    try:
        resp = requests.get(YAHOO_VIX_URL, params=params, headers=YAHOO_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("chart", {}).get("result") or []
        if not result:
            print("⚠️ Yahoo 返回空 result")
            return []
        node = result[0]
        closes = node.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c in closes if c is not None and not (isinstance(c, float) and math.isnan(c))]
        return closes[-days:] if len(closes) > days else closes
    except Exception as e:
        print(f"Error: Yahoo VIX 历史请求失败: {e}")
        return []


def get_current_vix(use_cache: bool = True) -> Optional[float]:
    """
    获取当前 VIX 值
    
    Args:
        use_cache: 是否使用缓存
        
    Returns:
        VIX 值，失败返回 None
    """
    # 1. 检查缓存
    if use_cache:
        cached_vix = _load_vix_from_cache()
        if cached_vix is not None:
            print(f"[VIX] 使用缓存值: {cached_vix:.2f}")
            return cached_vix
    
    # 2. 从 Alpha Vantage 获取
    # 2. 先尝试 Yahoo
    vix_value = _fetch_vix_yahoo_latest()
    if vix_value is not None:
        _save_vix_to_cache(vix_value)
        print(f"[VIX] Yahoo 获取成功: {vix_value:.2f}")
        return vix_value
    
    # 3. 回退 Alpha Vantage
    api_key = _get_alpha_vantage_key()
    if not api_key:
        print(f"Error: 缺少 {ALPHA_VANTAGE_ENV} 环境变量，无法获取 VIX")
        return None
    
    vix_value = _fetch_vix_alpha_vantage_latest(api_key)
    if vix_value is not None:
        _save_vix_to_cache(vix_value)
        print(f"[VIX] Alpha Vantage 获取成功: {vix_value:.2f}")
        return vix_value
    
    return None


def get_vix_history(days: int = 20) -> List[float]:
    """
    获取 VIX 历史数据
    
    Args:
        days: 历史天数
        
    Returns:
        VIX 值列表（按时间升序）
    """
    # 优先 Yahoo
    closes = _fetch_vix_yahoo_history(days)
    if closes:
        return closes[-days:] if len(closes) > days else closes
    
    # 回退 Alpha Vantage
    api_key = _get_alpha_vantage_key()
    if not api_key:
        print(f"Error: 缺少 {ALPHA_VANTAGE_ENV} 环境变量，无法获取 VIX 历史")
        return []
    
    return _fetch_vix_alpha_vantage_history(days, api_key)


def _load_vix_from_cache() -> Optional[float]:
    """
    从缓存加载 VIX
    
    Returns:
        VIX 值，如果缓存失效返回 None
    """
    if not os.path.exists(VIX_CACHE_FILE):
        return None
    
    try:
        with open(VIX_CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
        
        timestamp = cache_data.get("timestamp", 0)
        vix_value = cache_data.get("vix")
        
        # 检查缓存是否过期
        if time.time() - timestamp < VIX_CACHE_TTL:
            print(f"✓ VIX from cache: {vix_value:.2f} (age: {int(time.time() - timestamp)}s)")
            return vix_value
        else:
            print("⚠ VIX cache expired")
            return None
    
    except Exception as e:
        print(f"Warning: Failed to load VIX cache: {e}")
        return None


def _save_vix_to_cache(vix_value: float):
    """
    保存 VIX 到缓存
    
    Args:
        vix_value: VIX 值
    """
    try:
        cache_data = {
            "vix": vix_value,
            "timestamp": time.time(),
            "datetime": datetime.now().isoformat()
        }
        
        with open(VIX_CACHE_FILE, 'w') as f:
            json.dump(cache_data, f, indent=2)
    
    except Exception as e:
        print(f"Warning: Failed to save VIX cache: {e}")


def get_vix_with_fallback(default: float = 18.0) -> float:
    """
    获取 VIX，失败时使用回退值
    
    Args:
        default: 回退默认值（VIX 长期均值约 18）
        
    Returns:
        VIX 值
    """
    vix = get_current_vix(use_cache=True)
    
    if vix is None:
        print(f"[VIX] 获取失败，使用回退值: {default}")
        return default
    
    print(f"[VIX] 当前值: {vix:.2f}")
    return vix


def validate_vix(vix_value: float) -> bool:
    """
    验证 VIX 值的合理性
    
    Args:
        vix_value: VIX 值
        
    Returns:
        True if valid
    """
    # VIX 正常范围: 10 - 80
    # 极端情况: 2008 金融危机最高约 80，平静期最低约 10
    if not isinstance(vix_value, (int, float)):
        return False
    
    if vix_value < 5 or vix_value > 100:
        return False
    
    return True


def get_vix_info() -> Dict:
    """
    获取 VIX 相关信息（用于诊断）
    
    Returns:
        信息字典
    """
    current_vix = get_current_vix(use_cache=False)  # 强制刷新
    
    cache_exists = os.path.exists(VIX_CACHE_FILE)
    cache_age = None
    cached_vix = None
    
    if cache_exists:
        try:
            with open(VIX_CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
            
            cached_vix = cache_data.get("vix")
            cache_age = int(time.time() - cache_data.get("timestamp", 0))
        except:
            pass
    
    return {
        "current_vix": current_vix,
        "cached_vix": cached_vix,
        "cache_age_seconds": cache_age,
        "cache_valid": cache_age < VIX_CACHE_TTL if cache_age else False,
        "cache_file": VIX_CACHE_FILE,
        "cache_exists": cache_exists
    }

def clear_vix_cache():
    """清除 VIX 缓存（用于测试或强制刷新）"""
    if os.path.exists(VIX_CACHE_FILE):
        try:
            os.remove(VIX_CACHE_FILE)
            print("✓ VIX cache cleared")
        except Exception as e:
            print(f"Error: Failed to clear VIX cache: {e}")


if __name__ == '__main__':
    print("vix")
    get_current_vix(False)
