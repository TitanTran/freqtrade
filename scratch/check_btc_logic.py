import pandas as pd
import numpy as np
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib

# Load BTC data
df = pd.read_feather('user_data/data/binance/futures/BTC_USDT_USDT-1h-futures.feather')
df['ema_fast'] = ta.EMA(df, timeperiod=9)
df['ema_slow'] = ta.EMA(df, timeperiod=21)
df['ema_trend'] = ta.EMA(df, timeperiod=200)
df['rsi'] = ta.RSI(df, timeperiod=14)
df['ema_dist'] = abs(df['ema_fast'] - df['ema_slow']) / df['ema_slow']

# Conditions
df['cross_above'] = qtpylib.crossed_above(df['ema_fast'], df['ema_slow'])
df['rsi_dip'] = df['rsi'].shift(1) < 35
df['above_trend'] = df['close'] > df['ema_trend']
df['dist_filter'] = df['ema_dist'] > 0.0005

# Match
matches = df[df['cross_above'] & df['rsi_dip'] & df['above_trend'] & df['dist_filter']]

print(f"Total crosses: {df['cross_above'].sum()}")
print(f"Crosses with RSI dip: {(df['cross_above'] & df['rsi_dip']).sum()}")
print(f"Crosses with RSI dip and above trend: {(df['cross_above'] & df['rsi_dip'] & df['above_trend']).sum()}")
print(f"Final matches: {len(matches)}")

if len(matches) > 0:
    print(matches[['date', 'rsi', 'ema_dist', 'close']])
