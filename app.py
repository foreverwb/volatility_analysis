"""

Flask 主应用入口

"""
from flask import Flask, render_template, request, jsonify, send_from_directory, Response, stream_with_context
import json
import os
from typing import List, Dict, Any
from datetime import datetime, timedelta, time
from collections import defaultdict
from queue import Queue, Empty
import threading
from core.market_data import get_vix_info, clear_vix_cache

from core import (
    DEFAULT_CFG,
    calculate_analysis
)
from core.oi_fetcher import batch_fetch_oi, auto_tune_workers, estimate_fetch_time
from core.futu_option_iv import fetch_iv_term_structure
from core.background_tasks import (
    get_task_manager, 
    create_iv_fetch_task,
    execute_iv_fetch_task,
    TaskStatus
)
app = Flask(__name__)

DATA_FILE = 'analysis_records.json'

# =========================
# 时间判断工具函数
# =========================
def should_skip_oi_fetch() -> bool:
    """
    判断当前时间是否应跳过 OI 数据获取
    
    规则: 北京时间 18:00 之前跳过
    
    Returns:
        True if 当前时间 < 18:00 CST
    """
    import pytz
    
    beijing_tz = pytz.timezone('Asia/Shanghai')
    now_beijing = datetime.now(beijing_tz)
    
    cutoff_time = time(18, 0, 0)
    
    return now_beijing.time() < cutoff_time


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
    
    Args:
        symbol: 标的代码（大小写不敏感）
        n_days: 需要的历史天数（默认 5 天）
        as_of_date: 截止日期（格式: YYYY-MM-DD），默认为今天
        
    Returns:
        历史评分列表（按时间倒序，最新在前）
    """
    records = load_data()
    symbol_upper = symbol.upper()
    
    symbol_records = [
        r for r in records 
        if r.get('symbol', '').upper() == symbol_upper
    ]
    
    if not symbol_records:
        return []
    
    if as_of_date is None:
        as_of = datetime.now()
    else:
        try:
            as_of = datetime.strptime(as_of_date, '%Y-%m-%d')
        except ValueError:
            as_of = datetime.now()
    
    records_by_date = defaultdict(list)
    
    for r in symbol_records:
        timestamp = r.get('timestamp', '')
        if not timestamp:
            continue
        
        try:
            date_str = timestamp.split(' ')[0]
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            
            if dt <= as_of:
                records_by_date[date_str].append(r)
        except (ValueError, IndexError):
            continue
    
    daily_latest = {}
    for date_str, day_records in records_by_date.items():
        day_records.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        daily_latest[date_str] = day_records[0]
    
    sorted_dates = sorted(daily_latest.keys(), reverse=True)
    
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
    POST /api/analyze?ignore_earnings=false
    Body: { "records": [...] }
    
    ✨ 优化: 先获取 OI（快）→ 再获取 IV（慢）
    """
    try:
        ignore_earnings = request.args.get('ignore_earnings', 'false').lower() == 'true'
        records = request.json.get('records', [])
        
        if not isinstance(records, list):
            return jsonify({'error': '数据格式错误,需要是列表'}), 400
        
        if len(records) == 0:
            return jsonify({'error': '数据列表不能为空'}), 400
        
        skip_oi = should_skip_oi_fetch()
        
        symbols = list(set(r.get('symbol', '') for r in records if r.get('symbol')))
        num_symbols = len(symbols)
        
        # ========== ✨ 优化：先快后慢 ==========
        
        # 1️⃣ 先获取 OI 数据（快，且用户最关心）
        oi_data = {}
        
        if skip_oi:
            print(f"\n⏰ 当前时间早于 18:00 CST，跳过 OI 数据获取")
        else:
            auto_tuned_workers = auto_tune_workers(num_symbols)
            estimated_time = estimate_fetch_time(num_symbols, auto_tuned_workers)
            
            print(f"\n{'='*60}")
            print(f"📊 OI 数据获取配置:")
            print(f"   - 标的数量: {num_symbols}")
            print(f"   - 并发线程: {auto_tuned_workers}")
            print(f"   - 预计耗时: {estimated_time:.1f}s")
            print(f"{'='*60}\n")
            
            oi_data = batch_fetch_oi(symbols, max_workers=auto_tuned_workers)
        
        # 2️⃣ 再获取 IV 数据（慢，但可以并发）
        print(f"\n{'='*60}")
        print(f"📈 IV 数据获取配置:")
        print(f"   - 标的数量: {num_symbols}")
        print(f"   - 并发线程: 5 (Futu 限流保护)")
        print(f"{'='*60}\n")
        
        iv_term_data = fetch_iv_term_structure(
            symbols,
            max_workers=5  # Futu API 限流，建议不超过5
        )
        
        # 3️⃣ 分析数据
        results = []
        errors = []
        
        for i, record in enumerate(records):
            try:
                symbol = record.get('symbol', '')
                symbol_upper = symbol.upper()

                # 注入 IV 数据
                if symbol_upper in iv_term_data:
                    iv_values = iv_term_data[symbol_upper]
                    for key, value in iv_values.items():
                        if value is not None:
                            record[key] = value
                    if iv_values.get("IV_90D") is not None:
                        record["IV90"] = iv_values["IV_90D"]
                
                # 注入 OI 数据
                if not skip_oi and symbol in oi_data:
                    current_oi, delta_oi = oi_data[symbol]
                    if delta_oi is not None:
                        record['ΔOI_1D'] = delta_oi
                        
                history_scores = get_history_scores(symbol)
                
                analysis = calculate_analysis(
                    record,
                    ignore_earnings=ignore_earnings,
                    history_scores=history_scores,
                    skip_oi=skip_oi
                )
                results.append(analysis)
            except Exception as e:
                error_msg = f"标的 {record.get('symbol', f'#{i+1}')} 分析失败: {str(e)}"
                errors.append(error_msg)
                print(f"错误: {error_msg}")
        
        # 4️⃣ 保存数据
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
        
        if skip_oi:
            message += ' (已跳过 OI 数据获取)'
        
        return jsonify({
            'message': message,
            'results': results,
            'errors': errors if errors else None,
            'oi_stats': {
                'total': num_symbols,
                'success': sum(1 for s in symbols if oi_data.get(s, (None, None))[0] is not None),
                'with_delta': sum(1 for s in symbols if oi_data.get(s, (None, None))[1] is not None),
                'skipped': skip_oi
            }
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

@app.route('/api/analyze/stream', methods=['POST'])
def analyze_stream():
    """
    流式分析接口 - v2.6.0 异步优化版
    
    ✨ 优化策略：
    1. 优先获取 ΔOI（快，~30秒）
    2. 使用现有 IV 数据进行初步分析
    3. 立即返回结果给用户
    4. 后台启动 IV 获取任务
    5. IV 完成后推送更新通知
    
    POST /api/analyze/stream?ignore_earnings=false&async_iv=true
    Body: { "records": [...] }
    """
    def generate():
        try:
            ignore_earnings = request.args.get('ignore_earnings', 'false').lower() == 'true'
            async_iv = request.args.get('async_iv', 'true').lower() == 'true'  # ✨ 新增参数
            records = request.json.get('records', [])
            
            if not isinstance(records, list) or len(records) == 0:
                yield f"data: {json.dumps({'type': 'error', 'error': '数据格式错误'})}\n\n"
                return
            
            symbols = list(set(r.get('symbol', '') for r in records if r.get('symbol')))
            num_symbols = len(symbols)
            
            yield f"data: {json.dumps({'type': 'init', 'total': num_symbols, 'async_iv': async_iv})}\n\n"
            
            skip_oi = should_skip_oi_fetch()
            
            # ========== 1️⃣ 优先获取 OI 数据（快） ==========
            oi_data = {}
            
            if skip_oi:
                info_msg = {'type': 'info', 'message': '当前时间早于 18:00 CST，跳过 OI 数据获取'}
                yield f"data: {json.dumps(info_msg)}\n\n"
                yield f"data: {json.dumps({'type': 'oi_complete', 'success': 0, 'skipped': True})}\n\n"
            else:
                auto_tuned_workers = auto_tune_workers(num_symbols)
                estimated_time = estimate_fetch_time(num_symbols, auto_tuned_workers)
                
                yield f"data: {json.dumps({'type': 'oi_start', 'estimated_time': estimated_time})}\n\n"
                
                progress_queue = Queue()
                fetch_error = None
                
                def fetch_oi_task():
                    nonlocal oi_data, fetch_error
                    try:
                        oi_data = batch_fetch_oi(
                            symbols, 
                            max_workers=auto_tuned_workers,
                            progress_queue=progress_queue
                        )
                    except Exception as e:
                        fetch_error = str(e)
                        progress_queue.put({'type': 'error', 'error': str(e)})
                
                fetch_thread = threading.Thread(target=fetch_oi_task)
                fetch_thread.start()
                
                oi_fetch_complete = False
                
                while not oi_fetch_complete or not progress_queue.empty():
                    try:
                        progress_data = progress_queue.get(timeout=0.5)
                        
                        if progress_data.get('type') == 'complete':
                            oi_fetch_complete = True
                            complete_data = {
                                'type': 'oi_complete', 
                                'success': sum(1 for s in symbols if oi_data.get(s, (None, None))[0] is not None),
                                'skipped': False
                            }
                            yield f"data: {json.dumps(complete_data)}\n\n"
                            break
                        
                        elif progress_data.get('type') == 'error':
                            yield f"data: {json.dumps(progress_data)}\n\n"
                            return
                        
                        else:
                            progress_msg = {
                                'type': 'oi_progress',
                                'completed': progress_data['completed'],
                                'total': progress_data['total'],
                                'symbol': progress_data['symbol']
                            }
                            yield f"data: {json.dumps(progress_msg)}\n\n"
                    
                    except Empty:
                        if not fetch_thread.is_alive():
                            oi_fetch_complete = True
                            break
                        continue
                
                fetch_thread.join(timeout=5)
                
                if fetch_error:
                    yield f"data: {json.dumps({'type': 'error', 'error': fetch_error})}\n\n"
                    return
            
            # ========== 2️⃣ 使用现有 IV 数据进行初步分析 ==========
            yield f"data: {json.dumps({'type': 'info', 'message': '使用现有 IV 数据进行分析...'})}\n\n"
            
            # 注意：不主动获取新 IV，只用 records 中已有的
            results = []
            errors = []
            
            for i, record in enumerate(records):
                try:
                    symbol = record.get('symbol', '')
                    
                    # 注入 OI 数据
                    if not skip_oi and symbol in oi_data:
                        current_oi, delta_oi = oi_data[symbol]
                        if delta_oi is not None:
                            record['ΔOI_1D'] = delta_oi
                    
                    history_scores = get_history_scores(symbol)
                    
                    analysis = calculate_analysis(
                        record,
                        ignore_earnings=ignore_earnings,
                        history_scores=history_scores,
                        skip_oi=skip_oi
                    )
                    results.append(analysis)
                    
                    if i % 5 == 0 or i == len(records) - 1:
                        yield f"data: {json.dumps({
                            'type': 'analyze_progress', 
                            'completed': i + 1, 
                            'total': len(records)
                        })}\n\n"
                    
                except Exception as e:
                    error_msg = f"标的 {record.get('symbol', f'#{i+1}')} 分析失败: {str(e)}"
                    errors.append(error_msg)
            
            # ========== 3️⃣ 保存初步结果 ==========
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
            
            message = f'✓ 初步分析完成 {len(results)} 个标的'
            if errors:
                message += f', {len(errors)} 个失败'
            if skip_oi:
                message += ' (已跳过 OI 数据获取)'
            
            # ========== 4️⃣ 返回初步结果 ==========
            initial_result = {
                'type': 'analysis_complete',
                'message': message,
                'results': results,
                'errors': errors if errors else None,
                'oi_stats': {
                    'total': num_symbols,
                    'success': sum(1 for s in symbols if oi_data.get(s, (None, None))[0] is not None),
                    'with_delta': sum(1 for s in symbols if oi_data.get(s, (None, None))[1] is not None),
                    'skipped': skip_oi
                }
            }
            
            yield f"data: {json.dumps(initial_result)}\n\n"
            
            # ========== 5️⃣ 启动后台 IV 获取任务 ==========
            if async_iv:
                # 获取需要更新 IV 的 symbols（IV 数据缺失或过期）
                symbols_need_iv = []
                for record in records:
                    symbol = record.get('symbol', '')
                    iv30 = record.get('IV30') or record.get('IV_30D')
                    if iv30 is None or iv30 == 0:
                        symbols_need_iv.append(symbol)
                
                if symbols_need_iv:
                    # 创建后台任务
                    task_manager = get_task_manager()
                    
                    def on_iv_complete(task_id, iv_results):
                        """IV 获取完成后的回调"""
                        print(f"\n🎉 IV 任务完成: {task_id}")
                        print(f"   成功获取: {sum(1 for data in iv_results.values() if data.get('IV_30D'))} symbols")
                        
                        # 重新分析并更新数据
                        updated_records = []
                        for record in records:
                            symbol = record.get('symbol', '').upper()
                            if symbol in iv_results:
                                iv_data = iv_results[symbol]
                                for key, value in iv_data.items():
                                    if value is not None:
                                        record[key] = value
                            
                            try:
                                analysis = calculate_analysis(
                                    record,
                                    ignore_earnings=ignore_earnings,
                                    history_scores=get_history_scores(symbol),
                                    skip_oi=skip_oi
                                )
                                updated_records.append(analysis)
                            except Exception as e:
                                print(f"⚠ 重新分析失败 {symbol}: {e}")
                        
                        # 保存更新后的数据
                        if updated_records:
                            all_data = load_data()
                            new_records_map = {}
                            for r in updated_records:
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
                            
                            all_data = filtered_old_data + updated_records
                            save_data(all_data)
                    
                    task_id = create_iv_fetch_task(symbols_need_iv, on_complete=on_iv_complete)
                    
                    # 启动后台执行
                    execute_iv_fetch_task(task_id, symbols_need_iv)
                    
                    # 通知前端任务已创建
                    from core.futu_option_iv import FutuBatchController
                    controller = FutuBatchController()
                    batch_config = controller.calculate_batch_config(len(symbols_need_iv))
                    
                    yield f"data: {json.dumps({
                        'type': 'iv_task_created',
                        'task_id': task_id,
                        'symbols_count': len(symbols_need_iv),
                        'estimated_time': batch_config.estimated_time,
                        'message': f'后台获取 IV 数据中... (预计 {batch_config.estimated_time/60:.1f} 分钟)'
                    })}\n\n"
                else:
                    yield f"data: {json.dumps({
                        'type': 'info',
                        'message': '所有标的已有 IV 数据，无需后台更新'
                    })}\n\n"
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


