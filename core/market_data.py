"""
市场数据获取模块 - v2.3.6 (Flask 线程安全版本)
修复: 使用 util.run() 在工作线程中正确执行异步代码
"""
import os
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import time
import requests
import math
import threading

# ========== IBKR 集成 ==========
try:
    from ib_insync import IB, Index, util
    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False
    IB = None  # type: ignore
    Index = None  # type: ignore
    util = None  # type: ignore

# ========== 配置常量 ==========
VIX_CACHE_FILE = "vix_cache.json"
VIX_CACHE_TTL = 21600

IBKR_HOST = os.environ.get("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.environ.get("IBKR_PORT", "4002"))
IBKR_CLIENT_ID = int(os.environ.get("IBKR_CLIENT_ID", "3"))
IBKR_TIMEOUT = 10

# Yahoo Finance 配置
YAHOO_VIX_URL = "https://query1.finance.yahoo.com/v8/finance/chart/^VIX"
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ========== 全局连接池（线程局部存储）==========
_thread_local = threading.local()


def _get_ibkr_connection() -> Optional[IB]:
    """
    获取线程局部的 IBKR 连接
    
    关键改进:
    - 使用 threading.local() 避免跨线程共享
    - 每个 Flask 工作线程有独立连接
    - 使用 util.run() 在工作线程创建事件循环
    """
    if not IBKR_AVAILABLE:
        return None
    
    # 检查当前线程是否已有连接
    if hasattr(_thread_local, 'ib') and _thread_local.ib.isConnected():
        return _thread_local.ib
    
    # 创建新连接（使用 util.run 确保事件循环正确）
    try:
        print(f"[IBKR] Connecting to {IBKR_HOST}:{IBKR_PORT} (thread: {threading.current_thread().name})...")
        
        ib = IB()
        
        # 🟢 关键修复: 使用 util.run() 在工作线程中创建事件循环
        util.run(
            ib.connectAsync(
                host=IBKR_HOST,
                port=IBKR_PORT,
                clientId=IBKR_CLIENT_ID,
                timeout=IBKR_TIMEOUT
            )
        )
        
        # 启用延迟数据模式
        ib.reqMarketDataType(3)
        
        # 保存到线程局部存储
        _thread_local.ib = ib
        print(f"[IBKR] ✓ Connected (clientId={IBKR_CLIENT_ID})")
        return ib
        
    except Exception as e:
        print(f"[IBKR] ❌ Connection failed: {e}")
        return None


def _fetch_vix_ibkr() -> Optional[float]:
    """
    从 IBKR 获取 VIX（工作线程安全版本）
    """
    ib = _get_ibkr_connection()
    if ib is None:
        return None
    
    try:
        # 定义 VIX 合约
        vix_contract = Index('VIX', 'CBOE')
        ib.qualifyContracts(vix_contract)
        
        # 请求市场数据（使用 snapshot 模式更可靠）
        ticker = ib.reqMktData(vix_contract, snapshot=True)
        
        # 等待数据（最多 IBKR_TIMEOUT 秒）
        start_time = time.time()
        while time.time() - start_time < IBKR_TIMEOUT:
            ib.sleep(0.1)
            
            # 按优先级获取价格
            if ticker.last and ticker.last > 0:
                vix_value = ticker.last
                print(f"[IBKR] ✓ VIX = {vix_value:.2f} (last)")
                ib.cancelMktData(vix_contract)
                return vix_value
            
            if ticker.close and ticker.close > 0:
                vix_value = ticker.close
                print(f"[IBKR] ✓ VIX = {vix_value:.2f} (close)")
                ib.cancelMktData(vix_contract)
                return vix_value
            
            if ticker.bid and ticker.ask and ticker.bid > 0 and ticker.ask > 0:
                vix_value = (ticker.bid + ticker.ask) / 2
                print(f"[IBKR] ✓ VIX = {vix_value:.2f} (mid)")
                ib.cancelMktData(vix_contract)
                return vix_value
        
        print(f"[IBKR] ⚠️ Timeout: No data after {IBKR_TIMEOUT}s")
        ib.cancelMktData(vix_contract)
        return None
        
    except Exception as e:
        print(f"[IBKR] ❌ Error: {e}")
        return None


# ========== Yahoo Finance 数据获取 ==========

def _fetch_vix_yahoo_latest() -> Optional[float]:
    """从 Yahoo Finance 获取 VIX"""
    params = {"interval": "1d", "range": "1mo"}
    try:
        resp = requests.get(YAHOO_VIX_URL, params=params, headers=YAHOO_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("chart", {}).get("result") or []
        if not result:
            return None
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c in closes if c and not math.isnan(c)]
        return float(closes[-1]) if closes else None
    except Exception as e:
        print(f"[Yahoo] ❌ Error: {e}")
        return None


# ========== 缓存管理 ==========

def _load_vix_from_cache() -> Optional[float]:
    """从缓存加载 VIX"""
    if not os.path.exists(VIX_CACHE_FILE):
        return None
    try:
        with open(VIX_CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
        timestamp = cache_data.get("timestamp", 0)
        vix_value = cache_data.get("vix")
        if time.time() - timestamp < VIX_CACHE_TTL:
            age = int(time.time() - timestamp)
            print(f"[Cache] ✓ VIX = {vix_value:.2f} (age: {age}s)")
            return vix_value
        else:
            print("[Cache] ⚠️ Cache expired")
            return None
    except Exception as e:
        print(f"[Cache] ⚠️ Load failed: {e}")
        return None


def _save_vix_to_cache(vix_value: float, source: str = "unknown"):
    """保存 VIX 到缓存"""
    try:
        cache_data = {
            "vix": vix_value,
            "timestamp": time.time(),
            "datetime": datetime.now().isoformat(),
            "source": source
        }
        with open(VIX_CACHE_FILE, 'w') as f:
            json.dump(cache_data, f, indent=2)
        print(f"[Cache] ✓ Saved VIX = {vix_value:.2f} (source: {source})")
    except Exception as e:
        print(f"[Cache] ⚠️ Save failed: {e}")


# ========== 主接口函数 ==========

def get_current_vix(use_cache: bool = True) -> Optional[float]:
    """
    获取当前 VIX 值（多数据源级联）
    """
    # 1. 优先使用缓存（避免频繁请求）
    if use_cache:
        cached_vix = _load_vix_from_cache()
        if cached_vix is not None:
            return cached_vix
    
    # 2. IBKR（主数据源）
    if IBKR_AVAILABLE:
        vix_value = _fetch_vix_ibkr()
        if vix_value is not None:
            _save_vix_to_cache(vix_value, source="IBKR")
            return vix_value
        else:
            print("[IBKR] ⚠️ Failed, trying fallback sources...")
    
    # 3. Yahoo
    vix_value = _fetch_vix_yahoo_latest()
    if vix_value is not None:
        _save_vix_to_cache(vix_value, source="Yahoo")
        return vix_value
    
    print("❌ All VIX data sources failed")
    return None


def get_vix_with_fallback(default: float = 18.0) -> float:
    """获取 VIX，失败时使用回退值"""
    vix = get_current_vix(use_cache=True)
    if vix is None:
        print(f"[VIX] ⚠️ Using fallback value: {default}")
        return default
    print(f"[VIX] ✓ Current value: {vix:.2f}")
    return vix


def get_vix_info() -> Dict:
    """获取 VIX 相关信息（诊断用）"""
    current_vix = get_current_vix(use_cache=False)
    
    cache_exists = os.path.exists(VIX_CACHE_FILE)
    cache_age = None
    cached_vix = None
    cache_source = None
    
    if cache_exists:
        try:
            with open(VIX_CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
            cached_vix = cache_data.get("vix")
            cache_age = int(time.time() - cache_data.get("timestamp", 0))
            cache_source = cache_data.get("source", "unknown")
        except:
            pass
    
    # 检查当前线程的连接状态
    ib_connected = False
    if hasattr(_thread_local, 'ib') and _thread_local.ib.isConnected():
        ib_connected = True
    
    return {
        "current_vix": current_vix,
        "cached_vix": cached_vix,
        "cache_source": cache_source,
        "cache_age_seconds": cache_age,
        "cache_valid": cache_age < VIX_CACHE_TTL if cache_age else False,
        "cache_file": VIX_CACHE_FILE,
        "cache_exists": cache_exists,
        "ibkr_available": IBKR_AVAILABLE,
        "ibkr_connected": ib_connected,
        "thread_name": threading.current_thread().name,
        "ibkr_config": {
            "host": IBKR_HOST,
            "port": IBKR_PORT,
            "client_id": IBKR_CLIENT_ID
        } if IBKR_AVAILABLE else None
    }


def clear_vix_cache():
    """清除 VIX 缓存"""
    if os.path.exists(VIX_CACHE_FILE):
        try:
            os.remove(VIX_CACHE_FILE)
            print("✓ VIX cache cleared")
        except Exception as e:
            print(f"❌ Failed to clear VIX cache: {e}")


def validate_vix(vix_value: float) -> bool:
    """验证 VIX 值的合理性"""
    if not isinstance(vix_value, (int, float)):
        return False
    if vix_value < 5 or vix_value > 100:
        return False
    return True


def test_ibkr_connection() -> bool:
    """测试 IBKR 连接状态"""
    if not IBKR_AVAILABLE:
        print("❌ ib_insync not installed")
        return False
    
    print(f"\n🔍 Testing IBKR connection to {IBKR_HOST}:{IBKR_PORT}...")
    
    vix_value = _fetch_vix_ibkr()
    
    if vix_value is not None:
        print(f"✅ IBKR connection successful! VIX = {vix_value:.2f}")
        return True
    else:
        print("❌ IBKR connection failed")
        return False


# ========== 历史数据 ==========
def get_vix_history(days: int = 20) -> List[float]:
    """获取 VIX 历史数据"""
    params = {"interval": "1d", "range": "3mo"}
    try:
        resp = requests.get(YAHOO_VIX_URL, params=params, headers=YAHOO_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("chart", {}).get("result") or []
        if not result:
            return []
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c in closes if c and not math.isnan(c)]
        return closes[-days:] if len(closes) > days else closes
    except:
        return []