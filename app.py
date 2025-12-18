"""
期权策略量化分析系统 v2.3.2
Flask 主应用入口

修复内容：
1. 移除循环导入问题
2. 修正历史评分获取函数的位置
3. 确保所有依赖正确导入
"""
from flask import Flask, render_template, request, jsonify, send_from_directory
import json
import os
from typing import List, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict

from core import (
    DEFAULT_CFG,
    calculate_analysis
)

app = Flask(__name__)

DATA_FILE = 'analysis_records.json'

# =========================
# 数据持久化
# =========================
def load_data() -> List[Dict[str, Any]]:
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


def save_data(data: List[Dict[str, Any]]):
    """保存分析记录"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_history_scores(symbol: str, n_days: int = 5, as_of_date: str = None) -> List[float]:
    """
    获取指定标的的历史方向评分（用于跨期一致性计算）
    
    v2.3.2 修复版本：
    - 从"最近 N 条记录"改为"最近 N 个交易日"
    - 每天只取最新的一条记录
    - 增加日期有效性验证
    
    Args:
        symbol: 标的代码（大小写不敏感）
        n_days: 需要的历史天数（默认 5 天）
        as_of_date: 截止日期（格式: YYYY-MM-DD），默认为今天
        
    Returns:
        历史评分列表（按时间倒序，最新在前）
    """
    records = load_data()
    symbol_upper = symbol.upper()
    
    # 1. 筛选该 symbol 的所有记录
    symbol_records = [
        r for r in records 
        if r.get('symbol', '').upper() == symbol_upper
    ]
    
    if not symbol_records:
        return []
    
    # 2. 确定截止日期
    if as_of_date is None:
        as_of = datetime.now()
    else:
        try:
            as_of = datetime.strptime(as_of_date, '%Y-%m-%d')
        except ValueError:
            as_of = datetime.now()
    
    # 3. 按日期分组（每天只保留最新的一条）
    records_by_date = defaultdict(list)
    
    for r in symbol_records:
        timestamp = r.get('timestamp', '')
        if not timestamp:
            continue
        
        try:
            # 提取日期部分 (YYYY-MM-DD)
            date_str = timestamp.split(' ')[0]
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            
            # 只考虑截止日期及之前的记录
            if dt <= as_of:
                records_by_date[date_str].append(r)
        except (ValueError, IndexError):
            continue
    
    # 4. 每天只保留最新的记录（按完整 timestamp 排序）
    daily_latest = {}
    for date_str, day_records in records_by_date.items():
        # 按时间戳降序排序，取第一条（最新）
        day_records.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        daily_latest[date_str] = day_records[0]
    
    # 5. 按日期降序排序，取最近 n_days
    sorted_dates = sorted(daily_latest.keys(), reverse=True)
    
    # 6. 提取方向评分（最多 n_days 条）
    history_scores = []
    for date_str in sorted_dates[:n_days]:
        record = daily_latest[date_str]
        score = record.get('direction_score', 0)
        history_scores.append(float(score))
    
    return history_scores


# =========================
# Flask 路由
# =========================
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/analyze', methods=['POST'])
def analyze():
    """
    分析数据接口
    
    POST /api/analyze?ignore_earnings=false
    Body: { "records": [...] }
    """
    try:
        ignore_earnings = request.args.get('ignore_earnings', 'false').lower() == 'true'
        records = request.json.get('records', [])
        
        if not isinstance(records, list):
            return jsonify({'error': '数据格式错误,需要是列表'}), 400
        
        if len(records) == 0:
            return jsonify({'error': '数据列表不能为空'}), 400
        
        results = []
        errors = []
        
        for i, record in enumerate(records):
            try:
                symbol = record.get('symbol', '')
                # 获取历史评分用于跨期一致性计算
                history_scores = get_history_scores(symbol)
                
                analysis = calculate_analysis(
                    record,
                    ignore_earnings=ignore_earnings,
                    history_scores=history_scores
                )
                results.append(analysis)
            except Exception as e:
                error_msg = f"标的 {record.get('symbol', f'#{i+1}')} 分析失败: {str(e)}"
                errors.append(error_msg)
                print(f"错误: {error_msg}")
        
        if results:
            all_data = load_data()
            new_records_map = {}
            for r in results:
                date = r['timestamp'].split(' ')[0]
                symbol = r['symbol']
                key = (date, symbol)
                new_records_map[key] = r
            
            filtered_old_data = []
            for old_record in all_data:
                date = old_record.get('timestamp', '').split(' ')[0]
                symbol = old_record.get('symbol', '')
                key = (date, symbol)
                if key not in new_records_map:
                    filtered_old_data.append(old_record)
            
            all_data = filtered_old_data + results
            save_data(all_data)
        
        message = f'成功分析 {len(results)} 个标的'
        if errors:
            message += f',{len(errors)} 个失败'
        
        return jsonify({
            'message': message,
            'results': results,
            'errors': errors if errors else None
        }), 201
    
    except Exception as e:
        print(f"分析失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/records', methods=['GET'])
def get_records():
    """获取分析记录"""
    try:
        data = load_data()
        if not isinstance(data, list):
            return jsonify([])
        
        date_filter = request.args.get('date')
        quadrant_filter = request.args.get('quadrant')
        confidence_filter = request.args.get('confidence')
        
        filtered_data = data
        
        if date_filter:
            filtered_data = [d for d in filtered_data if d.get('timestamp', '').startswith(date_filter)]
        
        if quadrant_filter and quadrant_filter != 'all':
            filtered_data = [d for d in filtered_data if d.get('quadrant') == quadrant_filter]
        
        if confidence_filter and confidence_filter != 'all':
            filtered_data = [d for d in filtered_data if d.get('confidence') == confidence_filter]
        
        return jsonify(filtered_data)
    
    except Exception as e:
        return jsonify([])


@app.route('/api/records/<timestamp>/<symbol>', methods=['DELETE'])
def delete_record(timestamp, symbol):
    """删除单条记录"""
    try:
        data = load_data()
        original_length = len(data)
        data = [d for d in data if not (d['timestamp'] == timestamp and d['symbol'] == symbol)]
        if len(data) == original_length:
            return jsonify({'error': '未找到该记录'}), 404
        save_data(data)
        return jsonify({'message': '删除成功'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/records/date/<date>', methods=['DELETE'])
def delete_records_by_date(date):
    """按日期删除记录"""
    try:
        data = load_data()
        original_length = len(data)
        data = [d for d in data if not d.get('timestamp', '').startswith(date)]
        deleted_count = original_length - len(data)
        if deleted_count == 0:
            return jsonify({'error': '未找到该日期的记录'}), 404
        save_data(data)
        return jsonify({'message': f'成功删除 {deleted_count} 条记录'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/records/all', methods=['DELETE'])
def delete_all_records():
    """删除所有记录"""
    try:
        save_data([])
        return jsonify({'message': '所有数据已删除'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/dates', methods=['GET'])
def get_dates():
    """获取所有日期"""
    try:
        data = load_data()
        dates = sorted(set(d.get('timestamp', '')[:10] for d in data if d.get('timestamp')), reverse=True)
        return jsonify(dates)
    except Exception as e:
        return jsonify([]), 200


@app.route('/api/config', methods=['GET'])
def get_config():
    """获取当前配置"""
    return jsonify(DEFAULT_CFG)


@app.route('/api/config', methods=['POST'])
def update_config():
    """更新配置 (运行时)"""
    try:
        new_cfg = request.json
        DEFAULT_CFG.update(new_cfg)
        return jsonify({'message': '配置更新成功', 'config': DEFAULT_CFG})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# 注册 swing 项目的 API 扩展
from api_extension import register_swing_api
register_swing_api(app)


if __name__ == '__main__':
    print("\n📡 Swing API 端点已启用:")
    print("   GET  /api/swing/params/<symbol>?vix=XX")
    print("   POST /api/swing/params/batch")
    print("   GET  /api/swing/symbols")
    
    try:
        app.run(debug=True, host='0.0.0.0', port=8668)
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        import traceback
        traceback.print_exc()