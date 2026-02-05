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
    # --- CẤU HÌNH CƠ BẢN ---
    minimal_roi = {"0": 100} 
    stoploss = -0.10 
    timeframe = "5m"
    
    # [QUAN TRỌNG] Chỉ tập trung đánh Short
    can_short = True 
    
    use_custom_stoploss = True
    use_custom_exit = True

    # --- PHẦN 1: INFORMATIVE PAIRS (KÉO DỮ LIỆU 1H VỀ) ---
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, "1h") for pair in pairs]

    # --- PHẦN 2: QUẢN LÝ RỦI RO ĐỘNG (SMART STOPLOSS) ---
    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        last_candle = dataframe.iloc[-1].squeeze()

        # TÍNH TOÁN ATR
        atr_pixel = last_candle.get('atr', current_rate * 0.02)
        atr_percent = atr_pixel / current_rate
        if np.isnan(atr_percent): atr_percent = 0.02

        # 1. BẢO VỆ VỊ THẾ (KHI VỪA VÀO HOẶC LỖ)
        if current_profit < (atr_percent * 1.5): 
            base_multiplier = 3.0
            volatility_factor = 1.0
            if last_candle.get('adx', 0) < 20: 
                volatility_factor = 1.3 
            
            dynamic_sl_pct = atr_percent * base_multiplier * volatility_factor
            return max(min(-dynamic_sl_pct, -0.025), -0.10)

        # 2. KHÓA LỢI NHUẬN (DYNAMIC BREAK EVEN)
        target_breakeven = atr_percent * 2.0 
        
        if current_profit > target_breakeven:
            # Gồng lời: Nếu lãi > 5 ATR -> Trail sát hơn
            target_trailing = atr_percent * 5.0
            if current_profit > target_trailing:
                trailing_distance = atr_percent * 1.5
                return trailing_distance
            
            # Hòa vốn: Dời SL về dương nhẹ
            return atr_percent * 0.5

        return 1

    # --- PHẦN 3: CHIẾN LƯỢC THOÁT LỆNH (TAKE PROFIT) ---
    def custom_exit(self, pair: str, trade: 'Trade', current_time: 'datetime', current_rate: float,
                    current_profit: float, **kwargs):
        
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        last_candle = dataframe.iloc[-1].squeeze()
        
        # 1. HARD TAKE PROFIT (Giữ nguyên)
        if current_profit > 0.05:
            return "hard_take_profit_5pct"

        # 2. AI REVERSAL (TINH CHỈNH: Tăng ngưỡng chịu đựng)
        if trade.is_short:
            # Cũ: 0.002 (0.2%) -> Nhạy cảm, dễ thoát non.
            # Mới: 0.005 (0.5%) -> Chỉ thoát khi AI báo động đỏ (Reversal mạnh).
            if last_candle['&-s_close'] > 0.005: 
                return "ai_reversal_short"

        # 3. TIME-BASED EXIT (Giữ nguyên)
        trade_duration = (current_time - trade.open_date_utc).total_seconds() / 60
        if trade_duration > 720 and current_profit < 0.01:
            return "stale_trade_exit"

        # 4. EXTREME RSI EXIT (Giữ nguyên)
        if current_profit > 0.02: 
            if trade.is_short and last_candle['rsi'] < 15: return "rsi_oversold_exit"

        return None

    # --- PHẦN 4: TÍNH TOÁN CHỈ BÁO ---
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # FreqAI
        dataframe = self.freqai.start(dataframe, metadata, self)
        
        # Multi-Timeframe 1H (Để lọc Short an toàn)
        if self.dp: 
            informative_1h = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe="1h")
            informative_1h['ema_200'] = ta.EMA(informative_1h, timeperiod=200)
            dataframe = merge_informative_pair(dataframe, informative_1h, self.timeframe, "1h", ffill=True)
        
        # Indicators 5m
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['ema_200'] = ta.EMA(dataframe, timeperiod=200)
        dataframe['volume_mean_20'] = dataframe['volume'].rolling(window=20).mean()
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        
        return dataframe

    # --- PHẦN 5: LOGIC VÀO LỆNH (SHORT ONLY) ---
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        base_threshold = 0.004
        
        # Tính toán ngưỡng động
        dataframe['vol_factor'] = np.where(dataframe['volume'] > dataframe['volume_mean_20'], 0.9, 1.5)
        trend_factor_short = np.where(dataframe['close'] < dataframe['ema_200'], 0.8, 1.2)
        dataframe['dynamic_threshold_short'] = base_threshold * trend_factor_short * dataframe['vol_factor']

        # --- ENTRY LONG: VÔ HIỆU HÓA HOÀN TOÀN ---
        dataframe.loc[:, 'enter_long'] = 0

        # --- ENTRY SHORT ---
        enter_short_conditions = [
            dataframe['do_predict'] == 1,
            
            # 1. AI Dự báo giảm mạnh hơn ngưỡng động
            dataframe['&-s_close'] < -(dataframe['dynamic_threshold_short']),
            
            # 2. Hard Filter: Chỉ Short khi giá nằm DƯỚI đường EMA 200 (Khung 1H)
            # Nếu chưa có data 1h thì dùng tạm 5m để fallback
            (dataframe['close'] < dataframe.get('ema_200_1h', dataframe['ema_200'])), 
            
            # 3. RSI không quá thấp (Tránh short ngay đáy)
            dataframe['rsi'] > 25
        ]
        
        if enter_short_conditions:
            dataframe.loc[reduce(lambda x, y: x & y, enter_short_conditions), 'enter_short'] = 1
        
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, 'exit_long'] = 0
        dataframe.loc[:, 'exit_short'] = 0
        return dataframe

    # --- FREQAI CONFIG ---
    def feature_engineering_expand_all(self, dataframe: DataFrame, period: int, metadata: dict, **kwargs) -> DataFrame:
        dataframe["%-rsi-" + str(period)] = ta.RSI(dataframe, timeperiod=period)
        dataframe["%-mfi-" + str(period)] = ta.MFI(dataframe, timeperiod=period)
        dataframe["%-adx-" + str(period)] = ta.ADX(dataframe, timeperiod=period)
        return dataframe

    def feature_engineering_standard(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        dataframe["%-day_of_week"] = dataframe["date"].dt.dayofweek
        dataframe["%-hour_of_day"] = dataframe["date"].dt.hour
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        label_period = self.freqai_info["feature_parameters"]["label_period_candles"]
        dataframe["&-s_close"] = (
            dataframe["close"].shift(-label_period).rolling(label_period).mean() / dataframe["close"]
        ) - 1
        return dataframe