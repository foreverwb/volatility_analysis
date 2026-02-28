"""
API 扩展模块 - v2.3.3 VIX增强版
为 swing 项目提供市场参数查询接口
"""

from flask import jsonify, request
from datetime import datetime
from collections import defaultdict
import re
from typing import Optional, Dict, Any, List, Tuple

from bridge.builders import build_bridge_snapshot
from core.cleaning import clean_record, normalize_dataset
from core.api_constants import (
    BRIDGE_BATCH_DEFAULT_LIMIT,
    BRIDGE_BATCH_MIN_DIRECTION_SCORE,
    BRIDGE_BATCH_MIN_VOL_SCORE,
)
from storage.sqlite_repo import get_records_repo

records_repo = get_records_repo()


def parse_earnings_date_to_iso(earnings_str: Optional[str]) -> Optional[str]:
    """
    将财报日期字符串转换为 ISO 格式 (YYYY-MM-DD)
    
    输入格式: "22-Oct-2025 BMO" 或 "19-Nov-2025 AMC"
    输出格式: "2025-10-22"
    """
    if not earnings_str or not isinstance(earnings_str, str):
        return None
    
    t = earnings_str.strip()
    parts = t.split()
    if len(parts) >= 2 and parts[-1] in ("AMC", "BMO"):
        t = " ".join(parts[:-1])
    t = t.replace("  ", " ")
    
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%d %b %y"):
        try:
            dt = datetime.strptime(t, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    return None


def get_historical_iv30(symbol: str, target_date: str = None, days: int = 3) -> list:
    """
    获取指定 symbol 最近 N 个交易日的 IV30 值
    
    Args:
        symbol: 股票代码
        target_date: 目标日期 (YYYY-MM-DD)，默认为最新
        days: 需要的交易日数量
        
    Returns:
        按时间升序的 IV30 列表 [T-2, T-1, T]，不足时返回 []
    """
    records = records_repo.list_records_by_symbol(symbol)
    symbol_upper = symbol.upper()
    
    print(f"\n🔍 get_historical_iv30: {symbol}, target={target_date}, days={days}")
    
    # 筛选该 symbol 的所有记录
    symbol_records = [
        r for r in records 
        if r.get('symbol', '').upper() == symbol_upper
    ]
    
    if not symbol_records:
        print(f"❌ {symbol}: No records found in database")
        return []
    
    print(f"  📁 Found {len(symbol_records)} total records for {symbol}")
    
    # 按日期分组（每天只保留最新记录）
    from collections import defaultdict
    records_by_date = defaultdict(list)
    
    for r in symbol_records:
        timestamp = r.get('timestamp', '')
        if not timestamp:
            continue
        
        date_str = timestamp.split(' ')[0]  # 提取日期部分
        records_by_date[date_str].append(r)
    
    print(f"  📅 Available dates: {sorted(records_by_date.keys(), reverse=True)}")
    
    # 每天取最新记录
    daily_latest = {}
    for date_str, day_records in records_by_date.items():
        day_records.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        daily_latest[date_str] = day_records[0]
    
    # 🔧 按日期降序排序
    sorted_dates = sorted(daily_latest.keys(), reverse=True)
    
    # 🔧 如果指定了日期，从该日期开始查找
    start_index = 0
    if target_date:
        if target_date in sorted_dates:
            start_index = sorted_dates.index(target_date)
            print(f"  ✓ Target date {target_date} found at index {start_index}")
        else:
            print(f"❌ {symbol}: Target date {target_date} not found")
            print(f"  Available: {sorted_dates}")
            return []
    
    # 🔧 提取最近 N 个交易日的记录（从 target_date 开始往前数）
    selected_dates = sorted_dates[start_index:start_index + days]
    
    if len(selected_dates) < days:
        print(f"❌ {symbol}: Only {len(selected_dates)} days available, need {days}")
        print(f"  Selected dates: {selected_dates}")
        return []
    
    print(f"  ✓ Selected dates (desc): {selected_dates}")
    
    # 🔧 提取 IV30 值
    iv30_values = []
    for date_str in selected_dates:
        record = daily_latest[date_str]
        
        # 🔧 优先从顶层读取，注意不能用 `or` 因为 0 也是有效值
        iv30 = record.get('iv30')
        if iv30 is None:
            iv30 = record.get('raw_data', {}).get('IV30')
        
        print(f"    📊 {date_str}: iv30(top)={record.get('iv30')}, iv30(raw)={record.get('raw_data', {}).get('IV30')}, final={iv30}")
        
        if iv30 is not None:
            try:
                iv30_float = float(iv30)
                iv30_values.append(iv30_float)
                print(f"    ✓ {date_str}: IV30={iv30_float}")
            except (ValueError, TypeError) as e:
                print(f"    ❌ {date_str}: Cannot convert IV30={iv30} to float: {e}")
                return []
        else:
            print(f"    ❌ {date_str}: IV30 is None")
            return []
    
    # 🔧 返回按时间升序的列表 [T-2, T-1, T]
    # selected_dates 是降序的 [T, T-1, T-2]，所以需要反转
    result = list(reversed(iv30_values))
    print(f"✓ {symbol}: IV30 history (asc) = {result}")
    return result


def compute_iv_path(symbol: str, target_date: str = None, threshold: float = 1.0) -> str:
    """
    计算 IV30 的趋势路径
    
    Args:
        symbol: 股票代码
        target_date: 目标日期 (YYYY-MM-DD)
        threshold: 平坦判定阈值（百分比）
        
    Returns:
        "Rising" | "Falling" | "Flat" | "Insufficient_Data"
    """
    print(f"\n🔍 Computing iv_path for {symbol} (target_date={target_date})")
    
    iv_history = get_historical_iv30(symbol, target_date, days=3)
    
    if len(iv_history) < 3:
        print(f"❌ {symbol}: Insufficient data (got {len(iv_history)} days, need 3) -> skip iv_path")
        return None
    
    iv_t_minus_2, iv_t_minus_1, iv_t = iv_history
    print(f"  📈 IV30 history: T-2={iv_t_minus_2}, T-1={iv_t_minus_1}, T={iv_t}")
    
    # 计算变化百分比
    def pct_change(old, new):
        if old == 0:
            return 0.0
        return ((new - old) / old) * 100.0
    
    chg_1 = pct_change(iv_t_minus_2, iv_t_minus_1)  # T-2 到 T-1
    chg_2 = pct_change(iv_t_minus_1, iv_t)          # T-1 到 T
    
    print(f"  📊 Changes: T-2→T-1={chg_1:+.2f}%, T-1→T={chg_2:+.2f}%")
    
    # 判断趋势
    # Rising: 连续两日上升
    if chg_1 > threshold and chg_2 > threshold:
        print(f"✓ {symbol}: Rising (both > {threshold}%)")
        return "Rising"
    
    # Falling: 连续两日下降
    if chg_1 < -threshold and chg_2 < -threshold:
        print(f"✓ {symbol}: Falling (both < -{threshold}%)")
        return "Falling"
    
    # Flat: 其他情况（包括方向不连续或变动幅度小）
    print(f"✓ {symbol}: Flat (threshold=±{threshold}%)")
    return "Flat"


def get_latest_record_for_symbol(symbol: str, target_date: str = None) -> Optional[Dict[str, Any]]:
    """
    获取指定 symbol 的分析记录
    
    Args:
        symbol: 股票代码 (大小写不敏感)
        target_date: 目标日期 (YYYY-MM-DD 格式)，如果为 None 则返回最新记录
        
    Returns:
        分析记录，如果不存在返回 None
    """
    records = records_repo.list_records_by_symbol(symbol)
    symbol_upper = symbol.upper()
    
    # 筛选该 symbol 的所有记录
    symbol_records = [
        r for r in records 
        if r.get('symbol', '').upper() == symbol_upper
    ]
    
    if not symbol_records:
        return None
    
    # 如果指定了日期，筛选该日期的记录
    if target_date:
        date_records = [
            r for r in symbol_records
            if r.get('timestamp', '').startswith(target_date)
        ]
        
        if not date_records:
            return None
        
        # 同一天有多条记录，取最新的
        date_records.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return date_records[0]
    
    # 未指定日期，按 timestamp 降序排序，取最新的一条
    symbol_records.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return symbol_records[0]


def extract_swing_params(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 va 分析记录中提取 swing/micro 系统需要的参数
    
    改进 (v2.3.3):
    1. 🟢 优先从记录顶层提取清洗后的字段 (IVR/IV30/HV20/VIX)
    2. 🟢 回退到 raw_data (兼容旧版本数据)
    
    Args:
        record: va 的分析记录
        
    Returns:
        swing 兼容的参数字典
    """
    raw_data = record.get('raw_data', {})
    derived_metrics = record.get('derived_metrics', {})
    
    # 🟢 优先从顶层读取清洗后的字段 (v2.3.3+)，回退到 raw_data
    ivr = record.get('ivr') or raw_data.get('IVR')
    iv30 = record.get('iv30') or raw_data.get('IV30')
    hv20 = record.get('hv20') or raw_data.get('HV20')
    earnings_raw = raw_data.get('Earnings')
    
    # 🟢 从记录顶层提取 VIX (优先级高于 dynamic_params)
    vix = record.get('vix')
    
    # 回退: 如果顶层没有，尝试从 dynamic_params 获取 (兼容旧数据)
    if vix is None:
        vix = record.get('dynamic_params', {}).get('vix')
    
    # 数值清洗
    def clean_number(val):
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        try:
            return float(str(val).replace(',', '').replace('%', ''))
        except:
            return None
    
    # 解析期限结构比率
    term_structure_raw = record.get('term_structure_ratio', 'N/A')
    term_structure_ratio = None
    if term_structure_raw and term_structure_raw != 'N/A':
        try:
            term_structure_ratio = float(term_structure_raw.split()[0])
        except:
            pass
    
    result = {
        'vix': clean_number(vix),  # 🟢 VIX 现在是必要字段
        'ivr': clean_number(ivr),
        'iv30': clean_number(iv30),
        'hv20': clean_number(hv20),
        'earning_date': parse_earnings_date_to_iso(earnings_raw),
        
        # Meso 信号字段
        '_source': {
            'symbol': record.get('symbol'),
            'timestamp': record.get('timestamp'),
            'quadrant': record.get('quadrant'),
            'confidence': record.get('confidence'),
            
            'direction_score': record.get('direction_score', 0.0),
            'vol_score': record.get('vol_score', 0.0),
            'direction_bias': record.get('direction_bias', '中性'),
            'vol_bias': record.get('vol_bias', '中性'),
            
            'is_squeeze': record.get('is_squeeze', False),
            'is_index': record.get('is_index', False),
            
            'spot_vol_corr_score': record.get('spot_vol_corr_score', 0.0),
            'term_structure_ratio': term_structure_ratio,
            
            'ivrv_ratio': derived_metrics.get('ivrv_ratio', 1.0),
            'regime_ratio': derived_metrics.get('regime_ratio', 1.0),
            'days_to_earnings': derived_metrics.get('days_to_earnings'),
        }
    }
    
    return result


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return default


def _to_optional_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _parse_term_structure_ratio(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.upper() == "N/A":
        return None
    try:
        return float(text.split()[0])
    except (TypeError, ValueError, IndexError):
        return None


def _build_bridge_snapshot_for_record(record: Dict[str, Any], cfg_ref: Dict[str, Any]) -> Dict[str, Any]:
    bridge_data = record.get('bridge')

    if bridge_data:
        if hasattr(bridge_data, "to_dict"):
            bridge_data = bridge_data.to_dict()
    else:
        bridge_source: Dict[str, Any] = {}
        raw = record.get('raw_data') or {}
        try:
            cleaned = clean_record(raw)
            normalized = normalize_dataset([cleaned])[0]
            bridge_source.update(normalized)
        except Exception as e:
            print(f"⚠️ Bridge rebuild fallback without normalization: {e}")
            bridge_source.update(raw)

        bridge_source.update(record)
        bridge_data = build_bridge_snapshot(bridge_source, cfg_ref).to_dict()

    if isinstance(bridge_data, dict):
        bridge_data = dict(bridge_data)
        market_state = bridge_data.get('market_state', {}) if isinstance(bridge_data.get('market_state'), dict) else {}
        event_state = bridge_data.get('event_state', {}) if isinstance(bridge_data.get('event_state'), dict) else {}
        bridge_data.setdefault('vix', market_state.get('vix'))
        bridge_data.setdefault('ivr', market_state.get('ivr'))
        bridge_data.setdefault('iv30', market_state.get('iv30'))
        bridge_data.setdefault('hv20', market_state.get('hv20'))
        bridge_data.setdefault('earning_date', event_state.get('earnings_date'))

    return bridge_data


def _build_market_params_for_record(record: Dict[str, Any], bridge_data: Dict[str, Any]) -> Dict[str, Any]:
    params = extract_swing_params(record)
    market_state = bridge_data.get('market_state', {}) if isinstance(bridge_data.get('market_state'), dict) else {}
    event_state = bridge_data.get('event_state', {}) if isinstance(bridge_data.get('event_state'), dict) else {}

    vix = params.get('vix')
    if vix is None:
        vix = _to_optional_float(record.get('vix'))
    if vix is None:
        vix = _to_optional_float(bridge_data.get('vix'))
    if vix is None:
        vix = _to_optional_float(market_state.get('vix'))

    ivr = params.get('ivr')
    if ivr is None:
        ivr = _to_optional_float(record.get('ivr'))
    if ivr is None:
        ivr = _to_optional_float(bridge_data.get('ivr'))
    if ivr is None:
        ivr = _to_optional_float(market_state.get('ivr'))

    iv30 = params.get('iv30')
    if iv30 is None:
        iv30 = _to_optional_float(record.get('iv30'))
    if iv30 is None:
        iv30 = _to_optional_float(bridge_data.get('iv30'))
    if iv30 is None:
        iv30 = _to_optional_float(market_state.get('iv30'))

    hv20 = params.get('hv20')
    if hv20 is None:
        hv20 = _to_optional_float(record.get('hv20'))
    if hv20 is None:
        hv20 = _to_optional_float(bridge_data.get('hv20'))
    if hv20 is None:
        hv20 = _to_optional_float(market_state.get('hv20'))

    earning_date = (
        params.get('earning_date')
        or bridge_data.get('earning_date')
        or event_state.get('earnings_date')
        or record.get('earning_date')
    )
    iv_path = record.get('iv_path') or bridge_data.get('iv_path')

    beta = _to_optional_float(record.get('beta'))
    if beta is None:
        beta = _to_optional_float(bridge_data.get('beta'))

    return {
        'vix': vix,
        'ivr': ivr,
        'iv30': iv30,
        'hv20': hv20,
        'iv_path': iv_path,
        'earning_date': earning_date,
        'beta': beta,
    }


def _build_swing_params_payload(
    symbol: str,
    record: Dict[str, Any],
    target_date: Optional[str] = None,
    vix_override: Optional[float] = None,
) -> Tuple[Dict[str, Any], int]:
    params = extract_swing_params(record)

    if vix_override is not None:
        params['vix'] = vix_override

    params['iv_path'] = compute_iv_path(symbol, target_date)

    missing = []
    for key in ['vix', 'ivr', 'iv30', 'hv20', 'iv_path']:
        if params.get(key) is None:
            missing.append(key)

    if missing:
        return {
            'success': False,
            'error': f'Missing required fields: {missing}',
            'partial_params': params
        }, 400

    payload = {
        'success': True,
        'symbol': symbol,
        'date': target_date or record.get('timestamp', '')[:10],
        'params': {
            'ivr': params['ivr'],
            'iv30': params['iv30'],
            'hv20': params['hv20'],
            'earning_date': params['earning_date'],
            'iv_path': params['iv_path'],
            'vix': params['vix'],
        },
        '_source': params['_source']
    }
    return payload, 200


def _log_batch_request(tag: str, symbols: List[str]) -> None:
    try:
        ts = datetime.now().strftime("%m-%d %H:%M")
        normalized_tag = str(tag or "unknown").strip().upper()
        normalized_symbols = [
            str(symbol).strip().upper()
            for symbol in (symbols or [])
            if str(symbol).strip()
        ]
        symbol_list = "  ".join(normalized_symbols) if normalized_symbols else "-"
        print(f"{ts} │ {normalized_tag} │ cnt:{len(normalized_symbols)} │ {symbol_list}")
    except Exception as e:
        print(f"[BatchAPI] Failed to print request log: {e}")


def _resolve_default_date(requested_date: Optional[str]) -> Optional[str]:
    if requested_date:
        return requested_date
    available_dates = records_repo.list_dates()
    if not available_dates:
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    if today in available_dates:
        return today
    return available_dates[0]


def _resolve_default_direction_gate(cfg_ref: Dict[str, Any]) -> float:
    """
    Keep bridge batch default aligned with current quadrant mapping threshold:
    direction_pref_threshold + direction_pref_neutral_buffer.
    """
    if not isinstance(cfg_ref, dict):
        return BRIDGE_BATCH_MIN_DIRECTION_SCORE

    direction_threshold = _to_optional_float(cfg_ref.get('direction_pref_threshold'))
    if direction_threshold is None or direction_threshold <= 0:
        return BRIDGE_BATCH_MIN_DIRECTION_SCORE

    neutral_buffer = _to_optional_float(cfg_ref.get('direction_pref_neutral_buffer'))
    return abs(direction_threshold) + max(neutral_buffer or 0.0, 0.0)


def _resolve_default_vol_gate(cfg_ref: Dict[str, Any]) -> float:
    """
    Keep vol batch default aligned with current vol mapping threshold:
    vol_pref_threshold + max(vol_pref_threshold * buffer_ratio, buffer_min).
    """
    if not isinstance(cfg_ref, dict):
        return BRIDGE_BATCH_MIN_VOL_SCORE

    vol_threshold = _to_optional_float(
        cfg_ref.get('vol_pref_threshold', cfg_ref.get('penalty_vol_pct_thresh'))
    )
    if vol_threshold is None or vol_threshold <= 0:
        return BRIDGE_BATCH_MIN_VOL_SCORE

    buffer_ratio = _to_optional_float(cfg_ref.get('vol_pref_neutral_buffer_ratio'))
    buffer_min = _to_optional_float(cfg_ref.get('vol_pref_neutral_buffer_min'))
    buffer_width = max(
        abs(vol_threshold) * max(buffer_ratio or 0.0, 0.0),
        max(buffer_min or 0.0, 0.0),
    )
    return abs(vol_threshold) + buffer_width


def register_swing_api(app):
    """
    注册 swing 项目需要的 API 路由
    
    Args:
        app: Flask 应用实例
    """
    
    @app.route('/api/swing/params/<symbol>', methods=['GET'])
    def get_swing_params(symbol: str):
        symbol = symbol.upper()
        
        # 获取日期参数
        target_date = request.args.get('date')
        
        # 验证日期格式
        if target_date:
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', target_date):
                return jsonify({
                    'success': False,
                    'error': f'Invalid date format: {target_date}. Expected YYYY-MM-DD'
                }), 400
        
        # 获取记录（支持指定日期）
        record = get_latest_record_for_symbol(symbol, target_date)
        
        if not record:
            error_msg = f'Symbol {symbol} not found'
            if target_date:
                error_msg += f' for date {target_date}'
            
            # 获取该 symbol 可用的日期列表
            all_records = load_records()
            symbol_dates = sorted(set(
                r.get('timestamp', '')[:10]
                for r in all_records
                if r.get('symbol', '').upper() == symbol
            ), reverse=True)
            
            return jsonify({
                'success': False,
                'error': error_msg,
                'available_dates': symbol_dates[:10] if symbol_dates else None,
                'available_symbols': list(set(
                    r.get('symbol', '').upper() 
                    for r in all_records
                )) if not symbol_dates else None
            }), 404

        # 🟢 支持通过 query string 覆盖 VIX (可选)
        vix_override = request.args.get('vix', type=float)

        payload, status_code = _build_swing_params_payload(
            symbol=symbol,
            record=record,
            target_date=target_date,
            vix_override=vix_override,
        )
        return jsonify(payload), status_code

    @app.route('/api/swing/params/batch', methods=['POST'])
    def get_swing_params_batch():
        """
        批量获取 swing 参数
        """
        data = request.get_json(silent=True) or {}
        target_date = data.get('date')
        symbols = data.get('symbols')
        vix_override = data.get('vix_override')

        if target_date and not re.match(r'^\d{4}-\d{2}-\d{2}$', target_date):
            return jsonify({
                'success': False,
                'error': f'Invalid date format: {target_date}. Expected YYYY-MM-DD'
            }), 400

        if symbols is None:
            symbols = []
        elif isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        elif not isinstance(symbols, list):
            return jsonify({
                'success': False,
                'error': 'symbols must be a list or comma-separated string'
            }), 400

        if vix_override is not None:
            try:
                vix_override = float(vix_override)
            except (TypeError, ValueError):
                return jsonify({
                    'success': False,
                    'error': f'Invalid vix_override: {vix_override}'
                }), 400

        target_date = _resolve_default_date(target_date)

        # Upstream may legitimately pass an empty symbol set after filtering.
        if not symbols:
            _log_batch_request("swing", [])
            return jsonify({
                'success': True,
                'date': target_date,
                'results': [],
                'errors': []
            })

        results = []
        errors = []

        normalized_symbols: List[str] = []
        for raw_symbol in symbols:
            if not isinstance(raw_symbol, str) or not raw_symbol.strip():
                errors.append({
                    'symbol': str(raw_symbol),
                    'message': 'invalid symbol'
                })
                continue

            symbol = raw_symbol.upper()
            normalized_symbols.append(symbol)
            record = get_latest_record_for_symbol(symbol, target_date)
            if not record:
                message = (
                    f'no record found for date {target_date}'
                    if target_date else 'symbol not found'
                )
                errors.append({
                    'symbol': symbol,
                    'message': message
                })
                continue

            payload, status_code = _build_swing_params_payload(
                symbol=symbol,
                record=record,
                target_date=target_date,
                vix_override=vix_override,
            )

            if status_code != 200:
                errors.append({
                    'symbol': symbol,
                    'message': payload.get('error', 'failed to build params')
                })
                continue

            payload.pop('success', None)
            results.append(payload)

        _log_batch_request(
            "swing",
            [item.get("symbol", "") for item in results if item.get("symbol")] or normalized_symbols
        )

        resolved_date = target_date
        if resolved_date is None and results:
            dates = {item.get('date') for item in results if item.get('date')}
            if len(dates) == 1:
                resolved_date = next(iter(dates))

        return jsonify({
            'success': True,
            'date': resolved_date,
            'results': results,
            'errors': errors
        })
    
    @app.route('/api/swing/symbols', methods=['GET'])
    def list_available_symbols():
        """
        列出所有可用的 symbol
        
        响应示例:
            {
                "symbols": ["NVDA", "TSLA", "META", ...],
                "count": 15,
                "latest_date": "2025-12-06"
            }
        """
        records = records_repo.list_records()
        
        # 获取所有唯一的 symbol
        symbols = sorted(set(r.get('symbol', '').upper() for r in records if r.get('symbol')))
        
        # 获取最新日期
        dates = [r.get('timestamp', '')[:10] for r in records if r.get('timestamp')]
        latest_date = max(dates) if dates else None
        
        return jsonify({
            'symbols': symbols,
            'count': len(symbols),
            'latest_date': latest_date
        })
    
    @app.route('/api/swing/dates/<symbol>', methods=['GET'])
    def list_symbol_dates(symbol: str):
        """
        列出指定 symbol 的所有可用日期
        
        响应示例:
            {
                "symbol": "NVDA",
                "dates": ["2025-12-06", "2025-12-05", "2025-12-04"],
                "count": 3
            }
        """
        symbol = symbol.upper()
        records = records_repo.list_records()
        
        # 获取该 symbol 的所有日期
        symbol_dates = sorted(set(
            r.get('timestamp', '')[:10]
            for r in records
            if r.get('symbol', '').upper() == symbol and r.get('timestamp')
        ), reverse=True)
        
        return jsonify({
            'symbol': symbol,
            'dates': symbol_dates,
            'count': len(symbol_dates)
        })


def register_bridge_api(app, cfg=None):
    """
    注册 Bridge 层 API，返回 micro 消费的 bridge snapshot。
    """
    cfg_ref = cfg or {}

    @app.route('/api/bridge/batch', methods=['POST'])
    def get_bridge_batch():
        """
        批量获取 bridge snapshot
        """
        data = request.get_json(silent=True) or {}
        target_date = data.get('date')
        source = data.get('source', 'swing')
        symbols = data.get('symbols')
        min_direction_score = data.get('min_direction_score', _resolve_default_direction_gate(cfg_ref))
        min_vol_score = data.get('min_vol_score', _resolve_default_vol_gate(cfg_ref))
        limit = data.get('limit', BRIDGE_BATCH_DEFAULT_LIMIT)

        if target_date and not re.match(r'^\d{4}-\d{2}-\d{2}$', target_date):
            return jsonify({
                'success': False,
                'error': f'Invalid date format: {target_date}. Expected YYYY-MM-DD'
            }), 400

        if source is None or not isinstance(source, str):
            return jsonify({
                'success': False,
                'error': 'source must be a string'
            }), 400
        source = source.lower().strip() or 'swing'

        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]

        if symbols is not None and not isinstance(symbols, list):
            return jsonify({
                'success': False,
                'error': 'symbols must be a list or comma-separated string'
            }), 400

        symbols_set = None
        normalized_symbols: List[str] = []
        if isinstance(symbols, list):
            seen = set()
            for raw_symbol in symbols:
                if not isinstance(raw_symbol, str) or not raw_symbol.strip():
                    return jsonify({
                        'success': False,
                        'error': f'Invalid symbol in symbols list: {raw_symbol}'
                    }), 400
                symbol = raw_symbol.upper()
                if symbol in seen:
                    continue
                normalized_symbols.append(symbol)
                seen.add(symbol)
            symbols_set = set(normalized_symbols)

        try:
            min_direction_score = float(min_direction_score)
        except (TypeError, ValueError):
            return jsonify({
                'success': False,
                'error': f'Invalid min_direction_score: {min_direction_score}'
            }), 400

        try:
            min_vol_score = float(min_vol_score)
        except (TypeError, ValueError):
            return jsonify({
                'success': False,
                'error': f'Invalid min_vol_score: {min_vol_score}'
            }), 400

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return jsonify({
                'success': False,
                'error': f'Invalid limit: {limit}'
            }), 400

        if limit < 0:
            return jsonify({
                'success': False,
                'error': 'limit must be >= 0'
            }), 400

        requested_date = target_date
        target_date = _resolve_default_date(target_date)
        if not target_date:
            return jsonify({
                'success': False,
                'error': 'No records available'
            }), 404

        records = records_repo.list_records(date=target_date)
        fallback_used = False
        if requested_date and not records:
            fallback_date = _resolve_default_date(None)
            if fallback_date and fallback_date != target_date:
                target_date = fallback_date
                records = records_repo.list_records(date=target_date)
                fallback_used = bool(records)

        results: List[Dict[str, Any]] = []

        for record in records:
            symbol = (record.get('symbol') or '').upper()
            if not symbol:
                continue
            if symbols_set is not None and symbol not in symbols_set:
                continue

            direction_score = _safe_float(record.get('direction_score'), 0.0)
            vol_score = _safe_float(record.get('vol_score'), 0.0)
            direction_bias = record.get('direction_bias', '中性')
            vol_bias = record.get('vol_bias', '中性')

            if source == 'swing':
                if direction_bias not in {'偏多', '偏空'}:
                    continue
                if vol_bias != '买波':
                    continue
                if abs(direction_score) < min_direction_score:
                    continue
            elif source == 'vol':
                if direction_bias not in {'偏多', '偏空'}:
                    continue
                if vol_bias != '卖波':
                    continue
                if abs(vol_score) < min_vol_score:
                    continue
            else:
                if abs(direction_score) < min_direction_score:
                    continue

            try:
                bridge_data = _build_bridge_snapshot_for_record(record, cfg_ref)
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': f'Failed to build bridge snapshot for {symbol}: {e}'
                }), 500

            derived_metrics = record.get('derived_metrics') if isinstance(record.get('derived_metrics'), dict) else {}
            ivrv_ratio = _safe_float(derived_metrics.get('ivrv_ratio', 1.0), 1.0)

            results.append({
                'symbol': symbol,
                'timestamp': record.get('timestamp'),
                'quadrant': record.get('quadrant'),
                'direction_score': direction_score,
                'vol_score': vol_score,
                'direction_bias': direction_bias,
                'vol_bias': vol_bias,
                'confidence': record.get('confidence'),
                'term_structure_ratio': _parse_term_structure_ratio(record.get('term_structure_ratio')),
                'ivrv_ratio': ivrv_ratio,
                'market_params': _build_market_params_for_record(record, bridge_data),
                'bridge': bridge_data,
            })

        if source == 'vol':
            results.sort(key=lambda item: abs(_safe_float(item.get('vol_score'), 0.0)), reverse=True)
        else:
            results.sort(key=lambda item: abs(_safe_float(item.get('direction_score'), 0.0)), reverse=True)

        results = results[:limit]
        result_symbols = [item.get('symbol', '') for item in results if item.get('symbol')]
        # source=swing 可能被筛选成空结果，回退到请求 symbols，避免日志为空而误判未打印。
        _log_batch_request(source, result_symbols or normalized_symbols)

        return jsonify({
            'success': True,
            'date': target_date,
            'source': source,
            'requested_date': requested_date,
            'fallback_used': fallback_used,
            'count': len(results),
            'results': results,
        })

    @app.route('/api/bridge/params/<symbol>', methods=['GET'])
    def get_bridge_params(symbol: str):
        symbol = symbol.upper()
        target_date = request.args.get('date')
        target_source = request.args.get('source')
        
        if target_date and not re.match(r'^\d{4}-\d{2}-\d{2}$', target_date):
            return jsonify({
                'success': False,
                'error': f'Invalid date format: {target_date}. Expected YYYY-MM-DD'
            }), 400

        record = get_latest_record_for_symbol(symbol, target_date)
        resolved_date = target_date
        fallback_used = False

        if not record and target_date:
            # 指定日期未找到，回退到最新记录
            record = get_latest_record_for_symbol(symbol, None)
            fallback_used = record is not None
            resolved_date = record.get('timestamp', '')[:10] if record else None

        if not record:
            all_records = load_records()
            symbol_dates = sorted(set(
                r.get('timestamp', '')[:10]
                for r in all_records
                if r.get('symbol', '').upper() == symbol
            ), reverse=True)
            return jsonify({
                'success': False,
                'error': f'Symbol {symbol} not found',
                'available_dates': symbol_dates if symbol_dates else None,
            }), 404

        bridge_data = record.get('bridge')
        if not bridge_data:
            bridge_source = {}
            raw = record.get('raw_data') or {}
            try:
                cleaned = clean_record(raw)
                normalized = normalize_dataset([cleaned])[0]
                bridge_source.update(normalized)
            except Exception as e:
                print(f"⚠️ Bridge rebuild fallback without normalization: {e}")
                bridge_source.update(raw)

            bridge_source.update(record)

            try:
                bridge_data = build_bridge_snapshot(bridge_source, cfg_ref).to_dict()
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': f'Failed to build bridge snapshot: {e}'
                }), 500

        # 补充便捷字段 (与 micro 层预期一致)
        market_state = bridge_data.get('market_state', {}) if isinstance(bridge_data, dict) else {}
        event_state = bridge_data.get('event_state', {}) if isinstance(bridge_data, dict) else {}
        bridge_data.setdefault('ivr', market_state.get('ivr'))
        bridge_data.setdefault('iv30', market_state.get('iv30'))
        bridge_data.setdefault('hv20', market_state.get('hv20'))
        bridge_data.setdefault('earning_date', event_state.get('earnings_date'))

        response_payload = {
            'success': True,
            'symbol': symbol,
            'date': resolved_date or record.get('timestamp', '')[:10],
            'bridge': bridge_data,
            'requested_date': target_date,
            'fallback_used': fallback_used
        }
        try:
            print(f"{target_source}--{symbol} >> Bridge Response <<]" + json.dumps(response_payload, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[BridgeAPI] Failed to print response: {e}")
        return jsonify(response_payload)
