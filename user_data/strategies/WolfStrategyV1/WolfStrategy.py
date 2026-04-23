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
    timeframe = "15m"  # SCALPING MODE
    can_short = True

    # --- V5.90: THE PROPHET WOLF (SUPER TREND) ---
    stoploss = -0.12  # 12% price floor (60% margin) to survive MM shakeouts
    use_custom_stoploss = False
    trailing_stop = False

    # MINIMAL ROI (V5.71 - Sovereign Mode)
    # Vô hiệu hóa chốt lời tự động để ép Bot gồng lãi theo xu hướng 1H
    minimal_roi = {
        "0": 10.0      # 1000% margin profit (impossible to reach)
    }
    protections = [
        {"method": "CooldownPeriod", "stop_duration_candles": 4}  # Cool down after SL
    ]

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str,
        side: str,
        **kwargs,
    ) -> float:
        return 5.0  # 5x Leverage

    # --- VISUALIZATION CONFIGURATION ---
    plot_config = {
        "main_plot": {
            "ema_7": {"color": "#ff5733"},   # Fast Trend (Red)
            "ema_25": {"color": "#335bff"},  # Mid Trend (Blue)
            "ema_50": {"color": "#33ff57"},  # Confirmation (Green)
            "sma_200": {"color": "#ffc133"}, # Macro Safety (Orange)
            "vwap_24h": {"color": "#ffffff"}, # Anchor (White)
        },
        "subplots": {
            "RSI": {
                "rsi": {"color": "#9b33ff"}
            },
            "MACD": {
                "macd": {"color": "#335bff"},
                "macdsignal": {"color": "#ff5733"},
                "macdhist": {"type": "bar", "color": "#808080"}
            }
        }
    }

    # ==========================================
    # --- DYNAMIC RISK MANAGEMENT (TIERED GEARBOX) ---
    # ==========================================
    def custom_exit(self, pair: str, trade: 'Trade', current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs) -> bool:
        
        # --- V5.90: PROPHET PROFIT MANAGEMENT ---
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) == 0:
            return False
        last_candle = dataframe.iloc[-1]
        
        # 🛡️ TREND STRENGTH PROTECTION (Bảo vệ siêu xu hướng)
        # Nếu ADX > 30, xu hướng cực mạnh -> KHÔNG ĐƯỢC THOÁT LỆNH.
        if last_candle["adx"] > 30:
            return False

        # 1. HYPER EXHAUSTION (Chốt đỉnh bong bóng)
        # Chỉ chốt khi lãi > 10% và hưng phấn tột độ MFI > 95
        if current_profit > 0.10 and last_candle["mfi"] > 95:
            return "prophet_hyper_peak"

        # 2. TREND BREAK PROTECTION (Bảo vệ lãi khi gãy trend)
        # Nếu đã lãi trên 5% nhưng giá rớt dưới EMA 25 -> Thoát
        if current_profit > 0.05 and last_candle["close"] < last_candle["ema_25"]:
             return "trend_break_exit"

        return False

    # --- MULTI-DIMENSIONAL DATA PROVISIONING ---
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return ([(pair, "1h") for pair in pairs] + 
                [(pair, "4h") for pair in pairs] + 
                [(pair, "1d") for pair in pairs] + 
                [(pair, "1w") for pair in pairs])

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        dataframe["%-rsi-" + str(period)] = ta.RSI(dataframe, timeperiod=period)
        dataframe["%-mfi-" + str(period)] = ta.MFI(dataframe, timeperiod=period)
        dataframe["%-adx-" + str(period)] = ta.ADX(dataframe, timeperiod=period)

        bb = ta.BBANDS(dataframe, timeperiod=period)
        dataframe["%-bb_width-" + str(period)] = (bb["upperband"] - bb["lowerband"]) / bb[
            "middleband"
        ]
        dataframe["%-obv-" + str(period)] = ta.OBV(dataframe["close"], dataframe["volume"])
        dataframe["%-ad_line-" + str(period)] = ta.AD(
            dataframe["high"], dataframe["low"], dataframe["close"], dataframe["volume"]
        )
        return dataframe

    def feature_engineering_targets(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        horizon = 24  # Forward look 24 candles
        future_high = dataframe["high"].rolling(horizon).max().shift(-horizon)
        future_low = dataframe["low"].rolling(horizon).min().shift(-horizon)
        max_gain = (future_high - dataframe["close"]) / dataframe["close"]
        max_loss = (dataframe["close"] - future_low) / dataframe["close"]
        dataframe["&-rr_score"] = max_gain - (max_loss * 2.0)  # Heavy penalty for risk
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        return self.feature_engineering_targets(dataframe, metadata, **kwargs)

    # --- INDICATORS & DATA CLEANSING ---
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 1. MACRO 4H (The Tide - V5.33 Enhanced)
        inf_4h = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="4h")
        inf_4h["ema_20"] = ta.EMA(inf_4h, timeperiod=20)
        inf_4h["ema_50"] = ta.EMA(inf_4h, timeperiod=50)
        inf_4h["ema_200"] = ta.EMA(inf_4h, timeperiod=200)
        
        # Bullish if Price > EMA 50 OR (EMA 20 > EMA 50 - momentum)
        inf_4h["macro_bullish"] = (inf_4h["close"] > inf_4h["ema_50"]) | (inf_4h["ema_20"] > inf_4h["ema_50"])
        
        # Strict Bearish: Only if Price < EMA 50 AND EMA 20 < EMA 50 AND Price < EMA 200
        inf_4h["macro_bearish"] = (inf_4h["close"] < inf_4h["ema_50"]) & (inf_4h["ema_20"] < inf_4h["ema_50"]) & (inf_4h["close"] < inf_4h["ema_200"])
        
        dataframe = merge_informative_pair(dataframe, inf_4h, self.timeframe, "4h", ffill=True)

        # 2. MACRO 1H (The Wave)
        # 1. MACRO 1h
        inf_df_1h = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="1h")
        inf_df_1h["ema_20"] = ta.EMA(inf_df_1h, timeperiod=20)
        inf_df_1h["ema_50"] = ta.EMA(inf_df_1h, timeperiod=50)
        inf_df_1h["adx"] = ta.ADX(inf_df_1h, timeperiod=14)
        dataframe = merge_informative_pair(dataframe, inf_df_1h, self.timeframe, "1h", ffill=True)

        # 2. MICRO 15m
        dataframe["ema_7"] = ta.EMA(dataframe, timeperiod=7)
        dataframe["ema_25"] = ta.EMA(dataframe, timeperiod=25)
        dataframe["ema_10"] = ta.EMA(dataframe, timeperiod=10)
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["sma_200"] = ta.SMA(dataframe, timeperiod=200)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        bb = ta.BBANDS(dataframe, timeperiod=20)
        dataframe["bb_upperband"] = bb["upperband"]
        dataframe["bb_lowerband"] = bb["lowerband"]

        # 3. VOLUME, LIQUIDITY & SMART MONEY COMPASS
        typical_price = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3
        dataframe["vwap_24h"] = (dataframe["volume"] * typical_price).rolling(
            window=96
        ).sum() / dataframe["volume"].rolling(window=96).sum()
        dataframe["volume_mean"] = dataframe["volume"].rolling(window=40).mean()

        dataframe["obv"] = ta.OBV(dataframe["close"], dataframe["volume"])
        dataframe["obv_ema_10"] = ta.EMA(dataframe["obv"], timeperiod=10)  # OBV Momentum Compass

        # 5. FLOW & MOMENTUM (V5.70 - PRECISION)
        dataframe["mfi"] = ta.MFI(dataframe, timeperiod=14)
        dataframe["mfi_low"] = dataframe["mfi"].rolling(window=20).min()
        dataframe["mfi_high"] = dataframe["mfi"].rolling(window=20).max()
        
        # --- V5.95: DIVERGENCE DETECTION ---
        # Phân kỳ MFI Low: Giá tạo đáy mới thấp hơn nhưng MFI tạo đáy cao hơn
        dataframe["mfi_low_divergence"] = np.where(
            (dataframe["low"] < dataframe["low"].shift(1)) & 
            (dataframe["mfi"] > dataframe["mfi"].shift(1)) & 
            (dataframe["mfi"] < 30), 1, 0
        )
        
        # Phân kỳ MFI High: Giá tạo đỉnh mới cao hơn nhưng MFI tạo đỉnh thấp hơn
        dataframe["mfi_high_divergence"] = np.where(
            (dataframe["high"] > dataframe["high"].shift(1)) & 
            (dataframe["mfi"] < dataframe["mfi"].shift(1)) & 
            (dataframe["mfi"] > 70), 1, 0
        )

        # 4. MARKET STRUCTURE & WICK ANALYSIS
        dataframe["candle_body"] = abs(dataframe["close"] - dataframe["open"])
        dataframe["lower_wick"] = np.where(dataframe["close"] > dataframe["open"], 
                                         dataframe["open"] - dataframe["low"], 
                                         dataframe["close"] - dataframe["low"])
        dataframe["upper_wick"] = np.where(dataframe["close"] > dataframe["open"], 
                                         dataframe["high"] - dataframe["close"], 
                                         dataframe["high"] - dataframe["open"])
                                         
        dataframe["avg_candle_body"] = dataframe["candle_body"].rolling(window=40).mean()
        # 2. LOCAL STRUCTURE (V5.41 - Wider Lookback)
        dataframe["local_high"] = dataframe["high"].rolling(window=30).max().shift(1)
        dataframe["local_low"] = dataframe["low"].rolling(window=30).min().shift(1)

        dataframe = self.freqai.start(dataframe, metadata, self)
        return dataframe

    # --- COMBAT CORE (ENTRY) ---
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # V5.83: TOTAL SOVEREIGNTY - NO TECHNICAL EXIT
        # Chúng ta không thoát theo chỉ báo kỹ thuật nữa để tránh chốt non.
        # Mọi quyết định thoát lệnh chốt lời nằm ở custom_exit.
        dataframe.loc[:, ["exit_long", "exit_short"]] = 0
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        import logging

        logger = logging.getLogger(__name__)
        predict_col = "&-rr_score"
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0

        if predict_col not in dataframe.columns:
            return dataframe

        last_idx = -1
        common_cond = dataframe[predict_col].notnull()
        
        # --- FILTERS & PROTECTIONS ---
        common_cond = (dataframe["volume"] > 0)
        
        risk_filter = (
            (dataframe["rsi"] < 75)                               # ⚡ V5.61: Loosened for Super Trends
            & (dataframe["close"] > dataframe["bb_lowerband"])
        )

        # ANTI-FOMO FILTERS (V5.61)
        no_fomo_long = (dataframe["rsi"] < 70) 
        no_fomo_short = (dataframe["rsi"] > 30)

        # ======================================================================
        # --- SMART INTERCEPTOR (V5.0 - EMA CROSSOVER & VOLUME EXPAND) ---
        # ==========================================
        import freqtrade.vendor.qtpylib.indicators as qtpylib

        smart_volume = (
            (dataframe["volume"] > dataframe["volume"].shift(1))
            & (dataframe["volume"] > dataframe["volume_mean"])
        )

        is_green_candle = dataframe["close"] > dataframe["open"]
        is_red_candle = dataframe["close"] < dataframe["open"]

        ema_cross_long = (
            qtpylib.crossed_above(dataframe["ema_7"], dataframe["ema_25"])
            & (dataframe["close"] > dataframe["ema_50"])
            & is_green_candle
            & smart_volume
        )

        ema_cross_short = (
            qtpylib.crossed_below(dataframe["ema_7"], dataframe["ema_25"])
            & (dataframe["close"] < dataframe["ema_50"])
            & is_red_candle
            & smart_volume
        )

        # --- DANGER FILTERS (ANTI-TRAP V5.10) ---
        # 1. Wick Trap: If candle has a long wick in opposite direction, it's a trap
        # V5.10: Strict ratio check - if wick > body, it's unstable
        long_wick_trap = (dataframe["upper_wick"] > dataframe["candle_body"])
        short_wick_trap = (dataframe["lower_wick"] > dataframe["candle_body"])
        
        # 2. Volume Climax: Extreme volume usually leads to reversal
        volume_climax = (dataframe["volume"] > (dataframe["volume_mean"] * 3.0))

        # 3. Overextension: If price is too far from EMA 7, wait for pullback
        long_overextended = (dataframe["close"] > (dataframe["ema_7"] * 1.015))
        short_overextended = (dataframe["close"] < (dataframe["ema_7"] * 0.985))

        # --- SMART MONEY COMPASS (OBV) ---
        obv_flowing_in = (dataframe["obv"] > dataframe["obv_ema_10"]) & (dataframe["obv"] > dataframe["obv"].shift(1))
        obv_flowing_out = (dataframe["obv"] < dataframe["obv_ema_10"]) & (dataframe["obv"] < dataframe["obv"].shift(1))

        # ======================================================================
        # 🎯 PRECISION REVERSAL SNIPER (V5.70 - THE ALPHA)
        # ======================================================================
        
        # 🟢 LONG PRECISION: Phân kỳ MFI + Quét đáy + Nến xanh xác nhận
        # (Giá phá đáy cũ nhưng MFI không phá đáy cũ -> Kiệt sức)
        long_precision_cond = (
            common_cond
            & (dataframe["low"] < dataframe["local_low"])         # ⚡ Quét đáy cũ
            & (dataframe["mfi"] > dataframe["mfi_low"])            # ⚡ Phân kỳ MFI (Divergence)
            & (dataframe["close"] > dataframe["open"])             # ⚡ Nến xanh xác nhận
            & (dataframe["volume"] > dataframe["volume_mean"])     # ⚡ Dòng tiền vào
            & (dataframe["rsi"] < 40)                              # ⚡ Vùng giá tốt
            & (dataframe[predict_col] > 0.0)
        )

        # 🔴 SHORT PRECISION: Phân kỳ MFI + Quét đỉnh + Nến đỏ xác nhận
        short_precision_cond = (
            common_cond
            & (dataframe["high"] > dataframe["local_high"])        # ⚡ Quét đỉnh cũ
            & (dataframe["mfi"] < dataframe["mfi_high"])           # ⚡ Phân kỳ MFI
            & (dataframe["close"] < dataframe["open"])             # ⚡ Nến đỏ xác nhận
            & (dataframe["volume"] > dataframe["volume_mean"])
            & (dataframe["rsi"] > 60)
            & (dataframe["macro_bearish_4h"])                      # ⚡ Chỉ Short khi xu hướng 4H cho phép
            & (dataframe[predict_col] < 0.0)
        )

        # 🎯 BOS SNIPER - TREND RIDER (STRICTER QUALITY)
        long_bos_cond = (
            common_cond
            & (dataframe["close"] > dataframe["ema_50_1h"])
            & (dataframe["ema_7"] > dataframe["ema_25"])
            & (dataframe["ema_25"] > dataframe["ema_50"])
            & (dataframe["volume"] > (dataframe["volume_mean"] * 1.5)) # ⚡ High quality only
            & (dataframe[predict_col] > 0.01)
        )

        short_bos_cond = (
            common_cond
            & dataframe["macro_bearish_4h"]
            & (dataframe["close"] < dataframe["ema_50"])
            & (dataframe["ema_7"] < dataframe["ema_25"])
            & (dataframe["volume"] > dataframe["volume_mean"])
            & (dataframe[predict_col] < -0.005)
        )

        # --- COMBAT CORE (ENTRY) ---
        long_precision_cond = (
            common_cond
            & (dataframe["mfi_low_divergence"] == 1)
            & (dataframe["close"] > dataframe["ema_25"])
            & (dataframe[predict_col] > 0.01)
        )
        
        short_precision_cond = (
            common_cond
            & (dataframe["mfi_high_divergence"] == 1)
            & (dataframe["close"] < dataframe["ema_25"])
            & (dataframe[predict_col] < -0.01)
        )

        # --- V5.90: PANIC SNIPER (Bắt đáy hoảng loạn) ---
        # Vào lệnh ngay khi có Volume đột biến và quét râu nến dưới
        long_panic_cond = (
            common_cond
            & (dataframe["volume"] > dataframe["volume_mean"] * 3) # Volume gấp 3 lần trung bình
            & (dataframe["low"] < dataframe["bb_lowerband"])       # Quét dưới Bollinger Band
            & (dataframe["close"] > dataframe["low"])              # Có lực rút chân
        )

        dataframe.loc[long_precision_cond, ["enter_long", "enter_tag"]] = (1, "precision_long_mfi")
        dataframe.loc[long_panic_cond, ["enter_long", "enter_tag"]] = (1, "panic_bottom_sniper")
        dataframe.loc[short_precision_cond, ["enter_short", "enter_tag"]] = (1, "precision_short_mfi")

        # ==========================================
        # 🧭 TELEMETRY X-RAY (STEALTH INTERCEPTOR)
        # ==========================================
        if True:
            curr_close = dataframe["close"].iloc[last_idx]
            curr_vwap = dataframe["vwap_24h"].iloc[last_idx]
            curr_rsi = dataframe["rsi"].iloc[last_idx]

            is_up = dataframe["ema_7"].iloc[last_idx] > dataframe["ema_25"].iloc[last_idx]
            is_down = dataframe["ema_7"].iloc[last_idx] < dataframe["ema_25"].iloc[last_idx]

            ai_score = (
                dataframe[predict_col].iloc[last_idx] if predict_col in dataframe.columns else 0.0
            )

            logger.warning(f"")
            logger.warning(
                f"========== 🧭 X-RAY RADAR: SNIPER V5.10 - SURVIVOR ARMOR ({metadata['pair']}) 🧭 =========="
            )

            if is_up:
                vwap_ok = (
                    "✅ VALID (Price > VWAP 24h)"
                    if curr_close > curr_vwap
                    else "🔴 REJECTED (Against VWAP)"
                )
                fomo_ok = (
                    f"✅ SAFE (RSI: {curr_rsi:.1f})"
                    if no_fomo_long.iloc[last_idx]
                    else f"🔴 DANGER/OVERBOUGHT (RSI: {curr_rsi:.1f})"
                )
                macd_long_ok = (
                    "🔥 VALID (Green Candle + Strong Vol)"
                    if ema_cross_long.iloc[last_idx]
                    else "⏳ WAITING EMA 7 CROSS 25 / STRONG SUPPLY"
                )
                obv_ok = (
                    "✅ VALID (OBV Pumping)"
                    if obv_flowing_in.iloc[last_idx]
                    else "🔴 REJECTED (Smart Money Dumping)"
                )
                ai_ok = "✅ VALID (> 0.002)" if ai_score > 0.002 else "🔴 REJECTED (Low AI Score)"

                logger.warning(
                    f"► 1. HIGH-SPEED TREND (15m): 🟢 UPTREND (EMA 7 > 25) -> SEARCHING [LONG] 🚀"
                )
                logger.warning(
                    f"► 2. VWAP REFEREE          : {vwap_ok} | Live: {curr_close:.2f} / VWAP: {curr_vwap:.2f}"
                )
                logger.warning(f"► 3. ANTI-FOMO             : {fomo_ok}")
                logger.warning(f"► 4. ENTRY TRIGGER         : {macd_long_ok}")
                logger.warning(f"► 5. OBV COMPASS           : {obv_ok}")
                logger.warning(f"► 6. AI BRAIN              : {ai_ok} | Score: {ai_score:.4f}")

            elif is_down:
                vwap_ok = (
                    "✅ VALID (Price < VWAP 24h)"
                    if curr_close < curr_vwap
                    else "🔴 REJECTED (Against VWAP)"
                )
                fomo_ok = (
                    f"✅ SAFE (RSI: {curr_rsi:.1f})"
                    if no_fomo_short.iloc[last_idx]
                    else f"🔴 DANGER/OVERSOLD (RSI: {curr_rsi:.1f} < 30)"
                )
                macd_short_ok = (
                    "🩸 VALID (Red Candle + Strong Vol)"
                    if ema_cross_short.iloc[last_idx]
                    else "⏳ WAITING EMA 7 CROSS 25 / NO DEMAND"
                )
                obv_ok = (
                    "✅ VALID (OBV Dumping)"
                    if obv_flowing_out.iloc[last_idx]
                    else "🔴 REJECTED (Smart Money Pumping)"
                )
                ai_ok = "✅ VALID (< -0.002)" if ai_score < -0.002 else "🔴 REJECTED (Low AI Score)"

                logger.warning(
                    f"► 1. HIGH-SPEED TREND (15m): 🔴 DOWNTREND (EMA 7 < 25) -> SEARCHING [SHORT] 🩸"
                )
                logger.warning(
                    f"► 2. VWAP REFEREE          : {vwap_ok} | Live: {curr_close:.2f} / VWAP: {curr_vwap:.2f}"
                )
                logger.warning(f"► 3. ANTI-FOMO             : {fomo_ok}")
                logger.warning(f"► 4. ENTRY TRIGGER         : {macd_short_ok}")
                logger.warning(f"► 5. OBV COMPASS           : {obv_ok}")
                logger.warning(f"► 6. AI BRAIN              : {ai_ok} | Score: {ai_score:.4f}")

            else:
                logger.warning(
                    f"► 1. HIGH-SPEED TREND (15m): 🟡 SIDEWAY (EMA 7 overlaps EMA 25) -> STANDBY 💤"
                )

            logger.warning(f"===========================================================")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # THOÁT LỆNH THEO XU HƯỚNG KHUNG 1H (V5.77 - TREND PROTECTOR)
        
        # Thoát LONG khi xu hướng 1H thực sự đảo chiều (EMA 20 cắt xuống EMA 50)
        exit_long_cond = (
            (dataframe["close"] < dataframe["ema_50_1h"]) 
            & (dataframe["ema_20_1h"] < dataframe["ema_50_1h"])
        )

        # Thoát SHORT khi xu hướng 1H phục hồi
        exit_short_cond = (
            (dataframe["close"] > dataframe["ema_50_1h"])
            & (dataframe["ema_20_1h"] > dataframe["ema_50_1h"])
        )

        dataframe.loc[exit_long_cond, "exit_long"] = 1
        dataframe.loc[exit_short_cond, "exit_short"] = 1
        return dataframe
