"""
期权策略量化分析系统 v2.3.2
Flask 主应用入口

修复内容：
1. 移除循环导入问题
2. 修正历史评分获取函数的位置
3. 确保所有依赖正确导入
4. 去除 18:00 时间限制，默认获取 OI 数据
"""
from flask import Flask, render_template, request, jsonify, send_from_directory, Response, stream_with_context
import json
import os
from typing import List, Dict, Any
from datetime import datetime
from collections import defaultdict
from core.market_data import get_vix_info, clear_vix_cache, get_vix_with_fallback
from storage.sqlite_repo import get_records_repo

from core import (
    DEFAULT_CFG,
    calculate_analysis,
    compute_linear_slope,
    map_slope_trend,
)
from core.futu_iv import fetch_iv_terms, estimate_iv_fetch_time
from core.futu_oi import batch_compute_delta_oi
app = Flask(__name__)
records_repo = get_records_repo()

# =========================
# 时间判断工具函数（已禁用时间限制）
# =========================
def should_skip_oi_fetch() -> bool:
    """
    始终返回 False，表示不跳过 OI 数据获取。
    """
    return False


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_score(record: Dict[str, Any], key: str, default: float = 0.0) -> float:
    """兼容历史 payload: 优先 analysis 子对象，其次回退到顶层字段。"""
    if not isinstance(record, dict):
        return default

    analysis_payload = record.get('analysis', {})
    if isinstance(analysis_payload, dict):
        sub = analysis_payload.get(key)
        if sub is not None:
            return _safe_float(sub, default)

    top = record.get(key)
    if top is not None:
        return _safe_float(top, default)

    return default


def _count_valid_points(scores: List[float], n_days: int) -> int:
    if not scores or n_days <= 0:
        return 0
    valid = 0
    for score in scores:
        if score is None:
            continue
        try:
            float(score)
            valid += 1
        except (TypeError, ValueError):
            continue
        if valid >= n_days:
            break
    return valid


def _needs_trend_backfill(record: Dict[str, Any]) -> bool:
    """是否需要对历史记录补算趋势字段（兼容旧 payload）。"""
    if not isinstance(record, dict):
        return False
    return (
        record.get("dir_slope_nd") is None
        or record.get("dir_trend_label") in (None, "")
        or record.get("trend_days_used") is None
    )


