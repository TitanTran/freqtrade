import logging
from functools import reduce
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame
import talib.abstract as ta
import numpy as np
from datetime import datetime
from freqtrade.persistence import Trade

logger = logging.getLogger(__name__)

class WolfStrategy(IStrategy):
    # --- CẤU HÌNH ---
    trailing_stop = True 
    use_custom_stoploss = False 
    
    # ROI: Chốt lãi linh hoạt
    minimal_roi = {
        "0": 0.20,       # Lãi 20% chốt (Ăn dày hơn)
        "30": 0.10,      
        "60": 0.05,      
        "120": 0.02      
    }
    
    timeframe = "5m"
    
    # STOPLOSS: -5% (Nới lỏng ra vì đã giảm đòn bẩy cho Altcoin)
    stoploss = -0.05

    # --- DYNAMIC LEVERAGE (VŨ KHÍ MỚI) ---
    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str, side: str,
                 **kwargs) -> float:
        
        # Nếu là BTC: Cho phép 5x (Vì biên độ dao động thấp)
        if "BTC" in pair:
            return 5.0
        
        # Nếu là Altcoin (ETH, BNB...): Chỉ 3x (Để tránh bị quét râu cháy lệnh)
        return 3.0

    # --- DATA ---
    def informative_pairs(self):
        return [("BTC/USDT:USDT", "1h")]

    # --- FREQAI ---
    def feature_engineering_expand_all(self, dataframe: DataFrame, period: int, metadata: dict, **kwargs) -> DataFrame:
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

    # --- INDICATORS ---
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self.freqai.start(dataframe, metadata, self)
        
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['ema_200'] = ta.EMA(dataframe, timeperiod=200)
        
        # Bollinger Bands
        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe['bb_upper'] = bollinger['upperband']
        dataframe['bb_lower'] = bollinger['lowerband']
        
        # Kill Zones
        dataframe['hour'] = dataframe['date'].dt.hour
        dataframe['in_kill_zone'] = (
            ((dataframe['hour'] >= 7) & (dataframe['hour'] <= 10)) | 
            ((dataframe['hour'] >= 12) & (dataframe['hour'] <= 16))
        )

        return dataframe

    # --- ENTRY (BEAR HUNTER) ---
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        
        common = (
            (dataframe['in_kill_zone']) &       
            (dataframe['do_predict'] == 1)
        )

        # LONG: Chỉ bắt đáy khi Uptrend
        long_cond = (
            (dataframe['close'] > dataframe['ema_200']) & 
            (dataframe['close'] <= dataframe['bb_lower']) & 
            (dataframe['&-s_close'] > 0.002)
        )
        dataframe.loc[(common & long_cond), 'enter_long'] = 1

        # SHORT: Săn đỉnh khi Downtrend
        short_cond = (
            (dataframe['close'] < dataframe['ema_200']) & 
            (
                (dataframe['close'] >= dataframe['bb_upper']) | 
                (dataframe['rsi'] > 50)                         
            ) &
            (dataframe['&-s_close'] < -0.002)
        )
        dataframe.loc[(common & short_cond), 'enter_short'] = 1
        
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, ['exit_long', 'exit_short']] = 0
        return dataframe