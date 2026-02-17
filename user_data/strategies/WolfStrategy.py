import logging
from functools import reduce
from freqtrade.strategy import IStrategy, merge_informative_pair, DecimalParameter, IntParameter, CategoricalParameter
from pandas import DataFrame
import talib.abstract as ta
import numpy as np
from datetime import datetime
from freqtrade.persistence import Trade

logger = logging.getLogger(__name__)

class WolfStrategy(IStrategy):
    INTERFACE_VERSION = 3
    
    # 1. CẤU HÌNH CƠ BẢN
    can_short = True 
    timeframe = "5m"
    
    # 2. KHAI BÁO BIẾN MẶC ĐỊNH (CHO CHẠY LIVE/DRY RUN)
    # Những số này sẽ được dùng nếu bạn KHÔNG chạy Hyperopt
    stoploss = -0.05
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    # 3. KHAI BÁO KHÔNG GIAN TÌM KIẾM (CHO HYPEROPT)
    # Đây là những khoảng giá trị mà Hyperopt sẽ thử nghiệm
    
    # Tìm Stoploss từ -3% đến -10%
    stoploss_space = DecimalParameter(-0.10, -0.03, default=-0.05, space='sell', optimize=True)
    
    # Tìm Trailing Stop (Offset: 1%-5%, Distance: 0.5%-2%)
    trailing_stop_positive_offset_space = DecimalParameter(0.01, 0.05, default=0.02, space='sell', optimize=True)
    trailing_stop_positive_space = DecimalParameter(0.005, 0.02, default=0.01, space='sell', optimize=True)

    # ROI (Mặc định - Hyperopt sẽ tự tìm đè lên cái này nếu bạn bật --spaces roi)
    minimal_roi = {
        "0": 0.20,
        "60": 0.10,
        "120": 0.05,
        "240": 0.03
    }

    # --- ĐÒN BẨY ---
    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str, side: str,
                 **kwargs) -> float:
        return 3.0

    # --- DATA (NHÌN RỘNG 1H) ---
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, "1h") for pair in pairs]

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

    # --- INDICATORS & HYPEROPT INJECTION ---
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        
        # === PHẦN SỬA LỖI QUAN TRỌNG NHẤT ===
        # Cơ chế "Tiêm thuốc": Nếu đang chạy Hyperopt, lấy giá trị từ Space đè vào biến
        if self.config['runmode'].value in ('hyperopt', 'backtest'):
            self.stoploss = self.stoploss_space.value
            self.trailing_stop_positive = self.trailing_stop_positive_space.value
            self.trailing_stop_positive_offset = self.trailing_stop_positive_offset_space.value
        # ====================================

        dataframe = self.freqai.start(dataframe, metadata, self)
        
        # 1. Chỉ báo khung 5m
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['mfi'] = ta.MFI(dataframe, timeperiod=14)
        dataframe['ema_200'] = ta.EMA(dataframe, timeperiod=200)
        
        # Bollinger Bands (5m)
        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe['bb_upper'] = bollinger['upperband']
        dataframe['bb_lower'] = bollinger['lowerband']

        # 2. Chỉ báo khung 1h (Xu hướng lớn)
        informative_1h = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe="1h")
        informative_1h['ema_200'] = ta.EMA(informative_1h, timeperiod=200)
        dataframe = merge_informative_pair(dataframe, informative_1h, self.timeframe, "1h", ffill=True)

        return dataframe

    # --- ENTRY LOGIC ---
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        common = (dataframe['do_predict'] == 1)

        # LONG: Mua khi 5m & 1h đều Tăng + Giá chạm đáy BB + AI báo Tăng
        long_cond = (
            (dataframe['close'] > dataframe['ema_200']) & 
            (dataframe['close'] > dataframe['ema_200_1h']) & 
            (dataframe['close'] <= dataframe['bb_lower']) & 
            (dataframe['&-s_close'] > 0.002) &
            (dataframe['mfi'] < 80)
        )
        dataframe.loc[(common & long_cond), 'enter_long'] = 1

        # SHORT: Bán khi 5m & 1h đều Giảm + Giá chạm đỉnh BB + AI báo Giảm
        short_cond = (
            (dataframe['close'] < dataframe['ema_200']) & 
            (dataframe['close'] < dataframe['ema_200_1h']) & 
            (dataframe['close'] >= dataframe['bb_upper']) & 
            (dataframe['&-s_close'] < -0.002) &
            (dataframe['mfi'] > 20)
        )
        dataframe.loc[(common & short_cond), 'enter_short'] = 1
        
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, ['exit_long', 'exit_short']] = 0
        return dataframe