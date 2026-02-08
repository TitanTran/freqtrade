import logging
from functools import reduce
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame
import talib.abstract as ta
import numpy as np
from datetime import datetime

logger = logging.getLogger(__name__)

class WolfStrategy(IStrategy):
    # --- CẤU HÌNH ---
    trailing_stop = False
    use_custom_stoploss = False
    stoploss = -0.05 
    minimal_roi = { "0": 0.04, "20": 0.02, "40": 0.01 }
    timeframe = "5m"

    def informative_pairs(self):
        return [("BTC/USDT:USDT", "1h")]

    def feature_engineering_expand_all(self, dataframe: DataFrame, period: int, metadata: dict, **kwargs) -> DataFrame:
        # FreqAI features
        dataframe["%-rsi-" + str(period)] = ta.RSI(dataframe, timeperiod=period)
        dataframe["%-mfi-" + str(period)] = ta.MFI(dataframe, timeperiod=period)
        dataframe["%-adx-" + str(period)] = ta.ADX(dataframe, timeperiod=period)
        dataframe["%-volume-" + str(period)] = dataframe["volume"]
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        self.freqai_info = self.config["freqai"]
        label_period = self.freqai_info["feature_parameters"].get("label_period_candles", 20)
        dataframe["&-s_close"] = (
            dataframe["close"].shift(-label_period).rolling(label_period).mean() / dataframe["close"] - 1
        )
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self.freqai.start(dataframe, metadata, self)
        
        # --- 1. CHỈ BÁO CƠ BẢN ---
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['ema_200'] = ta.EMA(dataframe, timeperiod=200)
        
        # --- 2. PHÂN TÍCH NẾN (CANDLESTICK ANATOMY) ---
        # Tính độ lớn thân nến và râu nến
        dataframe['body_size'] = abs(dataframe['close'] - dataframe['open'])
        dataframe['upper_wick'] = dataframe['high'] - dataframe[['open', 'close']].max(axis=1)
        dataframe['lower_wick'] = dataframe[['open', 'close']].min(axis=1) - dataframe['low']
        dataframe['total_range'] = dataframe['high'] - dataframe['low']
        
        # --- 3. BỘ LỌC BẪY (TRAP DETECTORS) ---
        
        # A. Trap: Liquidity Grab (Quét thanh khoản)
        # Nến có râu dưới quá dài so với thân (Pinbar/Hammer) -> Lực mua ẩn
        dataframe['is_bullish_sweep'] = (dataframe['lower_wick'] > dataframe['body_size'] * 2)
        # Nến có râu trên quá dài -> Lực bán ẩn (Shooting Star)
        dataframe['is_bearish_sweep'] = (dataframe['upper_wick'] > dataframe['body_size'] * 2)

        # B. Trap: Volume Churn (Nỗ lực ảo)
        # Volume lớn nhưng nến nhỏ -> Cẩn thận đảo chiều
        dataframe['vol_mean'] = dataframe['volume'].rolling(20).mean()
        dataframe['body_mean'] = dataframe['body_size'].rolling(20).mean()
        
        # Điều kiện: Volume > 1.5TB VÀ Thân nến < 0.8TB (Nến nhỏ volume to)
        dataframe['is_churning'] = (
            (dataframe['volume'] > dataframe['vol_mean'] * 1.5) & 
            (dataframe['body_size'] < dataframe['body_mean'] * 0.8)
        )

        # C. Valid Displacement (Nến phá vỡ uy tín)
        # Thân nến to, Volume to -> Smart Money đẩy giá thật
        dataframe['is_valid_move'] = (
            (dataframe['body_size'] > dataframe['body_mean'] * 1.0) &
            (dataframe['volume'] > dataframe['vol_mean'] * 1.0)
        )

        # --- 4. MACRO CONTEXT ---
        if self.dp:
            btc_1h = self.dp.get_pair_dataframe(pair="BTC/USDT:USDT", timeframe="1h")
            btc_1h['ema_200'] = ta.EMA(btc_1h, timeperiod=200)
            dataframe = merge_informative_pair(dataframe, btc_1h, self.timeframe, "1h", ffill=True)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Ngưỡng dự báo AI (Thấp để bắt nhiều cơ hội, nhưng lọc kỹ bằng nến)
        base_threshold = 0.003 
        
        # Xu hướng BTC
        btc_uptrend = (dataframe['close_1h'] > dataframe['ema_200_1h'])
        
        # --- LOGIC ENTRY LONG (THÔNG MINH HƠN) ---
        # 1. AI dự báo Tăng
        # 2. BTC ổn định (Trên EMA 200)
        # 3. Giá > EMA 200 (Uptrend)
        # 4. KHÔNG PHẢI là nến Volume ảo (Churning)
        # 5. KHÔNG PHẢI là nến bị bán mạnh (Bearish Sweep)
        # 6. RSI an toàn (< 70)
        # 7. Có lực đẩy thực sự (Valid Move) HOẶC Vừa có pha quét thanh khoản xong (Bullish Sweep)
        
        dataframe.loc[
            (
                btc_uptrend &
                (dataframe['do_predict'] == 1) &
                (dataframe['&-s_close'] > base_threshold) & 
                (dataframe['close'] > dataframe['ema_200']) & 
                (dataframe['is_churning'] == False) &       # Tránh bẫy Volume ảo
                (dataframe['is_bearish_sweep'] == False) &  # Tránh nến bị từ chối giá
                (dataframe['rsi'] < 70) &
                (
                    dataframe['is_valid_move'] |            # Hoặc là nến tăng mạnh uy tín
                    dataframe['is_bullish_sweep']           # Hoặc là vừa quét Stoploss xong rút chân
                )
            ),
            'enter_long'] = 1

        # --- LOGIC ENTRY SHORT ---
        dataframe.loc[
            (
                (dataframe['do_predict'] == 1) &
                (dataframe['&-s_close'] < -base_threshold) & 
                (dataframe['close'] < dataframe['ema_200']) & 
                (dataframe['is_churning'] == False) &
                (dataframe['is_bullish_sweep'] == False) &  # Tránh Short ngay đáy rút chân
                (dataframe['rsi'] > 30) &
                (
                    dataframe['is_valid_move'] |
                    dataframe['is_bearish_sweep']           # Short khi thấy Shooting Star
                )
            ),
            'enter_short'] = 1
        
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, ['exit_long', 'exit_short']] = 0
        return dataframe