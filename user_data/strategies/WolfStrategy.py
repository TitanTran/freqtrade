import logging
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame
import talib.abstract as ta
from datetime import datetime
from freqtrade.persistence import Trade
import numpy as np

logger = logging.getLogger(__name__)

class WolfStrategy(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True

    # --- KIẾN TRÚC BẢO VỆ TÀI SẢN ---
    stoploss = -0.15 # Cầu chì Black Swan
    use_custom_stoploss = True
    trailing_stop = False

    minimal_roi = {
        "0": 0.10,    # Chốt 10% ngay lập tức nếu giá bơm điên rồ
        "60": 0.05,   
        "120": 0.02,
        "240": 0      
    }

    protections = [
        {"method": "CooldownPeriod", "stop_duration_candles": 12}
    ]

    # --- CẤU HÌNH ĐÒN BẨY (LEVERAGE) ---
    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str, side: str,
                 **kwargs) -> float:
        return 5.0  # Nâng đòn bẩy lên 5x để tối ưu hóa vốn vì Drawdown đang rất thấp

    # --- HỘP SỐ BÁM ĐUÔI (DIAMOND HANDS V4) ---
    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(dataframe) == 0: return -0.05
        last_candle = dataframe.iloc[-1].squeeze()
        atr_pct = last_candle['atr'] / current_rate

        # 1. INITIAL STOPLOSS: Nới rộng lên 3.5*ATR để sống sót qua nhịp giật râu (Whipsaw)
        dynamic_stop_pct = max(min(atr_pct * 3.5, 0.12), 0.03)
        dynamic_stop_pct = -abs(dynamic_stop_pct)

        # 2. BÁM ĐUÔI THEO CẤU TRÚC: CHỈ GỒNG KHI LÃI ĐẬM
        activation_bos = max(atr_pct * 6.0, 0.05) 
        if current_profit > activation_bos:
            return -abs(atr_pct * 3.0) 
        elif current_profit > (activation_bos * 0.6):
            return -abs(atr_pct * 4.0)

        # 3. CẦU CHÌ FAIL-FAST
        time_held = (current_time - trade.open_date_utc).total_seconds()
        if time_held > 5400 and current_profit < -abs(atr_pct): return -0.0001
        
        return dynamic_stop_pct

    # --- BỘ CẤP DỮ LIỆU ĐA CHIỀU (FEATURE ENGINEERING) ---
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, "1h") for pair in pairs]

    def feature_engineering_expand_all(self, dataframe: DataFrame, period: int, metadata: dict, **kwargs) -> DataFrame:
        dataframe["%-rsi-" + str(period)] = ta.RSI(dataframe, timeperiod=period)
        dataframe["%-mfi-" + str(period)] = ta.MFI(dataframe, timeperiod=period)
        dataframe["%-adx-" + str(period)] = ta.ADX(dataframe, timeperiod=period)
        
        bb = ta.BBANDS(dataframe, timeperiod=period)
        dataframe["%-bb_width-" + str(period)] = (bb['upperband'] - bb['lowerband']) / bb['middleband']
        dataframe["%-obv-" + str(period)] = ta.OBV(dataframe['close'], dataframe['volume'])
        dataframe["%-ad_line-" + str(period)] = ta.AD(dataframe['high'], dataframe['low'], dataframe['close'], dataframe['volume'])
        return dataframe

    def feature_engineering_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        horizon = 12
        future_high = dataframe['high'].rolling(horizon).max().shift(-horizon)
        future_low = dataframe['low'].rolling(horizon).min().shift(-horizon)
        max_gain = (future_high - dataframe['close']) / dataframe['close']
        max_loss = (dataframe['close'] - future_low) / dataframe['close']
        dataframe['&-rr_score'] = max_gain - (max_loss * 2.0)
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        return self.feature_engineering_targets(dataframe, metadata, **kwargs)

    # --- KHỞI TẠO CHỈ BÁO & LÀM SẠCH DỮ LIỆU ---
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 1. MACRO 1H
        inf_df = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe="1h")
        inf_df['ema_50'] = ta.EMA(inf_df, timeperiod=50)
        inf_df['ema_100'] = ta.EMA(inf_df, timeperiod=100)
        inf_df['ema_200'] = ta.EMA(inf_df, timeperiod=200) 
        inf_df['rsi'] = ta.RSI(inf_df, timeperiod=14)
        inf_df['plus_di'] = ta.PLUS_DI(inf_df, timeperiod=14)
        inf_df['minus_di'] = ta.MINUS_DI(inf_df, timeperiod=14)
        inf_df['adx'] = ta.ADX(inf_df, timeperiod=14)
        dataframe = merge_informative_pair(dataframe, inf_df, self.timeframe, "1h", ffill=True)

        # 2. MICRO 5m
        dataframe['ema_200'] = ta.EMA(dataframe, timeperiod=200)
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14) 
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)

        # 3. VOLUME & LIQUIDITY (SMART MONEY)
        typical_price = (dataframe['high'] + dataframe['low'] + dataframe['close']) / 3
        dataframe['vwap_24h'] = (dataframe['volume'] * typical_price).rolling(window=288).sum() / dataframe['volume'].rolling(window=288).sum()
        dataframe['volume_mean'] = dataframe['volume'].rolling(window=20).mean()

        # ==========================================
        # 🛡️ V4: MOMENTUM IGNITION & MARKET STRUCTURE 
        # ==========================================
        dataframe['candle_body'] = abs(dataframe['close'] - dataframe['open'])
        dataframe['avg_candle_body'] = dataframe['candle_body'].rolling(window=20).mean()

        # Dò tìm Đỉnh (HH) / Đáy (LL) cục bộ trong 10 nến
        dataframe['local_high'] = dataframe['high'].rolling(window=10).max().shift(1)
        dataframe['local_low'] = dataframe['low'].rolling(window=10).min().shift(1)

        # Nạp dữ liệu vào AI
        dataframe = self.freqai.start(dataframe, metadata, self)
        return dataframe

    # --- LÕI TÁC CHIẾN DUY NHẤT (ENTRY) ---
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        import logging
        logger = logging.getLogger(__name__)
        predict_col = '&-rr_score' 
        dataframe['enter_long'] = 0
        dataframe['enter_short'] = 0

        if predict_col not in dataframe.columns: return dataframe

        last_idx = -1
        common_cond = dataframe[predict_col].notnull()
        risk_filter = (dataframe['atr'] < (dataframe['close'] * 0.025))

        # =======================================================
        # KÍCH HOẠT ĐỘNG LƯỢNG (MOMENTUM IGNITION) - NỚI LỎNG V4.1
        # Hạ hệ số bạo lực từ 1.5 xuống 1.15 để chớp thời cơ nhanh hơn
        # =======================================================
        momentum_ignition = (
            (dataframe['candle_body'] > dataframe['avg_candle_body'] * 1.15) & 
            (dataframe['candle_body'] < dataframe['avg_candle_body'] * 3.5) & 
            (dataframe['volume'] > dataframe['volume_mean'])
        )

        # LA BÀN VĨ MÔ
        macro_uptrend = (
            (dataframe['ema_50_1h'] > dataframe['ema_200_1h']) |
            ((dataframe['plus_di_1h'] > dataframe['minus_di_1h']) & (dataframe['adx_1h'] > 20))
        )
        macro_downtrend = (
            (dataframe['close'] < dataframe['ema_100_1h']) &
            (dataframe['minus_di_1h'] > dataframe['plus_di_1h']) & 
            (dataframe['adx_1h'] > 25)
        )

        # =======================================================
        # 🎯 BOS SNIPER (SĂN CẤU TRÚC PHÁ VỠ) - NỚI LỎNG V4.1
        # =======================================================
        long_bos_cond = (
            common_cond & risk_filter & momentum_ignition & macro_uptrend & 
            (dataframe['close'] > dataframe['vwap_24h']) & 
            (dataframe['close'] > dataframe['local_high']) & 
            (dataframe[predict_col] > 0.003) # Hạ ngưỡng AI từ 0.005 xuống 0.003
        )

        short_bos_cond = (
            common_cond & risk_filter & momentum_ignition & macro_downtrend & 
            (dataframe['close'] < dataframe['vwap_24h']) & 
            (dataframe['close'] < dataframe['local_low']) & 
            (dataframe[predict_col] < -0.003) # Hạ ngưỡng AI từ -0.005 xuống -0.003
        )

        dataframe.loc[long_bos_cond, ['enter_long', 'enter_tag']] = (1, 'long_bos_sniper')
        dataframe.loc[short_bos_cond, ['enter_short', 'enter_tag']] = (1, 'short_bos_sniper')

        # ==========================================
        # 🧭 V4 X-RAY TELEMETRY 
        # ==========================================
        if metadata['pair'] == 'BTC/USDT:USDT':
            curr_close = dataframe['close'].iloc[last_idx]
            curr_ll = dataframe['local_low'].iloc[last_idx]
            curr_hh = dataframe['local_high'].iloc[last_idx]
            
            status_s = "🔴 CHỜ PHÁ ĐÁY" if curr_close > curr_ll else "✅ ĐÃ PHÁ ĐÁY"
            status_l = "🟢 CHỜ PHÁ ĐỈNH" if curr_close < curr_hh else "✅ ĐÃ PHÁ ĐỈNH"
            macro_status = "🟢 UPTREND" if macro_uptrend.iloc[last_idx] else ("🔴 DOWNTREND" if macro_downtrend.iloc[last_idx] else "🟡 SIDEWAY")
            
            logger.warning(f"")
            logger.warning(f"========== 🧭 V4 GHOST HUNTER {metadata['pair']} 🧭 ==========")
            logger.warning(f"► 1. LA BÀN VĨ MÔ: {macro_status}")
            logger.warning(f"► 2. TRẠNG THÁI DÒNG TIỀN (VWAP 24H): {dataframe['vwap_24h'].iloc[last_idx]:.2f}")
            logger.warning(f"► 3. CẤU TRÚC: SHORT ({status_s} | LL: {curr_ll:.2f}) || LONG ({status_l} | HH: {curr_hh:.2f})")
            logger.warning(f"► 4. MOMENTUM IGNITION: {'🔥 KÍCH HOẠT' if momentum_ignition.iloc[last_idx] else '💤 Đang nén'}")
            logger.warning(f"===========================================================")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, ['exit_long', 'exit_short']] = 0
        return dataframe