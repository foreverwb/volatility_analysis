"""
IBKR API 获取52周最高价/最低价
"""

from ib_insync import *
import pandas as pd
from datetime import datetime

def get_52_week_high_low(symbol, ib):
    """
    获取股票的52周最高价和最低价
    
    参数:
    - symbol: 股票代码
    - ib: IBKR连接对象
    
    返回:
    - dict: 包含52周高低点信息
    """
    
    # 创建合约
    stock = Stock(symbol, 'SMART', 'USD')
    ib.qualifyContracts(stock)
    
    # 获取过去1年的日线数据
    bars = ib.reqHistoricalData(
        stock,
        endDateTime='',
        durationStr='1 Y',
        barSizeSetting='1 day',
        whatToShow='TRADES',
        useRTH=True
    )
    
    if not bars:
        return None
    
    # 转换为DataFrame
    df = util.df(bars)
    
    # 计算52周最高和最低
    week_52_high = df['high'].max()
    week_52_low = df['low'].min()
    
    # 获取当前价格
    ticker = ib.reqMktData(stock, '', snapshot=True)
    ib.sleep(2)
    current_price = ticker.last if ticker.last > 0 else ticker.close
    
    # 计算距离52周高低点的百分比
    pct_from_high = ((current_price - week_52_high) / week_52_high) * 100
    pct_from_low = ((current_price - week_52_low) / week_52_low) * 100
    
    # 找到52周高低点的日期
    high_date = df[df['high'] == week_52_high]['date'].iloc[0]
    low_date = df[df['low'] == week_52_low]['date'].iloc[0]
    
    result = {
        'symbol': symbol,
        'current_price': current_price,
        '52w_high': week_52_high,
        '52w_low': week_52_low,
        '52w_high_date': high_date,
        '52w_low_date': low_date,
        'pct_from_52w_high': pct_from_high,
        'pct_from_52w_low': pct_from_low,
        'near_52w_high': abs(pct_from_high) < 5,  # 距离高点5%以内
        'near_52w_low': abs(pct_from_low) < 5,    # 距离低点5%以内
    }
    
    ib.cancelMktData(stock)
    
    return result


# 使用示例
if __name__ == "__main__":
    
    # 连接IBKR
    ib = IB()
    ib.connect('127.0.0.1', 4002, clientId=3)
    ib.reqMarketDataType(3)  # 延迟数据
    
    # 测试多个股票
    symbols = ['NVDA', 'AAPL', 'MSFT', 'GOOGL', 'META']
    
    results = []
    
    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"分析 {symbol}")
        print(f"{'='*60}")
        
        result = get_52_week_high_low(symbol, ib)
        
        if result:
            results.append(result)
            
            print(f"当前价格: ${result['current_price']:.2f}")
            print(f"52周最高: ${result['52w_high']:.2f} ({result['52w_high_date']})")
            print(f"52周最低: ${result['52w_low']:.2f} ({result['52w_low_date']})")
            print(f"距离52周高点: {result['pct_from_52w_high']:+.2f}%")
            print(f"距离52周低点: {result['pct_from_52w_low']:+.2f}%")
            
            if result['near_52w_high']:
                print("🟢 接近52周高点!")
            elif result['near_52w_low']:
                print("🔴 接近52周低点!")
        
        ib.sleep(1)
    
    
    ib.disconnect()
    print("\n✅ 完成")
