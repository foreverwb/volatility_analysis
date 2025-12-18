"""
API 扩展模块 - 为 swing 项目提供市场参数查询接口

使用方法：
    在 app.py 中导入并注册路由:
    from api_extension import register_swing_api
    register_swing_api(app)
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
    
    # 去除 AMC/BMO 标记
    t = earnings_str.strip()
    parts = t.split()
    if len(parts) >= 2 and parts[-1] in ("AMC", "BMO"):
        t = " ".join(parts[:-1])
    t = t.replace("  ", " ")
    
    # 尝试多种日期格式
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
        # 支持 YYYY-MM-DD 格式
        date_records = [
            r for r in symbol_records
            if r.get('timestamp', '').startswith(target_date)
        ]
        
        if not date_records:
            return None
        
        # 如果同一天有多条记录，取最新的
        date_records.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return date_records[0]
    
    # 未指定日期，按 timestamp 降序排序，取最新的一条
    symbol_records.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return symbol_records[0]


def extract_swing_params(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 va 分析记录中提取 swing/micro 系统需要的参数
    
    Args:
        record: va 的分析记录
        
    Returns:
        swing 兼容的参数字典，包含 Meso 层信号供 Micro 动态调整
    """
    raw_data = record.get('raw_data', {})
    derived_metrics = record.get('derived_metrics', {})
    
    # 提取基础参数
    ivr = raw_data.get('IVR')
    iv30 = raw_data.get('IV30')
    hv20 = raw_data.get('HV20')
    earnings_raw = raw_data.get('Earnings')
    
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
    
    # 解析期限结构比率 (格式可能是 "1.05 (倒挂/恐慌)" 或 "0.92 (陡峭/正常)")
    term_structure_raw = record.get('term_structure_ratio', 'N/A')
    term_structure_ratio = None
    if term_structure_raw and term_structure_raw != 'N/A':
        try:
            # 提取数字部分
            term_structure_ratio = float(term_structure_raw.split()[0])
        except:
            pass
    
    result = {
        'ivr': clean_number(ivr),
        'iv30': clean_number(iv30),
        'hv20': clean_number(hv20),
        'earning_date': parse_earnings_date_to_iso(earnings_raw),
        
        # === Meso 信号字段 (供 Micro 动态调整) ===
        '_source': {
            'symbol': record.get('symbol'),
            'timestamp': record.get('timestamp'),
            'quadrant': record.get('quadrant'),
            'confidence': record.get('confidence'),
            
            # 方向与波动分数
            'direction_score': record.get('direction_score', 0.0),
            'vol_score': record.get('vol_score', 0.0),
            'direction_bias': record.get('direction_bias', '中性'),
            'vol_bias': record.get('vol_bias', '中性'),
            
            # 关键状态标记
            'is_squeeze': record.get('is_squeeze', False),
            'is_index': record.get('is_index', False),
            
            # 市场环境指标
            'spot_vol_corr_score': record.get('spot_vol_corr_score', 0.0),
            'term_structure_ratio': term_structure_ratio,
            
            # 派生指标
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
        获取 swing 项目所需的市场参数
        
        请求示例:
            GET /api/swing/params/NVDA
            GET /api/swing/params/NVDA?vix=18.5
            GET /api/swing/params/NVDA?vix=18.5&date=2025-12-06
            
        查询参数:
            vix: VIX 指数（可选）
            date: 目标日期，格式 YYYY-MM-DD（可选，默认返回最新记录）
            
        响应示例:
            {
                "success": true,
                "symbol": "NVDA",
                "params": {
                    "vix": 18.5,        # 如果传入则使用传入值
                    "ivr": 63,
                    "iv30": 47.2,
                    "hv20": 40,
                    "earning_date": "2025-11-19"
                },
                "_source": {
                    "timestamp": "2025-12-06 14:31:46",
                    "quadrant": "中性/待观察"
                }
            }
        """
        symbol = symbol.upper()
        
        # 获取日期参数
        target_date = request.args.get('date')
        
        # 验证日期格式
        if target_date:
            import re
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
        
        # 检查 VIX 参数（可以通过 query string 传入）
        vix = request.args.get('vix', type=float)
        if vix is not None:
            params['vix'] = vix
        else:
            params['vix'] = None  # 标记需要用户提供
        
        # 检查必要参数
        missing = []
        for key in ['ivr', 'iv30', 'hv20']:
            if params.get(key) is None:
                missing.append(key)
        
        if missing:
            return jsonify({
                'success': False,
                'error': f'Missing required fields: {missing}',
                'partial_params': params
            }), 400
        
        return jsonify({
            'success': True,
            'symbol': symbol,
            'date': target_date or record.get('timestamp', '')[:10],
            'params': {
                'vix': params['vix'],
                'ivr': params['ivr'],
                'iv30': params['iv30'],
                'hv20': params['hv20'],
                'earning_date': params['earning_date']
            },
            '_source': params['_source'],
            '_note': 'VIX is market-level data, pass via ?vix=XX if not provided' if params['vix'] is None else None
        })
    
    @app.route('/api/swing/params/batch', methods=['POST'])
    def get_swing_params_batch():
        """
        批量获取多个 symbol 的市场参数
        
        请求示例:
            POST /api/swing/params/batch
            {
                "symbols": ["NVDA", "TSLA", "AAPL"],
                "vix": 18.5,
                "date": "2025-12-06"  // 可选，指定日期
            }
            
        响应示例:
            {
                "success": true,
                "vix": 18.5,
                "date": "2025-12-06",
                "results": {
                    "NVDA": { "ivr": 63, "iv30": 47.2, ... },
                    "TSLA": { "ivr": 35, "iv30": 55.7, ... }
                },
                "errors": {
                    "AAPL": "Symbol not found"
                }
            }
        """
        data = request.json or {}
        symbols = data.get('symbols', [])
        vix = data.get('vix')
        target_date = data.get('date')
        
        if not symbols:
            return jsonify({
                'success': False,
                'error': 'No symbols provided'
            }), 400
        
        # 验证日期格式
        if target_date:
            import re
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
            
            # 检查必要参数
            if any(params.get(k) is None for k in ['ivr', 'iv30', 'hv20']):
                errors[symbol] = 'Missing required fields'
                continue
            
            results[symbol] = {
                'vix': vix,
                'ivr': params['ivr'],
                'iv30': params['iv30'],
                'hv20': params['hv20'],
                'earning_date': params['earning_date']
            }
        
        return jsonify({
            'success': True,
            'vix': vix,
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