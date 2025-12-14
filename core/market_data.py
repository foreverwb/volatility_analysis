"""
市场数据获取模块 - v2.3.3
Market Data API for VIX

数据源：
- Yahoo Finance (yfinance)
- 本地缓存机制（避免频繁请求）
"""
import os
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import time


# VIX 缓存文件
VIX_CACHE_FILE = "vix_cache.json"
VIX_CACHE_TTL = 3600  # 缓存有效期 1 小时（秒）


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
            return cached_vix
    
    # 2. 从 Yahoo Finance 获取
    try:
        import yfinance as yf
        
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="1d")
        
        if not hist.empty:
            vix_value = float(hist['Close'].iloc[-1])
            
            # 保存到缓存
            _save_vix_to_cache(vix_value)
            
            print(f"✓ VIX fetched: {vix_value:.2f}")
            return vix_value
        else:
            print("Warning: VIX data is empty")
            return None
    
    except ImportError:
        print("Error: yfinance not installed. Run: pip install yfinance")
        return None
    
    except Exception as e:
        print(f"Error: Failed to fetch VIX: {e}")
        return None


def get_vix_history(days: int = 20) -> List[float]:
    """
    获取 VIX 历史数据
    
    Args:
        days: 历史天数
        
    Returns:
        VIX 值列表（按时间升序）
    """
    try:
        import yfinance as yf
        
        vix = yf.Ticker("^VIX")
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days + 10)  # 多取几天以防周末
        
        hist = vix.history(start=start_date, end=end_date)
        
        if not hist.empty:
            vix_values = hist['Close'].tolist()
            # 只返回最近的 days 个数据点
            return vix_values[-days:] if len(vix_values) > days else vix_values
        else:
            print("Warning: VIX history is empty")
            return []
    
    except ImportError:
        print("Error: yfinance not installed")
        return []
    
    except Exception as e:
        print(f"Error: Failed to fetch VIX history: {e}")
        return []


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
        print(f"⚠ Using fallback VIX: {default}")
        return default
    
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


# ========== 备用数据源（如果 yfinance 不可用） ==========

def get_vix_from_cboe() -> Optional[float]:
    """
    从 CBOE 官网获取 VIX（备用方案）
    
    注意：需要解析 HTML，不推荐作为主要数据源
    
    Returns:
        VIX 值，失败返回 None
    """
    try:
        import requests
        from bs4 import BeautifulSoup
        
        url = "https://www.cboe.com/tradable_products/vix/"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # 这里需要根据 CBOE 页面结构提取 VIX
            # 实际实现需要检查页面结构
            # ...
            pass
    
    except Exception as e:
        print(f"Error: Failed to fetch VIX from CBOE: {e}")
    
    return None


def clear_vix_cache():
    """清除 VIX 缓存（用于测试或强制刷新）"""
    if os.path.exists(VIX_CACHE_FILE):
        try:
            os.remove(VIX_CACHE_FILE)
            print("✓ VIX cache cleared")
        except Exception as e:
            print(f"Error: Failed to clear VIX cache: {e}")