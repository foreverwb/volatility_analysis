# services/oi_fetcher.py
import yfinance as yf
import pandas as pd
import time
import random
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import OI_MAX_WORKERS, OI_EXPIRATION_LIMIT

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

class OIFetcher:
    @staticmethod
    def get_realtime_oi(symbol: str, retries=3) -> dict:
        """
        获取单个 Symbol 的精确 OI，包含重试和延时机制
        """
        # 🟢 [新增] 随机延时，防止并发过快被封
        time.sleep(random.uniform(0.1, 0.5))
        
        for attempt in range(retries):
            try:
                ticker = yf.Ticker(symbol)
                expirations = ticker.options
                
                if not expirations:
                    # 如果没有期权链，可能是网络问题，稍作等待重试
                    if attempt < retries - 1:
                        time.sleep(1)
                        continue
                    return {"total": 0, "call": 0, "put": 0, "status": "no_options"}

                # 限制到期日数量
                target_exps = expirations
                if OI_EXPIRATION_LIMIT > 0:
                    target_exps = expirations[:OI_EXPIRATION_LIMIT]

                total_oi = 0
                call_oi = 0
                put_oi = 0
                valid_chain_count = 0
                
                for exp in target_exps:
                    try:
                        opt = ticker.option_chain(exp)
                        # 处理 NaN
                        c = opt.calls['openInterest'].fillna(0).sum()
                        p = opt.puts['openInterest'].fillna(0).sum()
                        
                        # 累加
                        call_oi += int(c)
                        put_oi += int(p)
                        total_oi += int(c + p)
                        valid_chain_count += 1
                    except Exception:
                        continue
                
                # 🟢 [新增] 如果获取成功但总数为0，且重试次数未用完，尝试重试
                # (防止 yfinance 返回空数据的情况)
                if total_oi == 0 and attempt < retries - 1:
                    time.sleep(1.5) # 等待稍长一点
                    continue

                return {
                    "total": total_oi,
                    "call": call_oi,
                    "put": put_oi,
                    "status": "success"
                }
                
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
                return {"total": 0, "call": 0, "put": 0, "status": f"error: {str(e)}"}
        
        return {"total": 0, "call": 0, "put": 0, "status": "failed_after_retries"}

    @staticmethod
    def fetch_batch_oi(symbols: list) -> dict:
        results = {}
        unique_symbols = list(set(symbols))
        total_count = len(unique_symbols)
        
        print(f"\n🔄 开始多线程获取 {total_count} 个标的 OI (Workers={OI_MAX_WORKERS})...")
        
        with ThreadPoolExecutor(max_workers=OI_MAX_WORKERS) as executor:
            future_to_symbol = {
                executor.submit(OIFetcher.get_realtime_oi, sym): sym 
                for sym in unique_symbols
            }
            
            completed = 0
            for future in as_completed(future_to_symbol):
                sym = future_to_symbol[future]
                try:
                    data = future.result()
                    results[sym] = data
                    
                    completed += 1
                    oi_val = data.get('total', 0)
                    # 只有大于0才算真正成功
                    status_icon = "✓" if oi_val > 0 else "⚠"
                    print(f"[{completed}/{total_count}] {status_icon} {sym:<6} - OI: {oi_val:>12,}")
                    
                except Exception as exc:
                    print(f"[{completed}/{total_count}] ✗ {sym:<6} - Exception: {exc}")
                    results[sym] = {"total": 0, "status": "exception"}

        return results