def enrich_records_with_trend_fields(records: List[Dict[str, Any]], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按 symbol+时间顺序补算缺失趋势字段，避免历史记录前端展示为 0。"""
    trend_days = int(cfg.get("trend_days", 5))

    # 保持原顺序，先构建索引
    indexed = list(enumerate(records))
    by_symbol: Dict[str, List] = defaultdict(list)
    for idx, rec in indexed:
        symbol = (rec.get("symbol") or "").upper()
        by_symbol[symbol].append((idx, rec))

    out = list(records)
    for _symbol, items in by_symbol.items():
        # 升序遍历，当前记录只使用“之前交易日”历史，贴近在线分析语义
        items.sort(key=lambda x: x[1].get("timestamp", ""))
        prior_scores: List[float] = []

        for idx, rec in items:
            dir_score_now = _extract_score(rec, "direction_score", 0.0)

            if _needs_trend_backfill(rec):
                history_recent_first = list(reversed(prior_scores))
                slope = compute_linear_slope(history_recent_first, trend_days)
                out[idx]["dir_slope_nd"] = round(slope, 3)
                out[idx]["dir_trend_label"] = map_slope_trend(slope, cfg)
                out[idx]["trend_days_used"] = _count_valid_points(history_recent_first, trend_days)

            prior_scores.append(dir_score_now)

    return out


def get_history_scores(symbol: str, days: int = 5, as_of_date: str = None) -> List[float]:
    """
    获取指定标的的历史方向评分（用于跨期一致性计算）
    
    v2.3.2 修复版本：
    - 从"最近 N 条记录"改为"最近 N 个交易日"
    - 每天只取最新的一条记录
    - 增加日期有效性验证
    
    Args:
        symbol: 标的代码（大小写不敏感）
        days: 需要的历史天数（默认 5 天）
        as_of_date: 截止日期（格式: YYYY-MM-DD），默认为今天
        
    Returns:
        历史评分列表（按时间倒序，最新在前）
    """
    records = records_repo.list_records_by_symbol(symbol)
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
    
    # 5. 按日期降序排序，取最近 days
    sorted_dates = sorted(daily_latest.keys(), reverse=True)

    # 6. 提取方向评分（最多 days 条）
    history_scores = []
    for date_str in sorted_dates[:days]:
        record = daily_latest[date_str]
        score = _extract_score(record, 'direction_score', 0.0)
        history_scores.append(score)

    return history_scores


def get_history_series(symbol: str, days: int = 5, as_of_date: str = None) -> Dict[str, List[float]]:
    """获取最近 N 个交易日的历史评分序列（方向+波动）。"""
    records = records_repo.list_records_by_symbol(symbol)
    symbol_upper = symbol.upper()

    symbol_records = [
        r for r in records
        if r.get('symbol', "").upper() == symbol_upper
    ]

    if not symbol_records:
        return {"direction": [], "vol": []}

    if as_of_date is None:
        as_of = datetime.now()
    else:
        try:
            as_of = datetime.strptime(as_of_date, "%Y-%m-%d")
        except ValueError:
            as_of = datetime.now()

    records_by_date = defaultdict(list)
    for r in symbol_records:
        timestamp = r.get("timestamp", "")
        if not timestamp:
            continue
        try:
            date_str = timestamp.split(" ")[0]
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if dt <= as_of:
                records_by_date[date_str].append(r)
        except (ValueError, IndexError):
            continue

    daily_latest = {}
    for date_str, day_records in records_by_date.items():
        day_records.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        daily_latest[date_str] = day_records[0]

    sorted_dates = sorted(daily_latest.keys(), reverse=True)
    direction_scores, vol_scores = [], []

    for date_str in sorted_dates[:days]:
        record = daily_latest[date_str]
        dir_score = _extract_score(record, "direction_score", 0.0)
        vol_score = _extract_score(record, "vol_score", 0.0)

        direction_scores.append(dir_score)
        vol_scores.append(vol_score)

    return {"direction": direction_scores, "vol": vol_scores}


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
        
        # ✨ NEW: 检查是否需要跳过盘后数据获取
        skip_oi = should_skip_oi_fetch()
        skip_iv = skip_oi
        
        # 提取所有 symbol
        symbols = list(set(r.get('symbol', '') for r in records if r.get('symbol')))
        num_symbols = len(symbols)
        
        # 初始化 IV / OI 数据字典
        iv_data = {}
        oi_data = {}

        # 只获取一次 VIX，避免随标的循环打印
        vix_value = get_vix_with_fallback(default=18.0)

        if skip_iv:
            print(f"\n⏰ 当前时间早于 18:00 CST，跳过 IV 数据获取")
        else:
            iv_estimated_time = estimate_iv_fetch_time(num_symbols)
            iv_estimated_minutes = iv_estimated_time / 60.0
            print(f"\n{'='*60}")
            print("[FUTU] 期权数据:")
            print(f"   - 标的数量: {num_symbols}")
            print(f"   - 预计耗时: {iv_estimated_minutes:.1f} 分钟")
            print(f"{'='*60}\n")
            iv_data = fetch_iv_terms(symbols)

        if skip_oi:
            # ✨ 跳过 OI 获取
            print(f"\n⏰ 当前时间早于 18:00 CST，跳过 OI 数据获取")
            print(f"📊 将直接分析 {num_symbols} 个标的（无 ΔOI）\n")
        else:
            oi_input = {
                symbol: iv_data.get(symbol).total_oi if iv_data.get(symbol) else None
                for symbol in symbols
            }
            oi_data = batch_compute_delta_oi(oi_input)
        
        results = []
        errors = []
        
        for i, record in enumerate(records):
            try:
                symbol = record.get('symbol', '')
                
                # 注入 IV 数据（如果有）
                iv_result = iv_data.get(symbol)
                if iv_result:
                    if iv_result.iv7 is not None:
                        record['IV7'] = iv_result.iv7
                    if iv_result.iv30 is not None:
                        record['IV30'] = iv_result.iv30
                    if iv_result.iv60 is not None:
                        record['IV60'] = iv_result.iv60
                    if iv_result.iv90 is not None:
                        record['IV90'] = iv_result.iv90

                # 注入 OI 数据（如果有）
                if not skip_oi and symbol in oi_data:
                    current_oi, delta_oi = oi_data[symbol]
                    record['oi_info'] = {
                        'total_oi': current_oi,
                        'delta_oi_1d': delta_oi,
                        'data_available': (current_oi is not None or delta_oi is not None),
                    }
                    if current_oi is not None:
                        record['TotalOI'] = current_oi
                    if delta_oi is not None:
                        record['ΔOI_1D'] = delta_oi
                        
                # 获取历史评分用于跨期一致性计算与斜率叠加
                history_series = get_history_series(symbol, days=DEFAULT_CFG.get("trend_days", 5))
                history_scores = history_series["direction"]
                
                # ✨ NEW: 传递 skip_oi 标志到分析函数
                analysis = calculate_analysis(
                    record,
                    ignore_earnings=ignore_earnings,
                    history_scores=history_scores,
                    skip_oi=skip_oi,  # ✨ 新增参数
                    vix_value=vix_value
                )
                results.append(analysis)
            except Exception as e:
                error_msg = f"标的 {record.get('symbol', f'#{i+1}')} 分析失败: {str(e)}"
                errors.append(error_msg)
                print(f"错误: {error_msg}")
        
        # 保存数据
        if results:
            records_repo.upsert_daily_latest(results)
        
        message = f'成功分析 {len(results)} 个标的'
        if errors:
            message += f',{len(errors)} 个失败'
        
        # ✨ 修改响应消息
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
                'skipped': skip_oi  # ✨ 新增标志
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
        date_filter = request.args.get('date')
        quadrant_filter = request.args.get('quadrant')
        confidence_filter = request.args.get('confidence')
        data = records_repo.list_records(
            date=date_filter,
            quadrant=quadrant_filter if quadrant_filter != 'all' else None,
            confidence=confidence_filter if confidence_filter != 'all' else None
        )
        data = enrich_records_with_trend_fields(data, DEFAULT_CFG)
        return jsonify(data)
    
    except Exception as e:
        return jsonify([])


@app.route('/api/records/<timestamp>/<symbol>', methods=['DELETE'])
def delete_record(timestamp, symbol):
    """删除单条记录"""
    try:
        deleted = records_repo.delete_record(timestamp, symbol)
        if not deleted:
            return jsonify({'error': '未找到该记录'}), 404
        return jsonify({'message': '删除成功'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/records/date/<date>', methods=['DELETE'])
def delete_records_by_date(date):
    """按日期删除记录"""
    try:
        deleted_count = records_repo.delete_by_date(date)
        if deleted_count == 0:
            return jsonify({'error': '未找到该日期的记录'}), 404
        return jsonify({'message': f'成功删除 {deleted_count} 条记录'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/records/all', methods=['DELETE'])
def delete_all_records():
    """删除所有记录"""
    try:
        records_repo.delete_all()
        return jsonify({'message': '所有数据已删除'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/dates', methods=['GET'])
def get_dates():
    """获取所有日期"""
    try:
        dates = records_repo.list_dates()
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
    流式分析接口 - 修复版本
    
    修复内容：
    1. 流式推送分析进度
    2. ✨ NEW: 添加18:00时间限制逻辑
    
    POST /api/analyze/stream?ignore_earnings=false
    Body: { "records": [...] }
    
    返回 Server-Sent Events (SSE) 流
    """
    def generate():
        try:
            ignore_earnings = request.args.get('ignore_earnings', 'false').lower() == 'true'
            records = request.json.get('records', [])
            
            if not isinstance(records, list) or len(records) == 0:
                yield f"data: {json.dumps({'type': 'error', 'error': '数据格式错误'})}\n\n"
                return
            
            # 提取所有 symbol
            symbols = list(set(r.get('symbol', '') for r in records if r.get('symbol')))
            num_symbols = len(symbols)
            
            # 🟢 发送初始化消息
            yield f"data: {json.dumps({'type': 'init', 'total': num_symbols})}\n\n"
            
            # ✨ NEW: 检查是否需要跳过盘后数据获取
            skip_oi = should_skip_oi_fetch()
            skip_iv = skip_oi
            
            # 初始化 IV / OI 数据
            iv_data = {}
            oi_data = {}

            # 只获取一次 VIX，避免随标的循环打印
            vix_value = get_vix_with_fallback(default=18.0)
            
            if skip_iv:
                print(f"\n⏰ 当前时间早于 18:00 CST，跳过 IV 数据获取")
            else:
                iv_estimated_time = estimate_iv_fetch_time(num_symbols)
                iv_estimated_minutes = iv_estimated_time / 60.0
                print(f"\n{'='*60}")
                print("📊 IV 数据获取配置:")
                print(f"   - 标的数量: {num_symbols}")
                print(f"   - 预计耗时: {iv_estimated_minutes:.1f} 分钟")
                print(f"{'='*60}\n")
                iv_data = fetch_iv_terms(symbols)

            if skip_oi:
                # ✨ 跳过 OI 获取
                info_msg = {'type': 'info', 'message': '当前时间早于 18:00 CST，跳过 OI 数据获取', 'workers': 0, 'estimated_time': 0}
                yield f"data: {json.dumps(info_msg)}\n\n"
                
                complete_msg = {'type': 'oi_complete', 'success': 0, 'skipped': True}
                yield f"data: {json.dumps(complete_msg)}\n\n"
            else:
                oi_input = {
                    symbol: iv_data.get(symbol).total_oi if iv_data.get(symbol) else None
                    for symbol in symbols
                }
                oi_data = batch_compute_delta_oi(oi_input)
                complete_data = {
                    'type': 'oi_complete',
                    'success': sum(1 for s in symbols if oi_data.get(s, (None, None))[0] is not None),
                    'skipped': False
                }
                yield f"data: {json.dumps(complete_data)}\n\n"
            
            # 🟢 开始分析数据
            results = []
            errors = []
            processed_symbols = set()
            
            for i, record in enumerate(records):
                try:
                    symbol = record.get('symbol', '')
                    
                    # 注入 IV 数据（如果有）
                    iv_result = iv_data.get(symbol)
                    if iv_result:
                        if iv_result.iv7 is not None:
                            record['IV7'] = iv_result.iv7
                        if iv_result.iv30 is not None:
                            record['IV30'] = iv_result.iv30
                        if iv_result.iv60 is not None:
                            record['IV60'] = iv_result.iv60
                        if iv_result.iv90 is not None:
                            record['IV90'] = iv_result.iv90

                    # 注入 OI 数据（如果有）
                    if not skip_oi and symbol in oi_data:
                        current_oi, delta_oi = oi_data[symbol]
                        record['oi_info'] = {
                            'total_oi': current_oi,
                            'delta_oi_1d': delta_oi,
                            'data_available': (current_oi is not None or delta_oi is not None),
                        }
                        if current_oi is not None:
                            record['TotalOI'] = current_oi
                        if delta_oi is not None:
                            record['ΔOI_1D'] = delta_oi
                    
                    # 获取历史评分
                    history_scores = get_history_scores(symbol)
                    
                    # ✨ NEW: 传递 skip_oi 标志
                    analysis = calculate_analysis(
                        record,
                        ignore_earnings=ignore_earnings,
                        history_scores=history_scores,
                        skip_oi=skip_oi,  # ✨ 新增参数
                        vix_value=vix_value
                    )
                    results.append(analysis)
                    
                    # 记录唯一标的完成数量
                    if symbol:
                        processed_symbols.add(symbol)
                    
                    # 🟢 发送单条分析完成进度（按唯一标的计数，与前端总数一致）
                    analyze_progress = {
                        'type': 'analyze_progress', 
                        'completed': len(processed_symbols), 
                        'total': num_symbols,
                        'symbol': symbol,
                        'percentage': round(100 * len(processed_symbols) / num_symbols, 1) if num_symbols else 100.0
                    }
                    yield f"data: {json.dumps(analyze_progress)}\n\n"
                    # 方便诊断流式进度
                    print(f"[SSE] analyze_progress {len(processed_symbols)}/{num_symbols} {symbol}")
                
                except Exception as e:
                    error_msg = f"标的 {record.get('symbol', f'#{i+1}')} 分析失败: {str(e)}"
                    errors.append(error_msg)
            
            # 保存数据
            if results:
                records_repo.upsert_daily_latest(results)
            
            # 🟢 发送完成消息
            message = f'成功分析 {len(results)} 个标的'
            if errors:
                message += f',{len(errors)} 个失败'
            if skip_oi:
                message += ' (已跳过 OI 数据获取)'
            
            final_data = {
                'type': 'complete',
                'message': message,
                'results': results,
                'errors': errors if errors else None,
                'oi_stats': {
                    'total': num_symbols,
                    'success': sum(1 for s in symbols if oi_data.get(s, (None, None))[0] is not None),
                    'with_delta': sum(1 for s in symbols if oi_data.get(s, (None, None))[1] is not None),
                    'skipped': skip_oi  # ✨ 新增标志
                }
            }
            
            yield f"data: {json.dumps(final_data)}\n\n"
            
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


@app.route('/api/vix/info', methods=['GET'])
def get_vix_cache_info():
    """
    获取 VIX 缓存状态（诊断用）
    
    GET /api/vix/info
    
    响应示例:
        {
            "current_vix": 18.52,
            "cached_vix": 18.52,
            "cache_age_seconds": 300,
            "cache_valid": true,
            "cache_file": "vix_cache.json",
            "cache_exists": true
        }
    """
    try:
        info = get_vix_info()
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/vix/clear', methods=['POST'])
def clear_vix_cache_endpoint():
    """
    清除 VIX 缓存（强制刷新用）
    
    POST /api/vix/clear
    
    响应示例:
        {
            "message": "VIX cache cleared successfully"
        }
    """
    try:
        clear_vix_cache()
        return jsonify({'message': 'VIX cache cleared successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 注册 swing 项目的 API 扩展
from api_extension import register_bridge_api, register_swing_api
register_swing_api(app)
register_bridge_api(app, DEFAULT_CFG)


if __name__ == '__main__':
    print(">>>>>>>>> σ² <<<<<<<<<<<<<")
    
    try:
        debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
        # 默认关闭 reloader，避免长任务被热重载中断；需要调试时手动开启环境变量
        app.run(debug=debug_mode, use_reloader=False, host='0.0.0.0', port=8668)
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        import traceback
        traceback.print_exc()
