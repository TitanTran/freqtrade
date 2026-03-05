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

    # --- KIẾN TRÚC BẢO VỆ TÀI SẢN (DRY-RUN BASELINE) ---
    # Đòn bẩy 3x -> Stoploss -5% nghĩa là thực tế bạn chịu rủi ro -15% vốn/lệnh
    stoploss = -0.05 
    use_custom_stoploss = True
    
    # Trailing Stop: Gồng lãi sát nút hơn để chống Whipsaw
    trailing_stop = True
    trailing_stop_positive = 0.02        # Lãi 2% mới kích hoạt bám đuôi
    trailing_stop_positive_offset = 0.03 # Bắt đầu bám từ mốc 3%
    trailing_only_offset_is_reached = True

    # Khấu hao kỳ vọng (Time-decay ROI): Càng ôm lệnh lâu, càng dễ dính bẫy
    minimal_roi = {
        "0": 0.06,    # Chốt ngay 6% nếu có cú Squeeze giật râu nến
        "30": 0.03,   # Giữ 30 phút -> Kỳ vọng giảm còn 3%
        "60": 0.015,  # Giữ 1 tiếng -> Ăn 1.5% là té
        "120": 0      # Sau 2 tiếng không bay nổi -> Hòa vốn (0%) là xả hàng
    }

    # Cơ chế Tản nhiệt chống Revenge Trading
    protections = [
        {"method": "CooldownPeriod", "stop_duration_candles": 12}
    ]

    # --- 1.5 CẤU HÌNH ĐÒN BẨY (LEVERAGE) ---
    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str, side: str,
                 **kwargs) -> float:
        """
        Khai báo đòn bẩy cứng cho mọi lệnh.
        """
        return 3.0  # Cố định đòn bẩy 3x

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

    def feature_engineering_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        """
        SINGLE-TARGET EXPLICIT LABELING
        Ép FreqAI ghi đè mọi cấu hình mặc định, chỉ học 1 mục tiêu duy nhất.
        """
        horizon = 12
        future_high = dataframe['high'].rolling(horizon).max().shift(-horizon)
        future_low = dataframe['low'].rolling(horizon).min().shift(-horizon)
        
        max_gain = (future_high - dataframe['close']) / dataframe['close']
        max_loss = (dataframe['close'] - future_low) / dataframe['close']
        
        # Tiền tố &- là bắt buộc để FreqAI nhận diện đây là Nhãn mục tiêu
        dataframe['&-rr_score'] = max_gain - (max_loss * 2.0)
        
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        """
        SINGLE-TARGET EXPLICIT LABELING
        Ép FreqAI ghi đè mọi cấu hình mặc định, chỉ học 1 mục tiêu duy nhất.
        """
        horizon = 12
        future_high = dataframe['high'].rolling(horizon).max().shift(-horizon)
        future_low = dataframe['low'].rolling(horizon).min().shift(-horizon)
        
        max_gain = (future_high - dataframe['close']) / dataframe['close']
        max_loss = (dataframe['close'] - future_low) / dataframe['close']
        
        # Tiền tố &- là bắt buộc để FreqAI nhận diện đây là Nhãn mục tiêu
        dataframe['&-rr_score'] = max_gain - (max_loss * 2.0)
        
        return dataframe

    # --- 4. TRIPLE CONFIRMATION & CẦU CHÌ BẢO VỆ ---
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Macro Filter (1H)
        inf_df = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe="1h")
        inf_df['ema_100'] = ta.EMA(inf_df, timeperiod=100)
        inf_df['rsi'] = ta.RSI(inf_df, timeperiod=14)
        inf_df['adx'] = ta.ADX(inf_df, timeperiod=14)
        dataframe = merge_informative_pair(dataframe, inf_df, self.timeframe, "1h", ffill=True)

        # Micro Filter (5m)
        dataframe['ema_200'] = ta.EMA(dataframe, timeperiod=200)
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14) 
        macd = ta.MACD(dataframe)
        dataframe['macdhist'] = macd['macdhist']
        dataframe['mfi'] = ta.MFI(dataframe, timeperiod=14)

        # Đánh thức Trí tuệ Nhân tạo
        dataframe = self.freqai.start(dataframe, metadata, self)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        import logging
        logger = logging.getLogger(__name__)
        
        # ==========================================
        # SỰ THẬT VỀ FREQAI: GHI ĐÈ TRỰC TIẾP (IN-PLACE PREDICTION)
        # Tên cột dự đoán CHÍNH LÀ tên cột Nhãn (Label) mà ta đã định nghĩa
        # ==========================================
        predict_col = '&-rr_score' 

        # Khởi tạo mặc định
        dataframe['enter_long'] = 0
        dataframe['enter_short'] = 0

        if predict_col not in dataframe.columns:
            logger.warning(f"🚨 FATAL: Cột {predict_col} KHÔNG TỒN TẠI!")
            return dataframe

        common_cond = (dataframe['do_predict'] == 1)
        risk_filter = (dataframe['atr'] < (dataframe['close'] * 0.025))

        long_cond = (
            common_cond & risk_filter &
            (dataframe['adx_1h'] > 25) & 
            (dataframe['close'] > dataframe['ema_200']) & 
            (dataframe['close'] > dataframe['ema_100_1h']) & 
            (dataframe['macdhist'] > dataframe['macdhist'].shift(1)) & 
            (dataframe['mfi'] < 80) & 
            (dataframe['rsi_1h'] > 30) & 
            (dataframe[predict_col] > 0.002) & 
            (dataframe['volume'] > 0)
        )
        dataframe.loc[long_cond, ['enter_long', 'enter_tag']] = (1, 'long_mtf_v4.5')

        short_cond = (
            common_cond & risk_filter &
            (dataframe['adx_1h'] > 25) & 
            (dataframe['close'] < dataframe['ema_200']) & 
            (dataframe['close'] < dataframe['ema_100_1h']) & 
            (dataframe['macdhist'] < dataframe['macdhist'].shift(1)) & 
            (dataframe['mfi'] > 20) & 
            (dataframe['rsi_1h'] < 70) & 
            (dataframe[predict_col] < -0.002) & 
            (dataframe['volume'] > 0)
        )
        dataframe.loc[short_cond, ['enter_short', 'enter_tag']] = (1, 'short_mtf_v4.5')
        
        # CẢM BIẾN BOTTLENECK CHẠY BẰNG WARNING
        if metadata['pair'] == 'BTC/USDT:USDT':
            total_candles = len(dataframe)
            cond_ai_ready = (dataframe['do_predict'] == 1).sum()
            cond_risk = risk_filter.sum()
            cond_adx = (dataframe['adx_1h'] > 25).sum()
            cond_ema_200 = (dataframe['close'] > dataframe['ema_200']).sum()
            cond_ema_100 = (dataframe['close'] > dataframe['ema_100_1h']).sum()
            cond_macd = (dataframe['macdhist'] > dataframe['macdhist'].shift(1)).sum()
            cond_mfi = (dataframe['mfi'] < 80).sum()
            cond_rsi = (dataframe['rsi_1h'] > 30).sum()
            cond_ai_score = (dataframe[predict_col] > 0.002).sum()
            
            max_ai_score = dataframe[predict_col].max()
            min_ai_score = dataframe[predict_col].min()

            logger.warning(f"")
            logger.warning(f"--- 🚨 BOTTLENECK ANALYSIS FOR BTC 🚨 ---")
            logger.warning(f"Tổng số nến khảo sát: {total_candles}")
            logger.warning(f"1. AI Ready (do_predict = 1): {cond_ai_ready} / {total_candles}")
            logger.warning(f"2. Risk Filter (ATR): {cond_risk} / {total_candles}")
            logger.warning(f"3. Vĩ mô ADX > 25: {cond_adx} / {total_candles}")
            logger.warning(f"4. Xu hướng > EMA200: {cond_ema_200} / {total_candles}")
            logger.warning(f"5. Xu hướng > EMA100_1H: {cond_ema_100} / {total_candles}")
            logger.warning(f"6. Động lượng MACD tăng: {cond_macd} / {total_candles}")
            logger.warning(f"7. Chống FOMO (MFI < 80): {cond_mfi} / {total_candles}")
            logger.warning(f"8. Đáy an toàn (RSI > 30): {cond_rsi} / {total_candles}")
            logger.warning(f"9. Điểm AI > 0.002: {cond_ai_score} / {total_candles}")
            logger.warning(f"-> ĐIỂM AI CAO NHẤT THỰC TẾ: {max_ai_score:.6f}")
            logger.warning(f"-> ĐIỂM AI THẤP NHẤT THỰC TẾ: {min_ai_score:.6f}")
            logger.warning(f"---------------------------------------")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, ['exit_long', 'exit_short']] = 0
        return dataframe
