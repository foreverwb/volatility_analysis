"""
未平仓合约 (Open Interest) 数据获取模块 - v2.3.3 多线程优化版
Data Source: Yahoo Finance (yfinance)
"""
import yfinance as yf
import pandas as pd
from typing import Optional, Tuple, Dict, List, Callable
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import time
from queue import Queue, Empty

from .futu_oi import (
    OI_CACHE_TABLE,
    clear_oi_cache as clear_oi_cache_store,
    compute_delta_oi_windows,
    get_oi_db_path,
    load_oi_cache as load_oi_cache_store,
    save_oi_cache as save_oi_cache_store,
)

# ========== 配置参数 ==========
DEFAULT_MAX_WORKERS = 8        # 默认并发线程数
DEFAULT_TIMEOUT = 30           # 单个请求超时（秒）
MAX_RETRIES = 2                # 失败重试次数
RETRY_DELAY = 1                # 重试延迟（秒）


def fetch_total_oi(symbol: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[int]:
    """
    获取标的的总未平仓合约量（带超时控制）
    
    Args:
        symbol: 标的代码
        timeout: 超时时间（秒）
        
    Returns:
        总 OI 量，失败返回 None
    """
    try:
        ticker = yf.Ticker(symbol)
        expirations = ticker.options
        
        if not expirations:
            print(f"⚠ {symbol}: No options data")
            return None
        
        total_oi = 0
        
        for exp in expirations:
            try:
                opt_chain = ticker.option_chain(exp)
                total_oi += opt_chain.calls['openInterest'].sum()
                total_oi += opt_chain.puts['openInterest'].sum()
            except Exception as e:
                print(f"⚠ {symbol} exp {exp}: {str(e)[:50]}")
                continue
        
        return int(total_oi) if total_oi > 0 else None
    
    except Exception as e:
        print(f"❌ {symbol}: {str(e)[:80]}")
        return None


def load_oi_cache() -> dict:
    """加载 OI 缓存（SQLite 后端，兼容旧接口）。"""
    return load_oi_cache_store()


def save_oi_cache(cache: dict):
    """保存 OI 缓存（SQLite 后端，兼容旧接口）。"""
    save_oi_cache_store(cache)


def get_oi_with_delta(symbol: str) -> Tuple[Optional[int], Optional[int]]:
    """
    获取当前 OI 及 ΔOI_1D
    
    Args:
        symbol: 标的代码
        
    Returns:
        (current_oi, delta_oi_1d)
    """
    # 1. 获取当前 OI
    current_oi = fetch_total_oi(symbol)
    if current_oi is None:
        return (None, None)
    
    # 2. 加载缓存（线程安全）
    cache = load_oi_cache()
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 3. 查找最近的历史数据（考虑周末/节假日）
    symbol_key = symbol.upper()
    symbol_cache = cache.get(symbol_key) or cache.get(symbol) or {}

    # 4. 计算 delta（统一窗口逻辑）
    delta_oi, _, _ = compute_delta_oi_windows(current_oi, symbol_cache)
    
    # 5. 更新缓存（线程安全）
    if symbol_key not in cache:
        cache[symbol_key] = {}
    
    cache[symbol_key][today] = current_oi
    
    # 清理超过 7 天的数据
    cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    cache[symbol_key] = {
        date: oi for date, oi in cache[symbol_key].items()
        if date >= cutoff
    }
    
    save_oi_cache(cache)
    
    return (current_oi, delta_oi)


def _fetch_single_symbol(symbol: str, retry_count: int = 0) -> Tuple[str, Optional[int], Optional[int]]:
    """
    单个 symbol 的获取逻辑（内部函数，支持重试）
    
    Returns:
        (symbol, current_oi, delta_oi)
    """
    try:
        current_oi, delta_oi = get_oi_with_delta(symbol)
        return (symbol, current_oi, delta_oi)
    
    except Exception as e:
        if retry_count < MAX_RETRIES:
            print(f"⚠ {symbol}: Retry {retry_count + 1}/{MAX_RETRIES}")
            time.sleep(RETRY_DELAY)
            return _fetch_single_symbol(symbol, retry_count + 1)
        else:
            print(f"❌ {symbol}: Failed after {MAX_RETRIES} retries")
            return (symbol, None, None)


def batch_fetch_oi(
    symbols: List[str], 
    max_workers: int = DEFAULT_MAX_WORKERS,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    progress_queue: Optional[Queue] = None  # 🟢 新增：线程安全的进度队列
) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
    """
    批量获取多个标的的 OI 数据（多线程并发）- 线程安全版本
    
    Args:
        symbols: 标的列表
        max_workers: 最大并发线程数
        progress_callback: 进度回调函数（在主线程中调用，传统方式）
        progress_queue: 进度队列（用于 SSE 流式推送，线程安全）
        
    Returns:
        {symbol: (current_oi, delta_oi_1d)}
        
    使用示例：
        # 方式1：传统回调（适用于同步场景）
        >>> results = batch_fetch_oi(symbols, progress_callback=on_progress)
        
        # 方式2：队列模式（适用于 SSE 流式推送）
        >>> progress_queue = Queue()
        >>> results = batch_fetch_oi(symbols, progress_queue=progress_queue)
        >>> while not progress_queue.empty():
        ...     progress = progress_queue.get()
        ...     yield f"data: {json.dumps(progress)}\n\n"
    """
    if not symbols:
        return {}
    
    print(f"\n📊 Starting OI fetch for {len(symbols)} symbols (max_workers={max_workers})...")
    start_time = time.time()
    
    results = {}
    completed = 0
    total = len(symbols)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_symbol = {
            executor.submit(_fetch_single_symbol, symbol): symbol 
            for symbol in symbols
        }
        
        # 处理完成的任务
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            
            try:
                symbol, current_oi, delta_oi = future.result(timeout=DEFAULT_TIMEOUT)
                results[symbol] = (current_oi, delta_oi)
                
                completed += 1
                
                # 状态输出（控制台）
                if delta_oi is not None:
                    sign = "+" if delta_oi > 0 else ""
                    print(f"✓ [{completed}/{total}] {symbol}: OI={current_oi:,}, ΔOI={sign}{delta_oi:,}")
                elif current_oi is not None:
                    print(f"⚠ [{completed}/{total}] {symbol}: OI={current_oi:,}, ΔOI=N/A (首次运行)")
                else:
                    print(f"❌ [{completed}/{total}] {symbol}: Failed to fetch OI")
                
                # 🟢 线程安全的进度通知
                progress_data = {
                    'completed': completed,
                    'total': total,
                    'symbol': symbol,
                    'current_oi': current_oi,
                    'delta_oi': delta_oi
                }
                
                # 方式1：使用队列（优先，线程安全）
                if progress_queue is not None:
                    try:
                        progress_queue.put(progress_data, block=False)
                    except Exception as e:
                        print(f"⚠ Warning: Failed to put progress to queue: {e}")
                
                # 方式2：使用回调（传统方式，非线程安全，仅适用于同步场景）
                if progress_callback is not None:
                    try:
                        progress_callback(completed, total, symbol)
                    except Exception as e:
                        print(f"⚠ Warning: Progress callback failed: {e}")
            
            except Exception as e:
                completed += 1
                print(f"❌ [{completed}/{total}] {symbol}: {str(e)[:50]}")
                results[symbol] = (None, None)
                
                # 即使失败也要通知进度
                if progress_queue is not None:
                    try:
                        progress_queue.put({
                            'completed': completed,
                            'total': total,
                            'symbol': symbol,
                            'error': str(e)
                        }, block=False)
                    except:
                        pass
    
    elapsed = time.time() - start_time
    success_count = sum(1 for _, (oi, _) in results.items() if oi is not None)
    
    print(f"\n📊 OI fetch completed: {success_count}/{total} successful in {elapsed:.1f}s")
    print(f"   Average: {elapsed/total:.2f}s per symbol")
    
    # 🟢 发送完成信号到队列
    if progress_queue is not None:
        try:
            progress_queue.put({'type': 'complete'}, block=False)
        except:
            pass
    
    return results


# ========== 性能优化工具 ==========

def estimate_fetch_time(num_symbols: int, max_workers: int = DEFAULT_MAX_WORKERS) -> float:
    """
    估算批量获取耗时
    
    Args:
        num_symbols: 标的数量
        max_workers: 并发数
        
    Returns:
        预计耗时（秒）
    """
    avg_time_per_symbol = 3.0  # 平均 3 秒/标的
    batches = (num_symbols + max_workers - 1) // max_workers
    return batches * avg_time_per_symbol


def auto_tune_workers(num_symbols: int) -> int:
    """
    根据标的数量自动调整并发数
    
    Args:
        num_symbols: 标的数量
        
    Returns:
        推荐的 max_workers
    """
    if num_symbols <= 5:
        return 3
    elif num_symbols <= 15:
        return 5
    elif num_symbols <= 30:
        return 8
    else:
        return 10


# ========== 诊断工具 ==========

def get_oi_info(symbol: str) -> dict:
    """获取 OI 数据的详细信息（用于调试）"""
    cache = load_oi_cache()
    symbol_key = symbol.upper()
    symbol_cache = cache.get(symbol_key) or cache.get(symbol) or {}
    
    current_oi, delta_oi = get_oi_with_delta(symbol)
    db_path = get_oi_db_path()
    
    return {
        "symbol": symbol_key,
        "current_oi": current_oi,
        "delta_oi_1d": delta_oi,
        "cache_history": symbol_cache,
        "cache_backend": "sqlite",
        "cache_db_path": db_path,
        "cache_table": OI_CACHE_TABLE,
        "cache_exists": os.path.exists(db_path),
    }


def clear_oi_cache():
    """清除 OI 缓存（SQLite 表）。"""
    clear_oi_cache_store()
    print("✓ OI cache cleared")


def benchmark_performance(symbols: List[str], max_workers_list: List[int] = [1, 5, 8, 10]):
    """
    性能基准测试
    
    Args:
        symbols: 测试标的列表
        max_workers_list: 要测试的并发数列表
        
    示例：
        >>> benchmark_performance(["AAPL", "TSLA", "NVDA", "MSFT", "GOOGL"])
    """
    print(f"\n🔬 Performance Benchmark ({len(symbols)} symbols)\n")
    print(f"{'Workers':<10} {'Time (s)':<12} {'Speed':<15}")
    print("-" * 40)
    
    for workers in max_workers_list:
        start = time.time()
        batch_fetch_oi(symbols, max_workers=workers)
        elapsed = time.time() - start
        speedup = (elapsed / (elapsed / workers)) if workers > 1 else 1.0
        
        print(f"{workers:<10} {elapsed:<12.2f} {speedup:.2f}x")


# ========== 使用示例 ==========

if __name__ == "__main__":
    # 示例 1: 批量获取
    symbols = ["AAPL", "TSLA", "NVDA", "MSFT", "GOOGL"]
    results = batch_fetch_oi(symbols, max_workers=5)
    
    # 示例 2: 带进度回调
    def progress(completed, total, symbol):
        percent = (completed / total) * 100
        print(f"Progress: {percent:.1f}%")
    
    results = batch_fetch_oi(symbols, progress_callback=progress)
    
    # 示例 3: 性能测试
    # benchmark_performance(symbols)
