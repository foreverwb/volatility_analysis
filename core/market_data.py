"""
市场数据获取模块 - v2.3.4 (IBKR 集成版本)
Market Data API for VIX

数据源优先级：
1. IBKR (Interactive Brokers) - 主数据源
2. Yahoo Finance - 备用数据源1
3. Alpha Vantage - 备用数据源2
4. 本地缓存
5. 固定默认值 (18.0)
"""
import os
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import time
import requests
import math

# ========== IBKR 集成 ==========
try:
    from ib_insync import IB, Stock, Index
    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False
    print("⚠️ Warning: ib_insync not installed. IBKR data source disabled.")
    print("   Install: pip install ib_insync")


# ========== 配置常量 ==========
VIX_CACHE_FILE = "vix_cache.json"
VIX_CACHE_TTL = 21600  # 缓存有效期 6 小时（秒）

# IBKR 配置
IBKR_HOST = os.environ.get("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.environ.get("IBKR_PORT", "4002"))  # TWS=7497, Gateway=4001/4002
IBKR_CLIENT_ID = int(os.environ.get("IBKR_CLIENT_ID", "3"))
IBKR_TIMEOUT = 10  # 连接/请求超时（秒）

# Alpha Vantage 配置
ALPHA_VANTAGE_API_URL = "https://www.alphavantage.co/query"
ALPHA_VANTAGE_ENV = "ALPHA_VANTAGE_API_KEY"
ALPHA_VANTAGE_KEY = 'STB6RITIM7Q71O1L'

# Yahoo Finance 配置
YAHOO_VIX_URL = "https://query1.finance.yahoo.com/v8/finance/chart/^VIX"
YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


# ========== IBKR 数据获取 ==========

def _fetch_vix_ibkr(timeout: int = IBKR_TIMEOUT, use_delayed: bool = True) -> Optional[float]:
    """
    从 IBKR 获取 VIX 数据（支持实时/延迟数据）
    
    Args:
        timeout: 超时时间（秒）
        use_delayed: 是否使用延迟数据（免费）
        
    Returns:
        VIX 值，失败返回 None
    """
    if not IBKR_AVAILABLE:
        return None
    
    ib = IB()
    
    try:
        # 连接到 IB Gateway
        print(f"[IBKR] Connecting to {IBKR_HOST}:{IBKR_PORT}...")
        ib.connect(
            host=IBKR_HOST,
            port=IBKR_PORT,
            clientId=IBKR_CLIENT_ID,
            timeout=timeout
        )
        
        # 🟢 启用延迟数据模式（免费）
        if use_delayed:
            print("[IBKR] Using delayed market data (free)")
            # 切换到延迟数据模式（市场数据类型 3 = 延迟）
            ib.reqMarketDataType(3)
        
        # 定义 VIX 合约
        vix_contract = Index('VIX', 'CBOE')
        
        # 请求市场数据（snapshot=False 改为持续订阅，更可靠）
        ib.qualifyContracts(vix_contract)
        ticker = ib.reqMktData(vix_contract, snapshot=False)
        
        # 等待数据返回（最多等待 timeout 秒）
        start_time = time.time()
        while time.time() - start_time < timeout:
            ib.sleep(0.1)
            
            # 优先使用 last（最新成交价）
            if ticker.last and ticker.last > 0:
                vix_value = ticker.last
                print(f"[IBKR] ✓ VIX = {vix_value:.2f} (last)")
                return vix_value
            
            # 其次使用 close（前收盘价）
            if ticker.close and ticker.close > 0:
                vix_value = ticker.close
                print(f"[IBKR] ✓ VIX = {vix_value:.2f} (close)")
                return vix_value
            
            # 最后尝试 bid/ask 中间价
            if ticker.bid and ticker.ask and ticker.bid > 0 and ticker.ask > 0:
                vix_value = (ticker.bid + ticker.ask) / 2
                print(f"[IBKR] ✓ VIX = {vix_value:.2f} (mid)")
                return vix_value
        
        # 超时未获取到数据
        print(f"[IBKR] ⚠️ Timeout: No valid data after {timeout}s")
        print(f"[IBKR] Debug: ticker = {ticker}")
        return None
    
    except Exception as e:
        error_str = str(e)
        
        # 检查是否为市场数据订阅错误
        if "354" in error_str or "未订阅" in error_str:
            print(f"[IBKR] ❌ Market Data Subscription Error")
            print(f"[IBKR] 💡 Solution: Enable delayed market data in TWS/Gateway:")
            print(f"[IBKR]    Account → Market Data Subscriptions → Delayed Data")
        else:
            print(f"[IBKR] ❌ Error: {error_str}")
        
        return None
    
    finally:
        # 取消订阅并断开连接
        if ib.isConnected():
            ib.disconnect()
            print("[IBKR] Disconnected")


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
        node = result[0]
        closes = node.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c in closes if c is not None and not (isinstance(c, float) and math.isnan(c))]
        if not closes:
            return None
        return float(closes[-1])
    except Exception as e:
        print(f"[Yahoo] ❌ Error: {e}")
        return None


