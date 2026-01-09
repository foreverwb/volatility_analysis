"""
Futu OpenAPI IV 期限结构计算
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, List, Optional, Tuple
import os
import time

from futu import OpenQuoteContext, OptionType, RET_OK


@dataclass
class OptionContract:
    code: str
    option_type: OptionType


@dataclass
class IVTermResult:
    iv7: Optional[float] = None
    iv30: Optional[float] = None
    iv60: Optional[float] = None
    iv90: Optional[float] = None
    total_oi: Optional[int] = None


class RateLimiter:
    def __init__(self, max_calls: int, period_seconds: int) -> None:
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self.calls: deque = deque()

    def acquire(self) -> None:
        now = time.time()
        while self.calls and now - self.calls[0] >= self.period_seconds:
            self.calls.popleft()
        if len(self.calls) >= self.max_calls:
            sleep_seconds = self.period_seconds - (now - self.calls[0]) + 0.01
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        self.calls.append(time.time())


def estimate_iv_fetch_time(
    symbol_count: int,
    windows_per_symbol: int = 4,
    option_type_count: int = 2
) -> float:
    """
    根据接口限流估算 IV 获取耗时（秒）
    """
    option_chain_calls = symbol_count * windows_per_symbol * option_type_count
    snapshot_calls = symbol_count  # 近似按每个标的 1 次快照（全链下将被低估）

    chain_batches = (option_chain_calls + 9) // 10
    snapshot_batches = (snapshot_calls + 59) // 60

    return max(chain_batches, snapshot_batches) * 30.0


def fetch_iv_terms(
    symbols: Iterable[str],
    max_days: int = 120,
    window_days: int = 30,
    max_retries: int = 2
) -> Dict[str, IVTermResult]:
    """
    批量获取 IV7/IV30/IV60/IV90
    """
    host = os.getenv("FUTU_HOST", "127.0.0.1")
    port = int(os.getenv("FUTU_PORT", "11111"))
    market = os.getenv("FUTU_MARKET", "US")

    quote_ctx = OpenQuoteContext(host=host, port=port)
    chain_limiter = RateLimiter(max_calls=10, period_seconds=30)
    snapshot_limiter = RateLimiter(max_calls=60, period_seconds=30)

    results: Dict[str, IVTermResult] = {}
    symbols_list = list(symbols)
    total = len(symbols_list)
    start_ts = time.time()

    try:
        for idx, symbol in enumerate(symbols_list, start=1):
            try:
                result = _fetch_symbol_iv_terms_with_retry(
                    symbol=symbol,
                    market=market,
                    quote_ctx=quote_ctx,
                    chain_limiter=chain_limiter,
                    snapshot_limiter=snapshot_limiter,
                    max_days=max_days,
                    window_days=window_days,
                    max_retries=max_retries
                )
                results[symbol] = result
                progress = f"[{idx}/{total}]"
                print(
                    f"✓ {progress} {symbol}: IV7={_fmt_iv(result.iv7)} "
                    f"IV30={_fmt_iv(result.iv30)} IV60={_fmt_iv(result.iv60)} "
                    f"IV90={_fmt_iv(result.iv90)}"
                )
            except Exception as exc:
                print(f"❌ {symbol}: IV 计算失败: {exc}")
                results[symbol] = IVTermResult()
    finally:
        quote_ctx.close()

    elapsed = time.time() - start_ts
    elapsed_minutes = elapsed / 60.0
    success = sum(
        1 for v in results.values()
        if v.iv7 is not None or v.iv30 is not None or v.iv60 is not None or v.iv90 is not None
    )
    print(f"✓ {success}/{total} successful in {elapsed_minutes:.1f}m")
    return results


def _fetch_symbol_iv_terms_with_retry(
    symbol: str,
    market: str,
    quote_ctx: OpenQuoteContext,
    chain_limiter: RateLimiter,
    snapshot_limiter: RateLimiter,
    max_days: int,
    window_days: int,
    max_retries: int
) -> IVTermResult:
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return _fetch_symbol_iv_terms(
                symbol=symbol,
                market=market,
                quote_ctx=quote_ctx,
                chain_limiter=chain_limiter,
                snapshot_limiter=snapshot_limiter,
                max_days=max_days,
                window_days=window_days
            )
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                sleep_seconds = min(30.0, 2 ** attempt)
                time.sleep(sleep_seconds)
            else:
                raise
    raise RuntimeError(f"{symbol}: IV fetch failed: {last_error}")
def _fetch_symbol_iv_terms(
    symbol: str,
    market: str,
    quote_ctx: OpenQuoteContext,
    chain_limiter: RateLimiter,
    snapshot_limiter: RateLimiter,
    max_days: int,
    window_days: int
) -> IVTermResult:
    code = symbol if "." in symbol else f"{market}.{symbol.upper()}"
    today = datetime.now().date()
    end_date = today + timedelta(days=max_days)
    expirations: Dict[str, List[OptionContract]] = defaultdict(list)

    _collect_expirations(
        symbol=symbol,
        code=code,
        quote_ctx=quote_ctx,
        chain_limiter=chain_limiter,
        expirations=expirations,
        start_date=today,
        end_date=end_date,
        window_days=window_days,
        option_types=[OptionType.CALL, OptionType.PUT]
    )

    if not expirations:
        print(f"⚠ {symbol}: 无可用期权到期日")
        return IVTermResult()

    snapshot_map = _fetch_snapshot_map(expirations, quote_ctx, snapshot_limiter)
    dte_points = _build_dte_points(today, expirations, snapshot_map)
    total_oi = _sum_open_interest(snapshot_map)
    iv7 = _interpolate_iv(dte_points, 7)
    iv30 = _interpolate_iv(dte_points, 30)
    iv60 = _interpolate_iv(dte_points, 60)
    iv90 = _interpolate_iv(dte_points, 90)

    return IVTermResult(iv7=iv7, iv30=iv30, iv60=iv60, iv90=iv90, total_oi=total_oi)


def _dataframe_to_records(data) -> List[Dict]:
    if hasattr(data, "to_dict"):
        return data.to_dict("records")
    if isinstance(data, list):
        return data
    return []


def _collect_expirations(
    symbol: str,
    code: str,
    quote_ctx: OpenQuoteContext,
    chain_limiter: RateLimiter,
    expirations: Dict[str, List[OptionContract]],
    start_date: datetime.date,
    end_date: datetime.date,
    window_days: int,
    option_types: List[OptionType]
) -> None:
    window_start = start_date
    while window_start <= end_date:
        window_end = min(window_start + timedelta(days=window_days), end_date)
        for option_type in option_types:
            ret, data = _fetch_option_chain_with_retry(
                quote_ctx=quote_ctx,
                chain_limiter=chain_limiter,
                code=code,
                start_date=window_start.strftime("%Y-%m-%d"),
                end_date=window_end.strftime("%Y-%m-%d"),
                option_type=option_type
            )

            if ret != RET_OK:
                print(f"⚠ {symbol}: get_option_chain 失败: {data}")
            else:
                records = _dataframe_to_records(data)
                for record in records:
                    expiry = _get_expiry_date(record)
                    option_code = _get_option_code(record)
                    if expiry and option_code:
                        expirations[expiry].append(OptionContract(option_code, option_type))

        window_start = window_end + timedelta(days=1)


def _get_option_chain_window(
    quote_ctx: OpenQuoteContext,
    code: str,
    start_date: str,
    end_date: str,
    option_type: OptionType
) -> Tuple[int, Any]:
    variants = [
        {"begin_time": start_date, "end_time": end_date},
        {"start_time": start_date, "end_time": end_date},
        {"start_date": start_date, "end_date": end_date},
        {"start": start_date, "end": end_date}
    ]
    positional_variants = [
        (start_date, end_date),
        ()
    ]
    last_error = None
    for variant in variants:
        try:
            kwargs = {
                "option_type": option_type,
                **variant
            }
            ret, data = quote_ctx.get_option_chain(code, **kwargs)
            return ret, data
        except TypeError as exc:
            last_error = exc
            continue
    for args in positional_variants:
        try:
            kwargs = {"option_type": option_type}
            ret, data = quote_ctx.get_option_chain(code, *args, **kwargs)
            return ret, data
        except TypeError as exc:
            last_error = exc
            continue
    raise TypeError(f"get_option_chain 参数不兼容: {last_error}")


def _fetch_option_chain_with_retry(
    quote_ctx: OpenQuoteContext,
    chain_limiter: RateLimiter,
    code: str,
    start_date: str,
    end_date: str,
    option_type: OptionType,
    max_retries: int = 2
) -> Tuple[int, Any]:
    last_data = None
    for attempt in range(max_retries + 1):
        chain_limiter.acquire()
        ret, data = _get_option_chain_window(
            quote_ctx=quote_ctx,
            code=code,
            start_date=start_date,
            end_date=end_date,
            option_type=option_type
        )
        last_data = data
        if ret == RET_OK:
            return ret, data
        if isinstance(data, str) and "频率太高" in data and attempt < max_retries:
            time.sleep(30.0)
            continue
        return ret, data
    return ret, last_data


def _get_expiry_date(record: Dict) -> Optional[str]:
    for key in ("expiry_date", "expire_date", "expiration_date", "expiry", "strike_time", "strike_date"):
        value = record.get(key)
        if value:
            return str(value).split(" ")[0]
    return None


def _get_option_code(record: Dict) -> Optional[str]:
    for key in ("code", "option_code", "contract_code", "security_code"):
        value = record.get(key)
        if value:
            return str(value)
    return None


def _fetch_snapshot_map(
    expirations: Dict[str, List[OptionContract]],
    quote_ctx: OpenQuoteContext,
    snapshot_limiter: RateLimiter
) -> Dict[str, Dict]:
    codes = []
    for option_codes in expirations.values():
        codes.extend(contract.code for contract in option_codes)

    snapshot_map: Dict[str, Dict] = {}
    chunk_size = 400
    for idx in range(0, len(codes), chunk_size):
        batch = codes[idx:idx + chunk_size]
        snapshot_limiter.acquire()
        ret, data = quote_ctx.get_market_snapshot(batch)
        if ret != RET_OK:
            print(f"⚠ 快照失败: {data}")
            continue
        records = _dataframe_to_records(data)
        for rec in records:
            code = rec.get("code") or rec.get("option_code")
            if code:
                snapshot_map[code] = rec
    return snapshot_map


def _build_dte_points(
    today,
    expirations: Dict[str, List[OptionContract]],
    snapshot_map: Dict[str, Dict]
) -> List[Tuple[int, float]]:
    points = []
    for expiry, option_codes in expirations.items():
        exp_date = _parse_date(expiry)
        if not exp_date:
            continue
        dte = (exp_date - today).days
        if dte <= 0:
            continue
        chosen_iv = _pick_atm_iv(option_codes, snapshot_map)
        if chosen_iv is None:
            continue
        points.append((dte, chosen_iv))
    points.sort(key=lambda x: x[0])
    return points


def _pick_atm_iv(option_contracts: List[OptionContract], snapshot_map: Dict[str, Dict]) -> Optional[float]:
    best_iv = None
    best_diff = None
    for contract in option_contracts:
        if contract.option_type != OptionType.CALL:
            continue
        snapshot = snapshot_map.get(contract.code)
        if not snapshot:
            continue
        delta = _get_snapshot_value(snapshot, ["option_delta", "delta"])
        iv = _get_snapshot_value(snapshot, ["option_implied_volatility", "implied_volatility", "iv"])
        if delta is None or iv is None:
            continue
        diff = abs(delta - 0.5)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_iv = _normalize_iv(iv)
    return best_iv


def _get_snapshot_value(snapshot: Dict, keys: List[str]) -> Optional[float]:
    for key in keys:
        if key in snapshot and snapshot[key] is not None:
            try:
                return float(snapshot[key])
            except Exception:
                return None
    return None


def _sum_open_interest(snapshot_map: Dict[str, Dict]) -> Optional[int]:
    total = 0
    found = False
    for snapshot in snapshot_map.values():
        oi = _get_snapshot_value(snapshot, ["option_open_interest", "open_interest", "oi"])
        if oi is None:
            continue
        found = True
        total += int(oi)
    return total if found else None


def _normalize_iv(iv_value: float) -> float:
    iv = float(iv_value)
    if iv <= 1.5:
        return iv * 100.0
    return iv


def _parse_date(value: str) -> Optional[datetime.date]:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except Exception:
            continue
    return None


def _interpolate_iv(points: List[Tuple[int, float]], target_day: int) -> Optional[float]:
    if not points:
        return None
    if len(points) == 1:
        return points[0][1]

    lower = None
    upper = None
    for dte, iv in points:
        if dte == target_day:
            return iv
        if dte < target_day:
            lower = (dte, iv)
        if dte > target_day and upper is None:
            upper = (dte, iv)
            break

    if lower and upper:
        return _variance_interpolation(lower, upper, target_day)
    if lower:
        return lower[1]
    if upper:
        return upper[1]
    return None


def _variance_interpolation(
    lower: Tuple[int, float],
    upper: Tuple[int, float],
    target_day: int
) -> float:
    d1, iv1 = lower
    d2, iv2 = upper
    if d2 == d1:
        return iv1
    var1 = (iv1 / 100.0) ** 2
    var2 = (iv2 / 100.0) ** 2
    weight = (target_day - d1) / (d2 - d1)
    var_t = var1 + (var2 - var1) * weight
    return (var_t ** 0.5) * 100.0


def _fmt_iv(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"
