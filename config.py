# config.py
import os

# 基础路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'analysis_records.json')

#  策略参数
MESO_CONFIG = {
    # 基础风控
    "min_liquidity_conf": 0.3,
    
    # Meso 因子参数
    "term_steep_ratio": 1.1,    # 短端陡峭
    "active_open_threshold": 0.05, # 主动建仓显著性
    
    # 波动率参数
    "iv_rank_low": 30,
    "iv_rank_high": 70,
    
    # 挤压参数 (Gamma Squeeze)
    "squeeze_iv_hv": 0.95,
    "squeeze_oi_rank": 70,
    "squeeze_rel_vol": 1.2
}

# 指数列表
INDEX_TICKERS = ["SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "FXI", "SMH"]

# 爬虫配置
OI_MAX_WORKERS = 4      # 线程池并发数
OI_RETRY_COUNT = 3      # 单个标的重试次数
OI_EXPIRATION_LIMIT = 0 # 0表示获取所有到期日（最准），设置数字（如6）表示只取前6个以提速