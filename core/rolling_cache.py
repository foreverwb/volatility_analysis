"""
历史数据缓存管理模块 - v2.3.3
Rolling Window Cache for Dynamic Parameters

管理：
- 60 日滚动窗口（符号级别）
- 20 日 VIX 历史数据
- 动态参数 EMA 历史
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import deque


class RollingCache:
    """滚动窗口历史数据缓存"""
    
    def __init__(self, cache_file: str = "rolling_cache.json"):
        """
        初始化缓存
        
        Args:
            cache_file: 缓存文件路径
        """
        self.cache_file = cache_file
        self.data = self._load_cache()
    
    def _load_cache(self) -> Dict:
        """从文件加载缓存"""
        if not os.path.exists(self.cache_file):
            return self._init_empty_cache()
        
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else self._init_empty_cache()
        except Exception as e:
            print(f"Warning: Failed to load cache: {e}")
            return self._init_empty_cache()
    
    def _init_empty_cache(self) -> Dict:
        """初始化空缓存结构"""
        return {
            "symbols": {},      # 符号级别的历史数据
            "vix": {            # VIX 历史数据
                "values": [],
                "timestamps": []
            },
            "params": {},       # 动态参数 EMA 历史
            "meta": {
                "last_update": None,
                "version": "2.3.3"
            }
        }
    
    def save_cache(self):
        """保存缓存到文件"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error: Failed to save cache: {e}")
    
    def update_symbol_data(
        self,
        symbol: str,
        record: Dict,
        max_window: int = 60
    ):
        """
        更新符号的历史数据
        
        Args:
            symbol: 标的代码
            record: 当前记录
            max_window: 最大窗口大小（天数）
        """
        if "symbols" not in self.data:
            self.data["symbols"] = {}
        
        if symbol not in self.data["symbols"]:
            self.data["symbols"][symbol] = {
                "RelVolTo90D": [],
                "OI_PctRank": [],
                "IV30": [],
                "HV20": [],
                "timestamps": []
            }
        
        symbol_data = self.data["symbols"][symbol]
        
        # 提取当前值
        timestamp = record.get("timestamp", datetime.now().isoformat())
        rel_vol = record.get("RelVolTo90D", 1.0) or 1.0
        oi_rank = record.get("OI_PctRank", 50.0) or 50.0
        iv30 = record.get("IV30", 0) or 0
        hv20 = record.get("HV20", 0) or 0
        
        # 添加新数据
        symbol_data["RelVolTo90D"].append(rel_vol)
        symbol_data["OI_PctRank"].append(oi_rank)
        symbol_data["IV30"].append(iv30)
        symbol_data["HV20"].append(hv20)
        symbol_data["timestamps"].append(timestamp)
        
        # 维持窗口大小
        for key in ["RelVolTo90D", "OI_PctRank", "IV30", "HV20", "timestamps"]:
            if len(symbol_data[key]) > max_window:
                symbol_data[key] = symbol_data[key][-max_window:]
    
    def update_vix_data(
        self,
        vix_value: float,
        timestamp: Optional[str] = None,
        max_window: int = 20
    ):
        """
        更新 VIX 历史数据
        
        Args:
            vix_value: VIX 值
            timestamp: 时间戳
            max_window: 最大窗口大小
        """
        if "vix" not in self.data:
            self.data["vix"] = {"values": [], "timestamps": []}
        
        if timestamp is None:
            timestamp = datetime.now().isoformat()
        
        vix_data = self.data["vix"]
        
        # 检查是否为同一天（避免重复添加）
        if vix_data["timestamps"]:
            last_date = vix_data["timestamps"][-1].split('T')[0]
            current_date = timestamp.split('T')[0]
            
            if last_date == current_date:
                # 同一天，更新最新值
                vix_data["values"][-1] = vix_value
                vix_data["timestamps"][-1] = timestamp
                return
        
        # 添加新数据
        vix_data["values"].append(vix_value)
        vix_data["timestamps"].append(timestamp)
        
        # 维持窗口大小
        if len(vix_data["values"]) > max_window:
            vix_data["values"] = vix_data["values"][-max_window:]
            vix_data["timestamps"] = vix_data["timestamps"][-max_window:]
    
    def update_param_ema(
        self,
        symbol: str,
        params: Dict[str, float]
    ):
        """
        更新动态参数的 EMA 值
        
        Args:
            symbol: 标的代码（"_global" 表示全局参数如 alpha_t）
            params: 动态参数字典 {'beta_t': x, 'lambda_t': y, 'alpha_t': z}
        """
        if "params" not in self.data:
            self.data["params"] = {}
        
        if symbol not in self.data["params"]:
            self.data["params"][symbol] = {}
        
        # 更新参数
        self.data["params"][symbol].update(params)
    
    def get_symbol_history(self, symbol: str) -> Dict:
        """
        获取符号的历史数据
        
        Args:
            symbol: 标的代码
            
        Returns:
            历史数据字典
        """
        return self.data.get("symbols", {}).get(symbol, {
            "RelVolTo90D": [],
            "OI_PctRank": [],
            "IV30": [],
            "HV20": [],
            "timestamps": []
        })
    
    def get_vix_history(self) -> List[float]:
        """获取 VIX 历史值列表"""
        return self.data.get("vix", {}).get("values", [])
    
    def get_param_ema(self, symbol: str) -> Dict:
        """
        获取符号的参数 EMA 历史
        
        Args:
            symbol: 标的代码
            
        Returns:
            参数 EMA 字典
        """
        return self.data.get("params", {}).get(symbol, {})
    
    def get_cache_stats(self) -> Dict:
        """
        获取缓存统计信息
        
        Returns:
            统计信息字典
        """
        symbols_count = len(self.data.get("symbols", {}))
        vix_count = len(self.data.get("vix", {}).get("values", []))
        
        # 计算平均数据点数
        total_points = 0
        for symbol_data in self.data.get("symbols", {}).values():
            total_points += len(symbol_data.get("RelVolTo90D", []))
        
        avg_points = total_points / symbols_count if symbols_count > 0 else 0
        
        return {
            "symbols_count": symbols_count,
            "vix_history_length": vix_count,
            "avg_data_points_per_symbol": round(avg_points, 1),
            "last_update": self.data.get("meta", {}).get("last_update"),
            "cache_file": self.cache_file,
            "file_exists": os.path.exists(self.cache_file)
        }
    
    def cleanup_old_data(self, days_to_keep: int = 90):
        """
        清理过期数据
        
        Args:
            days_to_keep: 保留的天数
        """
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        cutoff_str = cutoff_date.isoformat()
        
        # 清理符号数据
        for symbol in list(self.data.get("symbols", {}).keys()):
            symbol_data = self.data["symbols"][symbol]
            timestamps = symbol_data.get("timestamps", [])
            
            # 找到有效数据的起始索引
            valid_indices = [i for i, ts in enumerate(timestamps) if ts >= cutoff_str]
            
            if not valid_indices:
                # 所有数据都过期，删除该符号
                del self.data["symbols"][symbol]
            else:
                start_idx = valid_indices[0]
                # 只保留有效数据
                for key in symbol_data:
                    if isinstance(symbol_data[key], list):
                        symbol_data[key] = symbol_data[key][start_idx:]
        
        # 清理 VIX 数据
        vix_data = self.data.get("vix", {})
        vix_timestamps = vix_data.get("timestamps", [])
        valid_indices = [i for i, ts in enumerate(vix_timestamps) if ts >= cutoff_str]
        
        if valid_indices:
            start_idx = valid_indices[0]
            vix_data["values"] = vix_data["values"][start_idx:]
            vix_data["timestamps"] = vix_data["timestamps"][start_idx:]
    
    def export_to_dict(self) -> Dict:
        """导出完整缓存数据"""
        return self.data.copy()
    
    def get_data(self) -> Dict:
        """获取原始缓存数据（供 dynamic_params 使用）"""
        return self.data