def _fetch_vix_yahoo_history(days: int) -> List[float]:
    """从 Yahoo Finance 获取 VIX 历史数据"""
    params = {"interval": "1d", "range": "3mo"}
    try:
        resp = requests.get(YAHOO_VIX_URL, params=params, headers=YAHOO_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("chart", {}).get("result") or []
        if not result:
            return []
        node = result[0]
        closes = node.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c in closes if c is not None and not (isinstance(c, float) and math.isnan(c))]
        return closes[-days:] if len(closes) > days else closes
    except Exception as e:
        print(f"[Yahoo History] ❌ Error: {e}")
        return []


# ========== Alpha Vantage 数据获取 ==========

def _get_alpha_vantage_key() -> Optional[str]:
    """获取 Alpha Vantage API Key"""
    env_key = os.environ.get(ALPHA_VANTAGE_ENV)
    if env_key:
        return env_key
    if ALPHA_VANTAGE_KEY:
        return ALPHA_VANTAGE_KEY
    return None


def _fetch_vix_alpha_vantage_latest(api_key: str) -> Optional[float]:
    """从 Alpha Vantage 获取 VIX"""
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
            print(f"[Alpha Vantage] ⚠️ Rate limit: {data.get('Note')}")
        quote = data.get("Global Quote") or {}
        price_str = quote.get("05. price")
        if price_str is None:
            return None
        return float(price_str)
    except Exception as e:
        print(f"[Alpha Vantage] ❌ Error: {e}")
        return None


def _fetch_vix_alpha_vantage_history(days: int, api_key: str) -> List[float]:
    """从 Alpha Vantage 获取 VIX 历史数据"""
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
        ts = data.get("Time Series (Daily)") or {}
        if not ts:
            return []
        dates = sorted(ts.keys())
        closes = [float(ts[d]["4. close"]) for d in dates if "4. close" in ts[d]]
        return closes[-days:] if len(closes) > days else closes
    except Exception as e:
        print(f"[Alpha Vantage History] ❌ Error: {e}")
        return []


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
            "source": source  # 新增：记录数据来源
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
    
    数据源优先级：
    1. IBKR (实时数据，推荐)
    2. 本地缓存（6小时有效期）
    3. Yahoo Finance（备用）
    4. Alpha Vantage（备用）
    
    Args:
        use_cache: 是否使用缓存
        
    Returns:
        VIX 值，失败返回 None
    """
    # 1. 尝试从 IBKR 获取（主数据源）
    if IBKR_AVAILABLE:
        vix_value = _fetch_vix_ibkr()
        if vix_value is not None:
            _save_vix_to_cache(vix_value, source="IBKR")
            return vix_value
        else:
            print("[IBKR] ⚠️ Failed, trying fallback sources...")
    
    # 2. 检查缓存
    if use_cache:
        cached_vix = _load_vix_from_cache()
        if cached_vix is not None:
            return cached_vix
    
    # 3. 回退到 Yahoo Finance
    vix_value = _fetch_vix_yahoo_latest()
    if vix_value is not None:
        _save_vix_to_cache(vix_value, source="Yahoo")
        return vix_value
    
    # 4. 回退到 Alpha Vantage
    api_key = _get_alpha_vantage_key()
    if api_key:
        vix_value = _fetch_vix_alpha_vantage_latest(api_key)
        if vix_value is not None:
            _save_vix_to_cache(vix_value, source="AlphaVantage")
            return vix_value
    
    # 5. 所有数据源失败
    print("❌ All VIX data sources failed")
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
    if api_key:
        return _fetch_vix_alpha_vantage_history(days, api_key)
    
    return []


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
        print(f"[VIX] ⚠️ Using fallback value: {default}")
        return default
    
    print(f"[VIX] ✓ Current value: {vix:.2f}")
    return vix


def validate_vix(vix_value: float) -> bool:
    """验证 VIX 值的合理性"""
    if not isinstance(vix_value, (int, float)):
        return False
    
    if vix_value < 5 or vix_value > 100:
        return False
    
    return True


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
    
    return {
        "current_vix": current_vix,
        "cached_vix": cached_vix,
        "cache_source": cache_source,
        "cache_age_seconds": cache_age,
        "cache_valid": cache_age < VIX_CACHE_TTL if cache_age else False,
        "cache_file": VIX_CACHE_FILE,
        "cache_exists": cache_exists,
        "ibkr_available": IBKR_AVAILABLE,
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


# ========== 测试与诊断 ==========

def test_ibkr_connection() -> bool:
    """
    测试 IBKR 连接状态
    
    Returns:
        True if connection successful
    """
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
        print("\n📋 Troubleshooting:")
        print("   1. Ensure IB Gateway is running")
        print("   2. Check IBKR_HOST and IBKR_PORT environment variables")
        print("   3. Verify API settings in Gateway (Enable ActiveX and Socket Clients)")
        print("   4. Check firewall settings")
        return False

