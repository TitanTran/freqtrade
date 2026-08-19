import pandas as pd
import numpy as np
import talib.abstract as ta

# Load BTC data
df = pd.read_feather('user_data/data/binance/futures/BTC_USDT_USDT-1h-futures.feather')
df['rsi'] = ta.RSI(df, timeperiod=14)

# Check RSI < 35
low_rsi = df[df['rsi'] < 35]
print(f"Total 1H candles: {len(df)}")
print(f"Candles with RSI < 35: {len(low_rsi)}")
if len(low_rsi) > 0:
    print("Last 5 low RSI candles:")
    print(low_rsi.tail(5)[['date', 'rsi', 'close']])
else:
    print("No candles with RSI < 35 found in the dataset.")