# 全局缓存实例
_global_cache: Optional[RollingCache] = None


def get_global_cache(cache_file: str = "rolling_cache.json") -> RollingCache:
    """
    获取全局缓存实例（单例模式）
    
    Args:
        cache_file: 缓存文件路径
        
    Returns:
        RollingCache 实例
    """
    global _global_cache
    
    if _global_cache is None:
        _global_cache = RollingCache(cache_file)
    
    return _global_cache


def update_cache_with_record(
    record: Dict,
    vix_value: float,
    dynamic_params: Dict[str, float],
    cache: Optional[RollingCache] = None
):
    """
    使用分析记录更新缓存（便捷函数）
    
    Args:
        record: 分析记录
        vix_value: VIX 值
        dynamic_params: 动态参数
        cache: 缓存实例（None 则使用全局缓存）
    """
    if cache is None:
        cache = get_global_cache()
    
    symbol = record.get("symbol", "")
    timestamp = record.get("timestamp", datetime.now().isoformat())
    
    # 更新符号数据
    cache.update_symbol_data(symbol, record)
    
    # 更新 VIX 数据
    cache.update_vix_data(vix_value, timestamp)
    
    # 更新参数 EMA（符号级别）
    cache.update_param_ema(symbol, {
        "beta_t": dynamic_params.get("beta_t"),
        "lambda_t": dynamic_params.get("lambda_t")
    })
    
    # 更新参数 EMA（全局级别）
    cache.update_param_ema("_global", {
        "alpha_t": dynamic_params.get("alpha_t")
    })
    
    # 更新元数据
    cache.data["meta"]["last_update"] = timestamp
    
    # 保存缓存
    cache.save_cache()