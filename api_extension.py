"""
API 扩展模块 - v2.3.3 VIX增强版
为 swing 项目提供市场参数查询接口
"""

from flask import jsonify, request
from datetime import datetime
import json
import os
import re
from typing import Optional, Dict, Any


DATA_FILE = 'analysis_records.json'


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


def load_records() -> list:
    """加载分析记录"""
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return []
            data = json.loads(content)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, Exception) as e:
        print(f"警告: 读取 {DATA_FILE} 失败: {e}")
        return []


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
    records = load_records()
    symbol_upper = symbol.upper()
    
    # 筛选该 symbol 的所有记录
    symbol_records = [
        r for r in records 
        if r.get('symbol', '').upper() == symbol_upper
    ]
    
    if not symbol_records:
        return []
    
    # 按日期分组（每天只保留最新记录）
    from collections import defaultdict
    records_by_date = defaultdict(list)
    
    for r in symbol_records:
        timestamp = r.get('timestamp', '')
        if not timestamp:
            continue
        
        date_str = timestamp.split(' ')[0]  # 提取日期部分
        records_by_date[date_str].append(r)
    
    # 每天取最新记录
    daily_latest = {}
    for date_str, day_records in records_by_date.items():
        day_records.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        daily_latest[date_str] = day_records[0]
    
    # 按日期降序排序
    sorted_dates = sorted(daily_latest.keys(), reverse=True)
    
    # 如果指定了日期，从该日期开始查找
    if target_date:
        try:
            target_index = sorted_dates.index(target_date)
            sorted_dates = sorted_dates[target_index:]
        except ValueError:
            return []  # 目标日期不存在
    
    # 提取最近 N 个交易日的 IV30
    iv30_values = []
    for date_str in sorted_dates[:days]:
        record = daily_latest[date_str]
        
        # 优先从顶层读取（v2.3.3+），回退到 raw_data
        iv30 = record.get('iv30') or record.get('raw_data', {}).get('IV30')
        
        if iv30 is not None:
            try:
                iv30_values.append(float(iv30))
            except (ValueError, TypeError):
                continue
    
    # 需要恰好 N 个数据点
    if len(iv30_values) != days:
        return []
    
    # 返回按时间升序的列表 [T-2, T-1, T]
    return list(reversed(iv30_values))


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
    iv_history = get_historical_iv30(symbol, target_date, days=3)
    
    if len(iv_history) < 3:
        return "Insufficient_Data"
    
    iv_t_minus_2, iv_t_minus_1, iv_t = iv_history
    
    # 计算变化百分比
    def pct_change(old, new):
        if old == 0:
            return 0.0
        return ((new - old) / old) * 100.0
    
    chg_1 = pct_change(iv_t_minus_2, iv_t_minus_1)  # T-2 到 T-1
    chg_2 = pct_change(iv_t_minus_1, iv_t)          # T-1 到 T
    
    # 判断趋势
    # Rising: 连续两日上升
    if chg_1 > threshold and chg_2 > threshold:
        return "Rising"
    
    # Falling: 连续两日下降
    if chg_1 < -threshold and chg_2 < -threshold:
        return "Falling"
    
    # Flat: 其他情况（包括方向不连续或变动幅度小）
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
    records = load_records()
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


