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
    timeframe = "15m"  # CHẾ ĐỘ CẠO VẢY
    can_short = True

    # --- KIẾN TRÚC BẢO VỆ TÀI SẢN ---
    stoploss = -0.15 # Ngắn hơn
    use_custom_stoploss = True
    trailing_stop = False

    # ĐÁNH NHANH THẮNG NHANH (Tính bằng Phút)
    minimal_roi = {
        "0": 0.40,    # Lãi 40% (ký quỹ) mới chốt thẳng
        "1440": 0.15, # Sau 1 ngày mới hạ chuẩn chốt
        "2880": 0     # Sau 2 ngày hòa vốn rút lui
    }

    protections = [
        {"method": "CooldownPeriod", "stop_duration_candles": 4} # Dính SL nghỉ 1 tiếng
    ]

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str, side: str,
                 **kwargs) -> float:
        return 3.0  # Hạ đòn bẩy xuống 3x để phù hợp với khung ngắn, giảm nhiễu

    # --- HỘP SỐ CẮT LỖ FAIL-FAST & GỒNG LÃI VĨ MÔ ---
    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        
        # Lấy data 15m để cắt lỗ ngắn
        dataframe_15m, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(dataframe_15m) == 0: return -0.05
        atr_15m_pct = dataframe_15m.iloc[-1]['atr'] / current_rate

        # Lấy data 1H để gồng lãi dài
        dataframe_1h, _ = self.dp.get_analyzed_dataframe(pair, "1h") 
        if len(dataframe_1h) == 0: return -0.05
        atr_1h_pct = dataframe_1h.iloc[-1]['atr'] / current_rate

        # 1. INITIAL STOPLOSS: Cắt lỗ cực ngắn dựa trên 15m (Tối đa 6%)
        # Cắt đứt hoàn toàn tình trạng gồng lỗ sâu
        initial_stop = max(min(atr_15m_pct * 2.0, 0.06), 0.02)
        
        # 2. KHÓA LÃI VĨ MÔ (Bám theo sóng 1H)
        activation_bos = max(atr_1h_pct * 2.5, 0.05) # Lãi trên 5% mới kéo Stoploss
        
        if current_profit > activation_bos:
            return -abs(atr_1h_pct * 1.2) # Thả lỏng cho giá thở bằng biên độ 1H

        return -abs(initial_stop)

    # --- BỘ CẤP DỮ LIỆU ĐA CHIỀU ---
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, "1h") for pair in pairs] # Radar Vĩ Mô là 1H

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
        horizon = 24 # AI dự phóng 24 nến 15m (6 tiếng)
        future_high = dataframe['high'].rolling(horizon).max().shift(-horizon)
        future_low = dataframe['low'].rolling(horizon).min().shift(-horizon)
        max_gain = (future_high - dataframe['close']) / dataframe['close']
        max_loss = (dataframe['close'] - future_low) / dataframe['close']
        dataframe['&-rr_score'] = max_gain - (max_loss * 2.0) # Phạt rủi ro nặng hơn
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
        inf_df['atr'] = ta.ATR(inf_df, timeperiod=14)
        dataframe = merge_informative_pair(dataframe, inf_df, self.timeframe, "1h", ffill=True)

        # 2. MICRO 15m
        dataframe['ema_7'] = ta.EMA(dataframe, timeperiod=7)   # <-- Thêm mới
        dataframe['ema_25'] = ta.EMA(dataframe, timeperiod=25) # <-- Thêm mới
        dataframe['ema_10'] = ta.EMA(dataframe, timeperiod=10)
        dataframe['ema_50'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['ema_200'] = ta.EMA(dataframe, timeperiod=200)
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14) 
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        
        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']
        
        bb = ta.BBANDS(dataframe, timeperiod=20)
        dataframe['bb_upperband'] = bb['upperband']
        dataframe['bb_lowerband'] = bb['lowerband']

        # 3. VOLUME & LIQUIDITY (96 nến 15m = 24h)
        typical_price = (dataframe['high'] + dataframe['low'] + dataframe['close']) / 3
        dataframe['vwap_24h'] = (dataframe['volume'] * typical_price).rolling(window=96).sum() / dataframe['volume'].rolling(window=96).sum()
        dataframe['volume_mean'] = dataframe['volume'].rolling(window=40).mean()

        # 4. MARKET STRUCTURE
        dataframe['candle_body'] = abs(dataframe['close'] - dataframe['open'])
        dataframe['avg_candle_body'] = dataframe['candle_body'].rolling(window=40).mean()
        dataframe['local_high'] = dataframe['high'].rolling(window=20).max().shift(1)
        dataframe['local_low'] = dataframe['low'].rolling(window=20).min().shift(1)

        dataframe = self.freqai.start(dataframe, metadata, self)
        return dataframe

    # --- LÕI TÁC CHIẾN (ENTRY) ---
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

        # KÍCH HOẠT ĐỘNG LƯỢNG
        momentum_ignition = (
            (dataframe['candle_body'] > dataframe['avg_candle_body'] * 1.15) & 
            (dataframe['candle_body'] < dataframe['avg_candle_body'] * 4.0) & 
            (dataframe['volume'] > dataframe['volume_mean'])
        )

        # LA BÀN VĨ MÔ 1H
        macro_uptrend = (
            (dataframe['ema_50_1h'] > dataframe['ema_200_1h']) &
            (dataframe['plus_di_1h'] > dataframe['minus_di_1h']) & 
            (dataframe['adx_1h'] > 20) 
        )
        macro_downtrend = (
            (dataframe['close'] < dataframe['ema_100_1h']) &
            (dataframe['minus_di_1h'] > dataframe['plus_di_1h']) & 
            (dataframe['adx_1h'] > 20) 
        )

        # BỘ LỌC CHỐNG FOMO (ĐÃ ĐƯỢC TỐI ƯU CHO SIÊU SÓNG)
        # Nới RSI lên 75/25 để bắt được các nhịp Pullback trong Trend cực mạnh.
        # Cho phép giá liếm nhẹ ra ngoài dải Band (1%) nhưng không được đâm thủng quá sâu.
        no_fomo_long = (
            (dataframe['rsi'] < 75) & 
            (dataframe['close'] <= (dataframe['bb_upperband'] * 1.01))
        )
        no_fomo_short = (
            (dataframe['rsi'] > 25) & 
            (dataframe['close'] >= (dataframe['bb_lowerband'] * 0.99))
        )

        # --- SÁT THỦ BẮT ĐÁY / BÁN ĐỈNH SIÊU TỐC ---
        # Bóp cò ngay khi MACD tạo đáy V-shape và Giá vừa nhú qua EMA 7 (Không chờ cắt EMA 25)
        macd_reversal_long = (
            (dataframe['macdhist'] > dataframe['macdhist'].shift(1)) & 
            (dataframe['macdhist'].shift(1) < dataframe['macdhist'].shift(2)) &
            (dataframe['close'] > dataframe['ema_7']) # Xác nhận nến đã xanh và nảy lên
        )
        
        macd_reversal_short = (
            (dataframe['macdhist'] < dataframe['macdhist'].shift(1)) & 
            (dataframe['macdhist'].shift(1) > dataframe['macdhist'].shift(2)) &
            (dataframe['close'] < dataframe['ema_7']) # Xác nhận nến đã đỏ và gãy xuống
        )

        # 🎯 BOS SNIPER - TỐI ƯU HÓA BẮT ĐÁY (BOTTOM FISHER)
        long_bos_cond = (
            common_cond & risk_filter & 
            (dataframe['close'] > dataframe['vwap_24h']) & # Vẫn giữ VWAP làm khiên bảo vệ
            macd_reversal_long &   # Sử dụng Tín hiệu bắt đáy MACD
            no_fomo_long &         
            (dataframe[predict_col] > 0.002) # Hạ ngưỡng AI xuống cực thấp (0.2%) để không cản trở nhịp nảy
        )

        short_bos_cond = (
            common_cond & risk_filter & 
            (dataframe['close'] < dataframe['vwap_24h']) & 
            macd_reversal_short & 
            no_fomo_short & 
            (dataframe[predict_col] < -0.002)
        )

        dataframe.loc[long_bos_cond, ['enter_long', 'enter_tag']] = (1, 'long_bos_sniper')
        dataframe.loc[short_bos_cond, ['enter_short', 'enter_tag']] = (1, 'short_bos_sniper')

        # ==========================================
        # 🧭 V6.2 X-RAY TELEMETRY (SÁT THỦ BẮT ĐÁY)
        # ==========================================
        if True:
            curr_close = dataframe['close'].iloc[last_idx]
            curr_vwap = dataframe['vwap_24h'].iloc[last_idx]
            curr_rsi = dataframe['rsi'].iloc[last_idx]
            
            # Khung xu hướng vẫn mượn EMA 7 và 25 để xác định vị thế
            is_up = dataframe['ema_7'].iloc[last_idx] > dataframe['ema_25'].iloc[last_idx]
            is_down = dataframe['ema_7'].iloc[last_idx] < dataframe['ema_25'].iloc[last_idx]
            
            ai_score = dataframe[predict_col].iloc[last_idx] if predict_col in dataframe.columns else 0.0
            
            logger.warning(f"")
            logger.warning(f"========== 🧭 V6.2 X-RAY (SÁT THỦ BẮT ĐÁY): TÌNH TRẠNG BOT ({metadata['pair']}) 🧭 ==========")
            
            if is_up:
                # LUỒNG UPTREND -> TÌM ĐÁY MUA LÊN (LONG)
                vwap_ok = "✅ THỎA MÃN (Giá > VWAP 24h)" if curr_close > curr_vwap else "🔴 BỊ PHỦ QUYẾT (Ngược dòng tiền)"
                fomo_ok = f"✅ CHỜ ĐIỀU CHỈNH (RSI: {curr_rsi:.1f})" if no_fomo_long.iloc[last_idx] else f"🔴 QUÁ NÓNG/ĐU ĐỈNH (RSI: {curr_rsi:.1f})"
                macd_long_ok = "🔥 TẠO ĐÁY CHỮ V (MACD ngóc lên)" if macd_reversal_long.iloc[last_idx] else "⏳ CHỜ MACD TẠO ĐÁY"
                ai_ok = "✅ THỎA MÃN (> 0.002)" if ai_score > 0.002 else "🔴 BỊ PHỦ QUYẾT (Kỳ vọng lợi nhuận thấp)"
                
                logger.warning(f"► 1. TỐC ĐỘ CAO (15m): 🟢 UPTREND (EMA 7 > 25) -> CANH LỆNH [LONG] 🚀")
                logger.warning(f"► 2. TRỌNG TÀI DÒNG TIỀN: {vwap_ok} | Giá Live: {curr_close:.2f} / VWAP: {curr_vwap:.2f}")
                logger.warning(f"► 3. CHỐNG FOMO: {fomo_ok}")
                logger.warning(f"► 4. ĐIỂM BÓP CÒ: {macd_long_ok}")
                logger.warning(f"► 5. BỘ NÃO AI: {ai_ok} | Điểm hiện tại: {ai_score:.4f}")
                
            elif is_down:
                # LUỒNG DOWNTREND -> TÌM ĐỈNH BÁN XUỐNG (SHORT)
                vwap_ok = "✅ THỎA MÃN (Giá < VWAP 24h)" if curr_close < curr_vwap else "🔴 BỊ PHỦ QUYẾT (Ngược dòng tiền)"
                fomo_ok = f"✅ CHỜ ĐIỀU CHỈNH (RSI: {curr_rsi:.1f})" if no_fomo_short.iloc[last_idx] else f"🔴 QUÁ LẠNH/ĐU ĐÁY (RSI: {curr_rsi:.1f})"
                macd_short_ok = "🩸 TẠO ĐỈNH THÀNH CÔNG (MACD cắm mỏ)" if macd_reversal_short.iloc[last_idx] else "⏳ CHỜ MACD TẠO ĐỈNH"
                ai_ok = "✅ THỎA MÃN (< -0.002)" if ai_score < -0.002 else "🔴 BỊ PHỦ QUYẾT (Kỳ vọng lợi nhuận thấp)"
                
                logger.warning(f"► 1. TỐC ĐỘ CAO (15m): 🔴 DOWNTREND (EMA 7 < 25) -> CANH LỆNH [SHORT] 🩸")
                logger.warning(f"► 2. TRỌNG TÀI DÒNG TIỀN: {vwap_ok} | Giá Live: {curr_close:.2f} / VWAP: {curr_vwap:.2f}")
                logger.warning(f"► 3. CHỐNG FOMO: {fomo_ok}")
                logger.warning(f"► 4. ĐIỂM BÓP CÒ: {macd_short_ok}")
                logger.warning(f"► 5. BỘ NÃO AI: {ai_ok} | Điểm hiện tại: {ai_score:.4f}")
                
            else:
                # LUỒNG SIDEWAY
                logger.warning(f"► 1. TỐC ĐỘ CAO (15m): 🟡 SIDEWAY (EMA 7 chập EMA 25) -> BOT ĐI NGỦ 💤")
            
            logger.warning(f"===========================================================")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, ['exit_long', 'exit_short']] = 0
        return dataframe