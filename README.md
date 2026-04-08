# Hướng Dẫn Tự Chạy Backtest & Download Data (WolfStrategyV1)

Mọi chi tiết về chiến lược và các lệnh quan trọng đã được tôi lưu trữ an toàn trong git. Dưới đây là các câu lệnh bạn cần dùng:

## 1. Tải Dữ Liệu Mới Nhất (Binance)
Sử dụng lệnh này khi bạn muốn cập nhật nến mới nhất hoặc thêm cặp coin mới:
```powershell
.\ft_venv\Scripts\python.exe -m freqtrade download-data -c user_data/strategies/WolfStrategyV1/config.json -t 15m 1h --timerange 20260101-20260408
```

## 2. Chạy Backtest Sniper V5 (Bộ Đôi Vàng BNB/BTC)
Chạy lệnh này sau khi tải dữ liệu để xem hiệu suất Sniper Precision:
```powershell
.\ft_venv\Scripts\python.exe -m freqtrade backtesting -c user_data/strategies/WolfStrategyV1/config.json --strategy-path user_data/strategies/WolfStrategyV1/ --strategy WolfStrategy --timerange 20260212-20260408 --freqaimodel XGBoostRegressor
```

## 3. Xem Báo Cáo Chi Tiết
Kết quả backtest sẽ được lưu trong `user_data/backtest_results/`. Bạn cũng có thể xem tổng quan nhanh nhất trong file `backtest_results.log` nếu dùng ống dẫn `> backtest_results.log 2>&1` ở cuối lệnh.

---
Mọi mã nguồn hiện đã được **Commit** vào nhánh dự án. Bạn có thể yên tâm tiếp tục các bước tiếp theo.
