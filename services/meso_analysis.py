# services/meso_analysis.py
import numpy as np
from datetime import datetime
from config import INDEX_TICKERS, MESO_CONFIG

# 🟢 [修复] 强化版数据清洗函数
def clean_val(val):
    """
    通用数据清洗工具：强制转换为 float
    处理：None, "12.5%", "1,200", "N/A", "+5" 等情况
    """
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    
    try:
        s = str(val).strip().upper()
        if not s or s == 'N/A' or s == '-':
            return 0.0
            
        s = s.replace('%', '').replace(',', '').replace('+', '')
        
        # 处理单位
        multiplier = 1.0
        if s.endswith('B'):
            multiplier = 1_000_000_000
            s = s[:-1]
        elif s.endswith('M'):
            multiplier = 1_000_000
            s = s[:-1]
        elif s.endswith('K'):
            multiplier = 1_000
            s = s[:-1]
            
        return float(s) * multiplier
    except Exception:
        return 0.0

class MesoEngine:
    @staticmethod
    def analyze(records: list, history_map: dict) -> list:
        results = []
        for rec in records:
            try:
                res = MesoEngine._process_single_record(rec, history_map)
                results.append(res)
            except Exception as e:
                # 打印详细错误以便调试，但不中断流程
                sym = rec.get('symbol', 'UNKNOWN')
                print(f"Error analyzing {sym}: {e}")
                # import traceback
                # traceback.print_exc() 
        return results

    @staticmethod
    def _process_single_record(rec: dict, history_map: dict) -> dict:
        sym = rec.get('symbol')
        cfg = MESO_CONFIG
        
        # --- 1. 基础数据清洗 (关键：全部通过 clean_val 过滤) ---
        vol = clean_val(rec.get('Volume', 0))
        price_chg = clean_val(rec.get('PriceChgPct', 0))
        iv30_chg = clean_val(rec.get('IV30ChgPct', 0))
        iv_rank = clean_val(rec.get('IVR', rec.get('IV Rank', 50))) # 兼容不同字段名
        
        # --- 2. 核心指标计算 () ---
        
        # A. Net Sentiment
        is_index = sym in INDEX_TICKERS
        net_sent = MesoEngine._calc_net_sentiment(rec, is_index)
        
        # B. Crowd Sensitivity
        crowd_sens = 0.0
        if abs(price_chg) > 0.1:
            crowd_sens = iv30_chg / price_chg
            
        # C. Active Open Ratio
        curr_oi = clean_val(rec.get('OpenInterest', 0))
        last_stats = history_map.get(sym, {})
        last_oi = clean_val(last_stats.get('last_oi', 0))
        
        active_open = 0.0
        delta_oi = 0.0
        
        if last_oi > 0 and vol > 0:
            delta_oi = curr_oi - last_oi
            active_open = delta_oi / vol
        
        # D. Structure Consistency
        cv = clean_val(rec.get('CallVolume', 0))
        pv = clean_val(rec.get('PutVolume', 0))
        total_opt_vol = cv + pv
        struct_cons = abs(cv - pv) / total_opt_vol if total_opt_vol > 0 else 0
        
        # E. Term Structure
        term_shape = MesoEngine._calc_term_shape(rec)
        
        # F. Liquidity Confidence
        oi_rank = clean_val(rec.get('OI_PctRank', 50))
        liquidity_conf = MesoEngine._calc_liquidity_conf(vol, oi_rank)

        # --- 3. 评分模型 ---
        
        base_dir = (np.tanh(price_chg) * 0.5) + (net_sent * 0.5)
        ao_modifier = 1.0 + np.tanh(active_open * 5)
        struct_modifier = 0.8 + (struct_cons * 0.4)
        
        final_dir_score = base_dir * ao_modifier * struct_modifier * 5
        
        # 波动评分
        iv30 = clean_val(rec.get('IV30', 0))
        hv20 = clean_val(rec.get('HV20', 1))
        iv_hv_ratio = iv30 / max(0.1, hv20)
        
        # 🟢 [修复] 确保所有比较对象都是数字
        vol_score = 0
        if iv_rank < float(cfg['iv_rank_low']): vol_score += 1
        if iv_rank > float(cfg['iv_rank_high']): vol_score -= 1
        if iv_hv_ratio < 0.9: vol_score += 1
        if iv_hv_ratio > 1.2: vol_score -= 1
        
        # --- 4. 状态判定 ---
        rel_vol = clean_val(rec.get('RelVolTo90D', 0))
        
        # 🟢 [修复] 确保所有比较对象都是数字
        is_squeeze = (
            iv_hv_ratio < float(cfg['squeeze_iv_hv']) and 
            oi_rank > float(cfg['squeeze_oi_rank']) and 
            price_chg > 1.5 and
            rel_vol > float(cfg['squeeze_rel_vol'])
        )
        
        # 四象限
        dir_label = "偏多" if final_dir_score > 0.5 else "偏空" if final_dir_score < -0.5 else "中性"
        vol_label = "买波" if vol_score > 0 else "卖波" if vol_score < 0 else "中性"
        quadrant = f"{dir_label}—{vol_label}"
        if "中性" in quadrant: quadrant = "中性/待观察"

        return {
            'symbol': sym,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'quadrant': quadrant,
            'confidence': f"{liquidity_conf:.2f}",
            'liquidity': "高" if liquidity_conf > 0.7 else "中" if liquidity_conf > 0.4 else "低",
            'is_squeeze': is_squeeze,
            'is_index': is_index,
            'direction_score': round(final_dir_score, 2),
            'vol_score': round(vol_score, 2),
            'spot_vol_corr_score': round(crowd_sens, 2),
            'term_structure_ratio': term_shape,
            'active_open_ratio': round(active_open, 4),
            'delta_oi': int(delta_oi),
            'net_sentiment': round(net_sent, 2),
            'strategy': MesoEngine._get_strategy(quadrant, is_squeeze),
            'risk': MesoEngine._get_risk(liquidity_conf),
            'raw_data': rec,
            'direction_bias': dir_label,
            'vol_bias': vol_label,
            'direction_factors': [f"ActiveOpen: {active_open:.2%}"], # 示例因子
            'vol_factors': [f"IVR: {iv_rank}"],
            'derived_metrics': {
                'ivrv_ratio': round(iv_hv_ratio, 2),
                'ivrv_diff': round(iv30 - hv20, 2),
                'cp_ratio': 0, # 可选：添加计算逻辑
                'days_to_earnings': 0
            }
        }

    @staticmethod
    def _calc_net_sentiment(rec, is_index):
        # 使用 clean_val 确保安全
        cp_val = rec.get('CallPutRatio', 0)
        # 如果不存在比率，尝试手动计算
        if not cp_val:
            cv = clean_val(rec.get('CallVolume', 0))
            pv = clean_val(rec.get('PutVolume', 0))
            cp_val = cv / max(1, pv)
        
        cp = clean_val(cp_val)
        put_pct = clean_val(rec.get('PutPct', 50))
        
        base_cp = 1.0 if is_index else 1.2
        base_put = 60.0 if is_index else 50.0
        
        score_cp = np.tanh((cp - base_cp) * 2) 
        score_put = np.tanh((base_put - put_pct) / 10) 
        return (score_cp + score_put) / 2

    @staticmethod
    def _calc_term_shape(rec):
        iv30 = clean_val(rec.get('IV30', 0))
        iv90 = clean_val(rec.get('IV90', 0))
        if iv90 == 0: return "N/A"
        ratio = iv30 / iv90
        if ratio > 1.1: return "Short Steep"
        if ratio < 0.9: return "Long Steep"
        return "Smooth"

    @staticmethod
    def _calc_liquidity_conf(vol, oi_rank):
        score_vol = np.tanh(vol / 100000) 
        score_oi = oi_rank / 100.0
        return min(1.0, 0.6 * score_vol + 0.4 * score_oi)

    @staticmethod
    def _get_strategy(quad, squeeze):
        if squeeze: return "🔥 强烈建议 Long Call (Gamma爆发)"
        maps = {
            "偏多—买波": "Long Call / Call Spread",
            "偏多—卖波": "Short Put / Put Spread",
            "偏空—买波": "Long Put / Put Spread",
            "偏空—卖波": "Bear Call Spread / Iron Condor"
        }
        return maps.get(quad, "观望")

    @staticmethod
    def _get_risk(conf):
        return "流动性低，减仓" if conf < 0.4 else "注意风控"