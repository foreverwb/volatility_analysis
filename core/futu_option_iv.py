"""
Futu OpenAPI 期权隐含波动率获取 - v2.4.0 性能优化版
用于计算 IV7D/IV30D/IV60D/IV90D

优化内容：
1. ✨ 并发获取多个标的（ThreadPoolExecutor）
2. ✨ 精简日志输出，增强可读性
3. ✨ 优化获取顺序：先快后慢（OI → IV）
4. ✨ 添加进度回调支持
"""
from __future__ import annotations

import importlib.util
import os
from datetime import date, datetime
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import time


DEFAULT_OPEND_HOST = os.getenv("FUTU_OPEND_HOST", "127.0.0.1")
DEFAULT_OPEND_PORT = int(os.getenv("FUTU_OPEND_PORT", "11111"))
DEFAULT_MARKET_PREFIX = os.getenv("FUTU_MARKET_PREFIX", "US")
SNAPSHOT_CHUNK_SIZE = int(os.getenv("FUTU_SNAPSHOT_CHUNK", "200"))
HAS_FUTU = importlib.util.find_spec("futu") is not None


def _format_symbol(symbol: str, market_prefix: str) -> str:
    symbol = symbol.strip().upper()
    if "." in symbol:
        return symbol
    return f"{market_prefix}.{symbol}"


def _parse_expiry_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value if not isinstance(value, datetime) else value.date()
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime().date()
        except Exception:
            return None
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


def _extract_iv_column(columns: Iterable[str]) -> Optional[str]:
    candidates = [
        "implied_volatility",
        "implied_vol",
        "option_implied_volatility",
        "iv",
        "imp_vol",
    ]
    for col in candidates:
        if col in columns:
            return col
    return None


