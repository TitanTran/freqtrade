import logging
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame
import talib.abstract as ta
import numpy as np
from datetime import datetime
from freqtrade.persistence import Trade

logger = logging.getLogger(__name__)

class WolfStrategy(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True

    # --- 1. KIẾN TRÚC BẢO VỆ TÀI SẢN (DEFENSIVE LAYER) ---
    stoploss = -0.07
    use_custom_stoploss = True
    
    trailing_stop = True
    trailing_stop_positive = 0.015
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    minimal_roi = {
        "0": 0.15,
        "60": 0.04,
        "120": 0.015
    }

    # Cơ chế Tản nhiệt chống Revenge Trading
    protections = [
        {"method": "CooldownPeriod", "stop_duration_candles": 12}
    ]

    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        time_held = (current_time - trade.open_date_utc).total_seconds()
        # Time-based Bailout: Thoát hàng kẹp sau 1.5h nếu âm > 3%
        if time_held > 5400 and current_profit < -0.03:
            return -0.0001
        return 1

    # --- 2. BỘ CẤP DỮ LIỆU ĐA CHIỀU CHO AI (FEATURE ENGINEERING) ---
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, "1h") for pair in pairs] # Cấp dữ liệu Vĩ mô 1H

    def feature_engineering_expand_all(self, dataframe: DataFrame, period: int, metadata: dict, **kwargs) -> DataFrame:
        # Nhóm 1: Price Action & Momentum (Động lượng giá)
        dataframe["%-rsi-" + str(period)] = ta.RSI(dataframe, timeperiod=period)
        dataframe["%-mfi-" + str(period)] = ta.MFI(dataframe, timeperiod=period)
        dataframe["%-adx-" + str(period)] = ta.ADX(dataframe, timeperiod=period)
        
        # Nhóm 2: Volatility (Đo lường độ nén của nến)
        bb = ta.BBANDS(dataframe, timeperiod=period)
        dataframe["%-bb_width-" + str(period)] = (bb['upperband'] - bb['lowerband']) / bb['middleband']
        
        # Nhóm 3: Liquidity Zones Proxy (Dấu chân Market Maker)
        dataframe["%-obv-" + str(period)] = ta.OBV(dataframe['close'], dataframe['volume'])
        dataframe["%-ad_line-" + str(period)] = ta.AD(dataframe['high'], dataframe['low'], dataframe['close'], dataframe['volume'])
        
        return dataframe

    # --- 3. HÀM MỤC TIÊU V4 (MAX RISK/REWARD LABELING) ---
    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        horizon = 10 # Tầm nhìn: 10 nến tương lai (50 phút)
        
        # Tìm Đỉnh cao nhất và Đáy thấp nhất trong 10 nến tới (Dữ liệu Tương lai)
        future_max = dataframe['high'].shift(-horizon).rolling(horizon).max()
        future_min = dataframe['low'].shift(-horizon).rolling(horizon).min()
        
        # Tính toán Lợi nhuận và Drawdown tối đa theo %
        max_gain_pct = (future_max - dataframe['close']) / dataframe['close']
        max_loss_pct = (dataframe['close'] - future_min) / dataframe['close']
        
        # KIẾN TRÚC MỤC TIÊU: Trừng phạt Drawdown gấp 2 lần (Phòng vệ chủ động)
        # Prefix '&-' đảm bảo FreqAI cắt bỏ cột này khi Live Trading (Chống Lookahead Bias tuyệt đối)
        dataframe["&-rr_score"] = max_gain_pct - (max_loss_pct * 2.0)
        
        return dataframe

    # --- 4. TRIPLE CONFIRMATION (XÁC NHẬN BA LẦN) ---
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Macro Filter (1H)
        inf_df = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe="1h")
        inf_df['ema_200'] = ta.EMA(inf_df, timeperiod=200)
        dataframe = merge_informative_pair(dataframe, inf_df, self.timeframe, "1h", ffill=True)

        # Micro Filter (5m)
        dataframe['ema_200'] = ta.EMA(dataframe, timeperiod=200)
        macd = ta.MACD(dataframe)
        dataframe['macdhist'] = macd['macdhist']
        dataframe['mfi'] = ta.MFI(dataframe, timeperiod=14)

        # Đánh thức Trí tuệ Nhân tạo
        dataframe = self.freqai.start(dataframe, metadata, self)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        common = (dataframe['do_predict'] == 1)

        # KỊCH BẢN LONG: Macro Tăng + Lực Bán Kiệt Quệ + AI dự báo RR Score > 1.5%
        long_cond = (
            (dataframe['close'] > dataframe['ema_200']) & 
            (dataframe['close'] > dataframe['ema_200_1h']) & 
            (dataframe['macdhist'] > dataframe['macdhist'].shift(1)) & 
            (dataframe['mfi'] < 80) & 
            (dataframe['&-rr_score'] > 0.015) & # AI FreqAI Xác nhận Lợi nhuận vượt xa Rủi ro
            (dataframe['volume'] > 0)
        )
        dataframe.loc[(common & long_cond), ['enter_long', 'enter_tag']] = (1, 'long_mtf_v4')

        # KỊCH BẢN SHORT: Macro Giảm + Lực Mua Kiệt Quệ + AI dự báo RR Score cắm mỏ < -1.5%
        short_cond = (
            (dataframe['close'] < dataframe['ema_200']) & 
            (dataframe['close'] < dataframe['ema_200_1h']) & 
            (dataframe['macdhist'] < dataframe['macdhist'].shift(1)) & 
            (dataframe['mfi'] > 20) & 
            (dataframe['&-rr_score'] < -0.015) & 
            (dataframe['volume'] > 0)
        )
        dataframe.loc[(common & short_cond), ['enter_short', 'enter_tag']] = (1, 'short_mtf_v4')
        
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, ['exit_long', 'exit_short']] = 0
        return dataframe