def register_swing_api(app):
    """
    注册 swing 项目需要的 API 路由
    
    Args:
        app: Flask 应用实例
    """
    
    @app.route('/api/swing/params/<symbol>', methods=['GET'])
    def get_swing_params(symbol: str):
        """
        获取 swing 项目所需的市场参数 (v2.3.3 VIX增强版)
        
        请求示例:
            GET /api/swing/params/NVDA
            GET /api/swing/params/NVDA?date=2025-12-06
            GET /api/swing/params/NVDA?vix=18.5  (可选覆盖)
            
        查询参数:
            date: 目标日期，格式 YYYY-MM-DD (可选，默认返回最新记录)
            vix: VIX 覆盖值 (可选，用于手动指定 VIX)
            
        响应示例:
            {
                "success": true,
                "symbol": "NVDA",
                "date": "2025-12-06",
                "vix": 18.5,
                "params": {
                    "ivr": 63,
                    "iv30": 47.2,
                    "hv20": 40,
                    "earning_date": "2025-11-19",
                    "iv_path": "Rising"
                },
                "_source": { ... }
            }
            
        iv_path 可能的值:
            - "Rising": IV30 连续两日上升
            - "Falling": IV30 连续两日下降
            - "Flat": 变动幅度小于阈值或方向不连续
            - "Insufficient_Data": 历史数据不足
        """
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
        
        # 提取参数
        params = extract_swing_params(record)
        
        # 🟢 支持通过 query string 覆盖 VIX (可选)
        vix_override = request.args.get('vix', type=float)
        if vix_override is not None:
            params['vix'] = vix_override
        
        # 检查必要参数
        missing = []
        for key in ['vix', 'ivr', 'iv30', 'hv20']:  # 🟢 VIX 现在是必要字段
            if params.get(key) is None:
                missing.append(key)
        
        if missing:
            return jsonify({
                'success': False,
                'error': f'Missing required fields: {missing}',
                'partial_params': params
            }), 400
        
        # 🟢 返回结构: vix 与 symbol 同级
        return jsonify({
            'success': True,
            'symbol': symbol,
            'date': target_date or record.get('timestamp', '')[:10],
            'vix': params['vix'],  # 🟢 提升到顶层
            'params': {
                'ivr': params['ivr'],
                'iv30': params['iv30'],
                'hv20': params['hv20'],
                'earning_date': params['earning_date'],
                'iv_path': params['iv_path']  # 🟢 新增字段
            },
            '_source': params['_source']
        })
    
    @app.route('/api/swing/params/batch', methods=['POST'])
    def get_swing_params_batch():
        """
        批量获取多个 symbol 的市场参数 (v2.3.3 VIX增强版)
        
        请求示例:
            POST /api/swing/params/batch
            {
                "symbols": ["NVDA", "TSLA", "AAPL"],
                "date": "2025-12-06",  // 可选
                "vix": 18.5            // 可选覆盖
            }
            
        响应示例:
            {
                "success": true,
                "date": "2025-12-06",
                "results": {
                    "NVDA": {
                        "vix": 18.5,
                        "params": {
                            "ivr": 63,
                            "iv30": 47.2,
                            "hv20": 40,
                            "earning_date": "2025-11-19"
                        }
                    },
                    "TSLA": {
                        "vix": 18.5,
                        "params": { ... }
                    }
                },
                "errors": {
                    "AAPL": "Symbol not found"
                }
            }
        """
        data = request.json or {}
        symbols = data.get('symbols', [])
        vix_override = data.get('vix')  # 🟢 支持批量覆盖 VIX
        target_date = data.get('date')
        
        if not symbols:
            return jsonify({
                'success': False,
                'error': 'No symbols provided'
            }), 400
        
        # 验证日期格式
        if target_date:
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', target_date):
                return jsonify({
                    'success': False,
                    'error': f'Invalid date format: {target_date}. Expected YYYY-MM-DD'
                }), 400
        
        results = {}
        errors = {}
        
        for symbol in symbols:
            symbol = symbol.upper()
            record = get_latest_record_for_symbol(symbol, target_date)
            
            if not record:
                error_msg = 'Symbol not found'
                if target_date:
                    error_msg += f' for date {target_date}'
                errors[symbol] = error_msg
                continue
            
            params = extract_swing_params(record)
            
            # 🟢 应用 VIX 覆盖
            if vix_override is not None:
                params['vix'] = vix_override
            
            # 检查必要参数
            if any(params.get(k) is None for k in ['vix', 'ivr', 'iv30', 'hv20']):
                errors[symbol] = 'Missing required fields'
                continue
            
            # 🟢 每个 symbol 的数据结构: vix 独立字段
            results[symbol] = {
                'vix': params['vix'],  # 🟢 与 symbol 同级
                'params': {
                    'ivr': params['ivr'],
                    'iv30': params['iv30'],
                    'hv20': params['hv20'],
                    'earning_date': params['earning_date'],
                    'iv_path': params['iv_path']  # 🟢 新增字段
                }
            }
        
        return jsonify({
            'success': True,
            'date': target_date,
            'results': results,
            'errors': errors if errors else None
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
        records = load_records()
        
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
        records = load_records()
        
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