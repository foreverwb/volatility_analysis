# services/data_manager.py
import json
import os
from config import DATA_FILE

class DataManager:
    @staticmethod
    def load_records():
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []

    @staticmethod
    def save_records(data):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def get_history_map(all_records):
        """构建历史数据索引，用于计算 Delta OI"""
        history = {}
        # 按时间排序
        sorted_records = sorted(all_records, key=lambda x: x.get('timestamp', ''))
        
        for rec in sorted_records:
            sym = rec.get('symbol')
            if not sym: continue
            
            # 优先从 raw_data 获取原始 OpenInterest (它是绝对值)
            raw = rec.get('raw_data', {})
            total_oi = raw.get('OpenInterest', 0)
            
            # 如果 raw_data 没有，尝试从根目录获取 (兼容旧数据)
            if not total_oi:
                total_oi = rec.get('OpenInterest', 0)
                
            history[sym] = {
                'last_oi': total_oi,
                'timestamp': rec.get('timestamp')
            }
        return history