def _normalize_iv_value(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        iv = float(value)
    except (TypeError, ValueError):
        return None
    if iv <= 0:
        return None
    return iv * 100 if iv <= 3 else iv


def _chunked(values: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(values), size):
        yield values[i : i + size]


def _fetch_snapshot_iv(quote_ctx: Any, option_codes: List[str], ret_ok: Any) -> List[float]:
    """获取期权合约快照的IV值"""
    iv_values: List[float] = []
    for batch in _chunked(option_codes, SNAPSHOT_CHUNK_SIZE):
        ret, data = quote_ctx.get_market_snapshot(batch)
        if ret != ret_ok:
            continue
        iv_column = _extract_iv_column(data.columns)
        if not iv_column:
            continue
        for value in data[iv_column].tolist():
            iv = _normalize_iv_value(value)
            if iv is not None:
                iv_values.append(iv)
    return iv_values


def _collect_expiry_map(chain_df) -> Dict[date, List[str]]:
    """构建到期日->合约代码映射"""
    expiry_map: Dict[date, List[str]] = {}
    for _, row in chain_df.iterrows():
        exp_raw = row.get("exp_time") or row.get("expiry_date") or row.get("strike_time")
        expiry = _parse_expiry_date(exp_raw)
        code = row.get("code") or row.get("option_code")
        if not expiry or not code:
            continue
        expiry_map.setdefault(expiry, []).append(code)
    return expiry_map


def _select_nearest_expiry(expiries: List[date], target_days: int) -> Optional[date]:
    """选择最接近目标天数的到期日"""
    if not expiries:
        return None
    today = date.today()
    filtered = [exp for exp in expiries if (exp - today).days > 0]
    if not filtered:
        return None
    return min(filtered, key=lambda exp: abs((exp - today).days - target_days))


def _fetch_single_symbol_iv(
    symbol: str,
    host: str,
    port: int,
    market_prefix: str
) -> Dict[str, Optional[float]]:
    """
    获取单个标的的 IV 期限结构（内部函数）
    
    Returns:
        {"IV_7D": xx, "IV_30D": xx, "IV_60D": xx, "IV_90D": xx, "IV30": xx}
    """
    from futu import OpenQuoteContext, OptionType, RET_OK
    
    formatted = _format_symbol(symbol, market_prefix)
    
    with OpenQuoteContext(host=host, port=port) as quote_ctx:
        # 1. 获取期权链
        ret, chain_df = quote_ctx.get_option_chain(formatted, option_type=OptionType.ALL)
        if ret != RET_OK:
            print(f"⚠️  {symbol}: 期权链获取失败")
            return {}
        
        expiry_map = _collect_expiry_map(chain_df)
        if not expiry_map:
            print(f"⚠️  {symbol}: 期权链为空")
            return {}
        
        # 2. 获取每个到期日的 IV（静默处理，不打印每个到期日）
        expiry_iv: Dict[date, float] = {}
        total_contracts = sum(len(codes) for codes in expiry_map.values())
        
        for expiry, codes in expiry_map.items():
            iv_values = _fetch_snapshot_iv(quote_ctx, codes, RET_OK)
            if iv_values:
                expiry_iv[expiry] = median(iv_values)
        
        if not expiry_iv:
            print(f"⚠️  {symbol}: 无有效 IV 数据")
            return {}
        
        # 3. 计算期限结构
        expiries = sorted(expiry_iv.keys())
        iv_data: Dict[str, Optional[float]] = {}
        
        for target in (7, 30, 60, 90):
            nearest_expiry = _select_nearest_expiry(expiries, target)
            key = f"IV_{target}D"
            iv_data[key] = expiry_iv.get(nearest_expiry) if nearest_expiry else None
        
        # 4. 兼容字段
        if iv_data.get("IV_30D") is not None:
            iv_data["IV30"] = iv_data["IV_30D"]
        
        # ✨ 优化：精简输出，只显示关键结果
        iv7 = iv_data.get("IV_7D")
        iv30 = iv_data.get("IV_30D")
        iv60 = iv_data.get("IV_60D")
        iv90 = iv_data.get("IV_90D")
        
        print(
            f"✅ {symbol:6s} │ "
            f"IV_7D: {iv7:5.1f}% │ "
            f"IV_30D: {iv30:5.1f}% │ "
            f"IV_60D: {iv60:5.1f}% │ "
            f"IV_90D: {iv90:5.1f}% │ "
            f"({len(expiry_map)} 到期日, {total_contracts} 合约)"
        )
        
        return iv_data


def fetch_iv_term_structure(
    symbols: List[str],
    host: str = DEFAULT_OPEND_HOST,
    port: int = DEFAULT_OPEND_PORT,
    market_prefix: str = DEFAULT_MARKET_PREFIX,
    max_workers: int = 5,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> Dict[str, Dict[str, Optional[float]]]:
    """
    🚀 并发获取多个标的的 IV 期限结构（优化版）
    
    Args:
        symbols: 标的列表
        host: Futu OpenD 地址
        port: Futu OpenD 端口
        market_prefix: 市场前缀（US/HK）
        max_workers: 最大并发线程数（推荐3-5，避免触发Futu限流）
        progress_callback: 进度回调函数 (completed, total, symbol)
        
    Returns:
        {symbol: {"IV_7D": xx, "IV_30D": xx, "IV_60D": xx, "IV_90D": xx}}
    """
    if not HAS_FUTU:
        print("⚠️  futu-api 未安装，跳过 IV 期限结构获取")
        return {}
    
    if not symbols:
        return {}
    
    print(f"\n{'='*80}")
    print(f"📡 Futu IV 数据获取 - 并发模式")
    print(f"   连接: {host}:{port} | 市场: {market_prefix} | 并发: {max_workers} 线程")
    print(f"   标的数量: {len(symbols)}")
    print(f"{'='*80}\n")
    
    results: Dict[str, Dict[str, Optional[float]]] = {}
    completed = 0
    start_time = time.time()
    
    # 🚀 并发获取
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_symbol = {
            executor.submit(
                _fetch_single_symbol_iv,
                symbol,
                host,
                port,
                market_prefix
            ): symbol
            for symbol in symbols
        }
        
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            
            try:
                iv_data = future.result(timeout=60)
                results[symbol.upper()] = iv_data
                
                completed += 1
                
                # 进度回调
                if progress_callback:
                    try:
                        progress_callback(completed, len(symbols), symbol)
                    except Exception as e:
                        print(f"⚠️  进度回调失败: {e}")
                
            except Exception as e:
                completed += 1
                print(f"❌ {symbol:6s} │ 获取失败: {str(e)[:60]}")
                results[symbol.upper()] = {}
    
    elapsed = time.time() - start_time
    success_count = sum(1 for data in results.values() if data.get("IV_30D") is not None)
    
    print(f"\n{'='*80}")
    print(f"📊 IV 获取完成: {success_count}/{len(symbols)} 成功")
    print(f"   总耗时: {elapsed:.1f}s | 平均: {elapsed/len(symbols):.1f}s/标的")
    print(f"{'='*80}\n")
    
    return results


# ========== 兼容旧版 API（不带并发） ==========

def fetch_iv_term_structure_legacy(
    symbols: List[str],
    host: str = DEFAULT_OPEND_HOST,
    port: int = DEFAULT_OPEND_PORT,
    market_prefix: str = DEFAULT_MARKET_PREFIX,
) -> Dict[str, Dict[str, Optional[float]]]:
    """
    ⚠️  旧版串行获取（已弃用，请使用 fetch_iv_term_structure）
    """
    print("⚠️  警告: 使用旧版串行 API，建议切换到并发版本")
    return fetch_iv_term_structure(
        symbols,
        host=host,
        port=port,
        market_prefix=market_prefix,
        max_workers=1  # 串行模式
    )