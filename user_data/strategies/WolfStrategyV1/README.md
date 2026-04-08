# Hướng Dẫn Tự Chạy Backtest & Download Data (WolfStrategyV1)

File này chứa các câu lệnh (Commands) bằng PowerShell để bạn có thể tự mình tải dữ liệu từ Binance và chạy Backtest trên bất kỳ cặp coin nào.

## 1. Mở Cửa Sổ Dòng Lệnh (Terminal)
Trong thư mục chứa dự án `d:\PYTHON\freqtrade`, mở cửa sổ **PowerShell** hoặc **Command Prompt**.

---

## 2. Lệnh Tải Dữ Liệu (Download Data)
Mỗi khi bạn thêm một cặp coin mới vào `config.json` (ví dụ BTC, SOL) hoặc muốn cập nhật dữ liệu nến mới nhất tới thời điểm hiện tại, bạn phải chạy lệnh này:

```powershell
.\ft_venv\Scripts\python.exe -m freqtrade download-data -c user_data/strategies/WolfStrategyV1/config.json -t 15m 1h --timerange 20260101-20260408
```

*Giải thích tham số:*
- `-t 15m 1h`: Tải dữ liệu cho cả 2 khung thời gian 15m (Micro) và 1h (Macro) vì thuật toán của chúng ta dùng cả 2.
- `--timerange 20260101-20260408`: Mốc thời gian tải dữ liệu (Từ 01/01/2026 đến 08/04/2026). Sửa mốc này tùy vào thời điểm bạn chạy.

---

## 3. Lệnh Chạy Kịch Bản (Backtesting)
Sau khi tải dữ liệu xong, bạn chạy thuật toán FreqAI để học máy và kiểm định chiến lược `WolfStrategyV1`:

```powershell
.\ft_venv\Scripts\python.exe -m freqtrade backtesting -c user_data/strategies/WolfStrategyV1/config.json --strategy-path user_data/strategies/WolfStrategyV1/ --strategy WolfStrategy --timerange 20260212-20260408 --freqaimodel XGBoostRegressor
```

*Mẹo nâng cao: Nếu bạn muốn lưu toàn bộ bảng kết quả báo cáo (ống xả log) thành một file văn bản để đọc từ từ mà không bị trôi màn hình, hãy thêm `> backtest_results.log 2>&1` vào cuối câu lệnh:*
```powershell
.\ft_venv\Scripts\python.exe -m freqtrade backtesting -c user_data/strategies/WolfStrategyV1/config.json --strategy-path user_data/strategies/WolfStrategyV1/ --strategy WolfStrategy --timerange 20260212-20260408 --freqaimodel XGBoostRegressor > backtest_results.log 2>&1
```

---

## 4. Xóa Rác Đào Tạo (Clear FreqAI Models)
FreqAI sẽ lưu lại các "Bộ Não AI" sau mỗi lần chạy. Nếu bạn sửa đổi thuật toán/chỉ báo quá nhiều và muốn máy học lại từ đầu (để tránh nhiễu), hãy xóa ruột thư mục này đi:
`d:\PYTHON\freqtrade\user_data\models\wolf_mtf_v6_15m`