# ========== 3. 新增任务状态查询接口 ==========

@app.route('/api/tasks/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """
    查询后台任务状态
    
    GET /api/tasks/{task_id}
    
    Returns:
        {
            "task_id": "...",
            "status": "running" | "completed" | "failed",
            "progress": 45,
            "completed_symbols": 15,
            "total_symbols": 32,
            "created_at": "...",
            "completed_at": "..."
        }
    """
    try:
        task_manager = get_task_manager()
        task = task_manager.get_task(task_id)
        
        if not task:
            return jsonify({'error': 'Task not found'}), 404
        
        return jsonify(task.to_dict())
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks', methods=['GET'])
def list_tasks():
    """
    列出所有任务
    
    GET /api/tasks?status=running
    """
    try:
        task_manager = get_task_manager()
        tasks = task_manager.get_all_tasks()
        
        # 过滤（可选）
        status_filter = request.args.get('status')
        if status_filter:
            tasks = [t for t in tasks if t.status.value == status_filter]
        
        return jsonify([t.to_dict() for t in tasks])
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ========== 4. 新增任务完成通知（SSE 推送） ==========

@app.route('/api/tasks/<task_id>/stream', methods=['GET'])
def stream_task_status(task_id):
    """
    实时推送任务状态（SSE）
    
    GET /api/tasks/{task_id}/stream
    
    前端可以订阅此接口，实时接收任务更新
    """
    def generate():
        task_manager = get_task_manager()
        task = task_manager.get_task(task_id)
        
        if not task:
            yield f"data: {json.dumps({'type': 'error', 'error': 'Task not found'})}\n\n"
            return
        
        # 发送初始状态
        yield f"data: {json.dumps({'type': 'status', 'data': task.to_dict()})}\n\n"
        
        # 轮询任务状态（每2秒检查一次）
        while task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            time.sleep(2)
            task = task_manager.get_task(task_id)
            
            if task:
                yield f"data: {json.dumps({'type': 'status', 'data': task.to_dict()})}\n\n"
        
        # 任务完成
        if task:
            yield f"data: {json.dumps({'type': 'complete', 'data': task.to_dict()})}\n\n"
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


@app.route('/api/vix/info', methods=['GET'])
def get_vix_cache_info():
    """获取 VIX 缓存状态"""
    try:
        info = get_vix_info()
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/vix/clear', methods=['POST'])
def clear_vix_cache_endpoint():
    """清除 VIX 缓存"""
    try:
        clear_vix_cache()
        return jsonify({'message': 'VIX cache cleared successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 注册 swing 项目的 API 扩展
from api_extension import register_swing_api
register_swing_api(app)


if __name__ == '__main__':
    print("\n" + "="*80)
    print("期权策略量化分析系统 v2.6.0 - 异步优化版")
    print("="*80)
    print("\n📡 API 端点:")
    print("   POST /api/analyze/stream      - 流式分析接口（异步IV）")
    print("   GET  /api/tasks/<task_id>     - 查询任务状态")
    print("   GET  /api/tasks               - 列出所有任务")
    print("   GET  /api/tasks/<task_id>/stream - 实时推送任务状态")
    print("   • ΔOI 优先获取（~30秒）")
    print("   • 立即返回初步分析结果")
    print("   • IV 数据后台异步更新（~2分钟）")
    print("   • 支持任务状态实时查询")
    print("\n⏰ 时间限制:")
    print("   • 18:00 CST 之前跳过 OI 数据获取")
    print("="*80 + "\n")
    
    # 清理旧任务
    task_manager = get_task_manager()
    task_manager.cleanup_old_tasks(max_age_hours=24)
    
    try:
        app.run(debug=True, host='0.0.0.0', port=8668)
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        import traceback
        traceback.print_exc()