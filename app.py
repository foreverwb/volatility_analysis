# app.py
from flask import Flask, render_template, request, jsonify, send_from_directory
from services.data_manager import DataManager
from services.oi_fetcher import OIFetcher
from services.meso_analysis import MesoEngine
# 注册 swing 项目的 API 扩展
from api_extension import register_swing_api


app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/api/analyze', methods=['POST'])
def analyze():
    try:
        input_records = request.json.get('records', [])
        if not input_records:
            return jsonify({'error': 'No records provided'}), 400

        # 1. 获取 Symbol 列表
        symbols = [r.get('symbol') for r in input_records if r.get('symbol')]
        
        # 2. 批量获取 OI (修复后的逻辑)
        oi_data_map = OIFetcher.fetch_batch_oi(symbols)
        
        # 3. 将 OI 数据注入原始记录
        enriched_records = []
        for rec in input_records:
            sym = rec.get('symbol')
            if sym in oi_data_map:
                oi_info = oi_data_map[sym]
                if oi_info.get('total', 0) > 0:
                    rec['OpenInterest'] = oi_info['total']
                    rec['CallOI'] = oi_info['call']
                    rec['PutOI'] = oi_info['put']
                    rec['_oi_source'] = 'yfinance_auto'
                else:
                    # 获取失败或为0，保持原样或标记警告
                    rec['_oi_error'] = oi_info.get('status')
            enriched_records.append(rec)

        # 4. 加载历史数据 (用于计算 ActiveOpenRatio)
        history_records = DataManager.load_records()
        history_map = DataManager.get_history_map(history_records)

        # 5. 执行 Meso 分析
        results = MesoEngine.analyze(enriched_records, history_map)

        # 6. 保存结果
        if results:
            new_data = history_records + results
            DataManager.save_records(new_data)

        # 7. 统计成功数
        success_oi = sum(1 for r in enriched_records if r.get('OpenInterest', 0) > 0)

        return jsonify({
            'message': 'Analysis Complete',
            'results': results,
            'oi_summary': {'fetched': success_oi, 'total': len(symbols)}
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/records', methods=['GET'])
def get_records():
    return jsonify(DataManager.load_records())

@app.route('/api/records/date/<date>', methods=['DELETE'])
def delete_records_by_date(date):
    """删除指定日期的所有记录"""
    try:
        # 1. 加载现有数据
        data = DataManager.load_records()
        original_count = len(data)
        
        # 2. 过滤掉该日期的数据 (字符串匹配 yyyy-mm-dd)
        new_data = [d for d in data if not d.get('timestamp', '').startswith(date)]
        
        # 3. 如果数量没变，说明没找到该日期
        if len(new_data) == original_count:
            return jsonify({'error': '未找到该日期的记录'}), 404
            
        # 4. 保存新数据
        DataManager.save_records(new_data)
        
        return jsonify({
            'success': True, 
            'message': f'成功删除 {original_count - len(new_data)} 条记录'
        })
        
    except Exception as e:
        print(f"删除失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/records/<timestamp>/<symbol>', methods=['DELETE'])
def delete_record(timestamp, symbol):
    data = DataManager.load_records()
    new_data = [d for d in data if not (d['timestamp'] == timestamp and d['symbol'] == symbol)]
    DataManager.save_records(new_data)
    return jsonify({'success': True})

@app.route('/api/dates', methods=['GET'])
def get_dates():
    data = DataManager.load_records()
    dates = sorted(list(set([d['timestamp'].split(' ')[0] for d in data])), reverse=True)
    return jsonify(dates)

register_swing_api(app)

if __name__ == '__main__':
    print("🚀 Meso System v2.2 (Refactored) Starting...")
    print("   OI Fetcher: Enhanced Mode (Option Chain Iteration)")
    app.run(debug=True, port=8668)