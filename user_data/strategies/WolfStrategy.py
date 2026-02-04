import logging
from functools import reduce
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame
import talib.abstract as ta
import numpy as np

logger = logging.getLogger(__name__)

class WolfStrategy(IStrategy):
    # --- CẤU HÌNH CƠ BẢN ---
    minimal_roi = {"0": 100} # Để AI tự quyết định
    stoploss = -0.10
    timeframe = "5m"
    
    # Quan trọng: Đặt False nếu chạy Spot, True nếu chạy Futures
    can_short = True 

    # --- CẤU HÌNH FREQAI ---
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        
        # 1. KÍCH HOẠT FREQAI (BẮT BUỘC)
        # Hàm này sẽ tự động gọi feature_engineering_* và train model
        # Kết quả trả về sẽ có thêm cột 'do_predict', '&s-up_or_down', v.v.
        dataframe = self.freqai.start(dataframe, metadata, self)
        
        # 2. Tính thêm chỉ báo kỹ thuật ĐỂ LỌC (Filter) sau khi AI dự đoán
        # Ví dụ: Chỉ vào lệnh nếu AI bảo Tăng VÀ RSI < 70
        dataframe['rsi'] = ta.RSI(dataframe)
        
        return dataframe

    # --- PHẦN 1: FEATURE ENGINEERING (AI HỌC CÁI GÌ?) ---
    def feature_engineering_expand_all(self, dataframe: DataFrame, period: int, metadata: dict, **kwargs) -> DataFrame:
        """
        Hàm này tạo ra các biến thể của chỉ báo dựa trên 'indicator_periods_candles' trong config.
        Ví dụ: Nếu config là [10, 20], nó sẽ tạo RSI_10, RSI_20.
        """
        # AI sẽ nhìn vào RSI, MFI, ADX, Bollinger Bands để học
        dataframe["%-rsi-" + str(period)] = ta.RSI(dataframe, timeperiod=period)
        dataframe["%-mfi-" + str(period)] = ta.MFI(dataframe, timeperiod=period)
        dataframe["%-adx-" + str(period)] = ta.ADX(dataframe, timeperiod=period)
        
        return dataframe

    def feature_engineering_standard(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        """
        Các feature không phụ thuộc vào period (ví dụ: ngày trong tuần, giờ trong ngày)
        """
        dataframe["%-day_of_week"] = dataframe["date"].dt.dayofweek
        dataframe["%-hour_of_day"] = dataframe["date"].dt.hour
        return dataframe

    # --- PHẦN 2: TARGETS (MỤC TIÊU CỦA AI LÀ GÌ?) ---
    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        """
        Định nghĩa 'Nhãn' (Label) để AI học. 
        Ở đây ta dạy AI dự đoán giá đóng cửa trong tương lai (Label period) sẽ tăng hay giảm bao nhiêu %.
        """
        label_period = self.freqai_info["feature_parameters"]["label_period_candles"]
        
        # Target = (Giá trung bình nến tương lai / Giá hiện tại) - 1
        dataframe["&-s_close"] = (
            dataframe["close"]
            .shift(-label_period)
            .rolling(label_period)
            .mean()
            / dataframe["close"]
        ) - 1
        
        return dataframe

    # --- PHẦN 3: LOGIC VÀO LỆNH (SỬA LẠI CHO REGRESSOR) ---
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Ngưỡng lợi nhuận dự đoán tối thiểu để vào lệnh (ví dụ: 0.5%)
        # Bạn có thể chỉnh số này. 0.005 = 0.5%
        min_profit_threshold = 0.005 

        # Entry Long:
        # 1. Có tín hiệu (do_predict == 1)
        # 2. Dự đoán lợi nhuận > ngưỡng (&-s_close > 0.005)
        # 3. RSI < 70 (An toàn)
        enter_long_conditions = [
            dataframe['do_predict'] == 1,
            dataframe['&-s_close'] > min_profit_threshold, 
            dataframe['rsi'] < 70 
        ]
        
        if enter_long_conditions:
            dataframe.loc[
                reduce(lambda x, y: x & y, enter_long_conditions), 'enter_long'] = 1

        # Entry Short (Futures):
        # 1. Có tín hiệu
        # 2. Dự đoán lợi nhuận < -ngưỡng (&-s_close < -0.005) -> Tức là dự đoán giảm mạnh
        # 3. RSI > 30
        enter_short_conditions = [
            dataframe['do_predict'] == 1,
            dataframe['&-s_close'] < -min_profit_threshold,
            dataframe['rsi'] > 30
        ]
        
        if enter_short_conditions:
            dataframe.loc[
                reduce(lambda x, y: x & y, enter_short_conditions), 'enter_short'] = 1
        
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exit Long nếu AI dự đoán giảm (dự đoán < 0)
        exit_long_conditions = [
            dataframe['do_predict'] == 1,
            dataframe['&-s_close'] < 0 
        ]
        if exit_long_conditions:
            dataframe.loc[
                reduce(lambda x, y: x & y, exit_long_conditions), 'exit_long'] = 1

        # Exit Short nếu AI dự đoán tăng (dự đoán > 0)
        exit_short_conditions = [
            dataframe['do_predict'] == 1,
            dataframe['&-s_close'] > 0
        ]
        if exit_short_conditions:
            dataframe.loc[
                reduce(lambda x, y: x & y, exit_short_conditions), 'exit_short'] = 1
                
        return dataframe