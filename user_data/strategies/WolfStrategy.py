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

    # --- ASSET PROTECTION ARCHITECTURE ---
    stoploss = -0.15 # Hard floor safety net
    use_custom_stoploss = True
    trailing_stop = False

    # MINIMAL ROI (Fast Hit & Run)
    minimal_roi = {
        "0": 0.40,    # 40% ROI (leveraged) to take profit immediately
        "1440": 0.15, # Lower threshold after 1 day
        "2880": 0     # Breakeven exit after 2 days
    }

    protections = [
        {"method": "CooldownPeriod", "stop_duration_candles": 4} # Cool down after SL
    ]

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str, side: str,
                 **kwargs) -> float:
        return 3.0  # 3x Leverage

    # ==========================================
    # --- DYNAMIC RISK MANAGEMENT (TIERED GEARBOX) ---
    # ==========================================
    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        
        # 15m ATR for micro stoploss
        dataframe_15m, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe_15m is None or len(dataframe_15m) == 0: return -0.05
        atr_15m_pct = dataframe_15m.iloc[-1]['atr'] / current_rate

        # 1H ATR for macro trailing
        dataframe_1h, _ = self.dp.get_analyzed_dataframe(pair, "1h") 
        if dataframe_1h is None or len(dataframe_1h) == 0: return -0.05
        atr_1h_pct = dataframe_1h.iloc[-1]['atr'] / current_rate

        # DEFAULT TIER: Initial Stoploss (Max 6%, Min 2%)
        initial_stop = max(min(atr_15m_pct * 2.0, 0.06), 0.02)
        
        # --- DEFENSE THRESHOLDS ---
        leverage_rate = 3.0
        roi_5_pct = 0.05 / leverage_rate  # 5% ROI target (~1.66% price move)
        activation_bos = max(atr_1h_pct * 2.5, 0.033) # Macro lock threshold
        
        # TIER 2: MACRO LOCK (Trailing based on 1H ATR)
        if current_profit > activation_bos:
            return -abs(atr_1h_pct * 1.2) 

        # TIER 1: BREAKEVEN TRAP (Lock at +0.2% price move to cover fees)
        # Formula: (desired_profit - current_profit)
        if current_profit > roi_5_pct:
            return (0.002 - current_profit) 

        return -abs(initial_stop)

    # --- MULTI-DIMENSIONAL DATA PROVISIONING ---
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, "1h") for pair in pairs] # Macro Radar

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
        horizon = 24 # Forward look 24 candles
        future_high = dataframe['high'].rolling(horizon).max().shift(-horizon)
        future_low = dataframe['low'].rolling(horizon).min().shift(-horizon)
        max_gain = (future_high - dataframe['close']) / dataframe['close']
        max_loss = (dataframe['close'] - future_low) / dataframe['close']
        dataframe['&-rr_score'] = max_gain - (max_loss * 2.0) # Heavy penalty for risk
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        return self.feature_engineering_targets(dataframe, metadata, **kwargs)

    # --- INDICATORS & DATA CLEANSING ---
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
        dataframe['ema_7'] = ta.EMA(dataframe, timeperiod=7)
        dataframe['ema_25'] = ta.EMA(dataframe, timeperiod=25)
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

        # 3. VOLUME, LIQUIDITY & SMART MONEY COMPASS
        typical_price = (dataframe['high'] + dataframe['low'] + dataframe['close']) / 3
        dataframe['vwap_24h'] = (dataframe['volume'] * typical_price).rolling(window=96).sum() / dataframe['volume'].rolling(window=96).sum()
        dataframe['volume_mean'] = dataframe['volume'].rolling(window=40).mean()
        
        dataframe['obv'] = ta.OBV(dataframe['close'], dataframe['volume'])
        dataframe['obv_ema_10'] = ta.EMA(dataframe['obv'], timeperiod=10) # OBV Momentum Compass

        # 4. MARKET STRUCTURE
        dataframe['candle_body'] = abs(dataframe['close'] - dataframe['open'])
        dataframe['avg_candle_body'] = dataframe['candle_body'].rolling(window=40).mean()
        dataframe['local_high'] = dataframe['high'].rolling(window=20).max().shift(1)
        dataframe['local_low'] = dataframe['low'].rolling(window=20).min().shift(1)

        dataframe = self.freqai.start(dataframe, metadata, self)
        return dataframe

    # --- COMBAT CORE (ENTRY) ---
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

        # ANTI-FOMO FILTERS
        no_fomo_long = (
            (dataframe['rsi'] < 75) & 
            (dataframe['close'] <= (dataframe['bb_upperband'] * 1.01))
        )
        no_fomo_short = (
            (dataframe['rsi'] > 25) & 
            (dataframe['close'] >= (dataframe['bb_lowerband'] * 0.99))
        )

        # ======================================================================
        # --- STEALTH INTERCEPTOR (V3.0 - NO SUPPLY / NO DEMAND) ---
        # ==========================================
        stealth_volume = (
            (dataframe['volume'].shift(1) < dataframe['volume_mean'].shift(1)) & 
            (dataframe['volume'] < (dataframe['volume_mean'] * 1.2))             
        )

        is_green_candle = dataframe['close'] > dataframe['open']
        is_red_candle = dataframe['close'] < dataframe['open']

        macd_reversal_long = (
            (dataframe['macdhist'] > dataframe['macdhist'].shift(1)) & 
            (dataframe['macdhist'].shift(1) < dataframe['macdhist'].shift(2)) &
            (dataframe['close'] > dataframe['ema_7']) & 
            is_green_candle &
            stealth_volume
        )
        
        macd_reversal_short = (
            (dataframe['macdhist'] < dataframe['macdhist'].shift(1)) & 
            (dataframe['macdhist'].shift(1) > dataframe['macdhist'].shift(2)) &
            (dataframe['close'] < dataframe['ema_7']) &
            is_red_candle &
            stealth_volume
        )

        # --- SMART MONEY COMPASS (OBV) ---
        obv_flowing_in = dataframe['obv'] > dataframe['obv_ema_10']
        obv_flowing_out = dataframe['obv'] < dataframe['obv_ema_10']

        # 🎯 BOS SNIPER - OPTIMIZED BOTTOM FISHER
        long_bos_cond = (
            common_cond & risk_filter & 
            (dataframe['close'] > dataframe['vwap_24h']) & 
            macd_reversal_long &   
            no_fomo_long &
            obv_flowing_in &       # HARD FILTER: Disallow Long if Smart Money is dumping
            (dataframe[predict_col] > 0.002) 
        )

        short_bos_cond = (
            common_cond & risk_filter & 
            (dataframe['close'] < dataframe['vwap_24h']) & 
            macd_reversal_short & 
            no_fomo_short &
            obv_flowing_out &      # HARD FILTER: Disallow Short if Smart Money is pumping
            (dataframe[predict_col] < -0.002)
        )

        dataframe.loc[long_bos_cond, ['enter_long', 'enter_tag']] = (1, 'long_bos_sniper')
        dataframe.loc[short_bos_cond, ['enter_short', 'enter_tag']] = (1, 'short_bos_sniper')

        # ==========================================
        # 🧭 TELEMETRY X-RAY (STEALTH INTERCEPTOR)
        # ==========================================
        if True:
            curr_close = dataframe['close'].iloc[last_idx]
            curr_vwap = dataframe['vwap_24h'].iloc[last_idx]
            curr_rsi = dataframe['rsi'].iloc[last_idx]
            
            is_up = dataframe['ema_7'].iloc[last_idx] > dataframe['ema_25'].iloc[last_idx]
            is_down = dataframe['ema_7'].iloc[last_idx] < dataframe['ema_25'].iloc[last_idx]
            
            ai_score = dataframe[predict_col].iloc[last_idx] if predict_col in dataframe.columns else 0.0
            
            logger.warning(f"")
            logger.warning(f"========== 🧭 X-RAY RADAR: BOT STATUS ({metadata['pair']}) 🧭 ==========")
            
            if is_up:
                vwap_ok = "✅ VALID (Price > VWAP 24h)" if curr_close > curr_vwap else "🔴 REJECTED (Against VWAP)"
                fomo_ok = f"✅ SAFE (RSI: {curr_rsi:.1f})" if no_fomo_long.iloc[last_idx] else f"🔴 DANGER/OVERBOUGHT (RSI: {curr_rsi:.1f})"
                macd_long_ok = "🔥 VALID (Green Candle + Low Vol)" if macd_reversal_long.iloc[last_idx] else "⏳ WAITING MACD BOTTOM / NO SUPPLY"
                obv_ok = "✅ VALID (OBV Pumping)" if obv_flowing_in.iloc[last_idx] else "🔴 REJECTED (Smart Money Dumping)"
                ai_ok = "✅ VALID (> 0.002)" if ai_score > 0.002 else "🔴 REJECTED (Low AI Score)"
                
                logger.warning(f"► 1. HIGH-SPEED TREND (15m): 🟢 UPTREND (EMA 7 > 25) -> SEARCHING [LONG] 🚀")
                logger.warning(f"► 2. VWAP REFEREE          : {vwap_ok} | Live: {curr_close:.2f} / VWAP: {curr_vwap:.2f}")
                logger.warning(f"► 3. ANTI-FOMO             : {fomo_ok}")
                logger.warning(f"► 4. ENTRY TRIGGER         : {macd_long_ok}")
                logger.warning(f"► 5. OBV COMPASS           : {obv_ok}")
                logger.warning(f"► 6. AI BRAIN              : {ai_ok} | Score: {ai_score:.4f}")
                
            elif is_down:
                vwap_ok = "✅ VALID (Price < VWAP 24h)" if curr_close < curr_vwap else "🔴 REJECTED (Against VWAP)"
                fomo_ok = f"✅ SAFE (RSI: {curr_rsi:.1f})" if no_fomo_short.iloc[last_idx] else f"🔴 DANGER/OVERSOLD (RSI: {curr_rsi:.1f})"
                macd_short_ok = "🩸 VALID (Red Candle + Low Vol)" if macd_reversal_short.iloc[last_idx] else "⏳ WAITING MACD TOP / NO DEMAND"
                obv_ok = "✅ VALID (OBV Dumping)" if obv_flowing_out.iloc[last_idx] else "🔴 REJECTED (Smart Money Pumping)"
                ai_ok = "✅ VALID (< -0.002)" if ai_score < -0.002 else "🔴 REJECTED (Low AI Score)"
                
                logger.warning(f"► 1. HIGH-SPEED TREND (15m): 🔴 DOWNTREND (EMA 7 < 25) -> SEARCHING [SHORT] 🩸")
                logger.warning(f"► 2. VWAP REFEREE          : {vwap_ok} | Live: {curr_close:.2f} / VWAP: {curr_vwap:.2f}")
                logger.warning(f"► 3. ANTI-FOMO             : {fomo_ok}")
                logger.warning(f"► 4. ENTRY TRIGGER         : {macd_short_ok}")
                logger.warning(f"► 5. OBV COMPASS           : {obv_ok}")
                logger.warning(f"► 6. AI BRAIN              : {ai_ok} | Score: {ai_score:.4f}")
                
            else:
                logger.warning(f"► 1. HIGH-SPEED TREND (15m): 🟡 SIDEWAY (EMA 7 overlaps EMA 25) -> STANDBY 💤")
            
            logger.warning(f"===========================================================")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, ['exit_long', 'exit_short']] = 0
        return dataframe
