Đây là nội dung file `README.md` chuyên nghiệp dành cho dự án **WolfStrategy FreqAI** của bạn, kèm theo hướng dẫn chi tiết để đẩy code lên Git bất chấp việc thư mục `user_data` đang bị ignore.

### Phần 1: Nội dung file `user_data/README.md`

Bạn hãy tạo file `README.md` trong thư mục `user_data/` và dán nội dung sau vào. File này được thiết kế như một "Wiki" nhỏ để bạn (hoặc người khác) nhìn vào là biết cách vận hành ngay.

```markdown
# 🐺 WolfStrategy - FreqAI Futures Trading Bot

Dự án phát triển Bot giao dịch Futures sử dụng FreqAI (Machine Learning) với mô hình **XGBoostRegressor**.
Chiến thuật tập trung vào quản lý rủi ro bảo thủ, kết hợp dự đoán của AI với các chỉ báo kỹ thuật (RSI, Bollinger Bands) để bắt xu hướng (Trend Following).

## 🛠 Yêu cầu hệ thống
* **Docker & Docker Compose** (đã cài đặt và cấu hình GPU Passthrough nếu dùng Local).
* **RAM:** Tối thiểu 16GB (khuyến nghị 32GB cho việc Training).
* **OS:** Linux hoặc Windows (WSL2).

## 📂 Cấu trúc dự án
* `strategies/WolfStrategy.py`: Logic chiến thuật chính (Entry/Exit/Stoploss).
* `config_freqai.json`: Cấu hình Bot, tham số FreqAI và danh sách cặp tiền (Binance Futures).
* `docker-compose.dev.yml`: File khởi chạy môi trường Dev (nằm ở thư mục gốc).

## 🚀 Cheatsheet lệnh (CMD)

Lưu ý: Các lệnh được chạy từ thư mục gốc của dự án.

### 1. Quản lý Bot
**Khởi động Bot (Chạy ngầm):**
```bash
docker compose -f docker-compose.dev.yml up -d

```

**Khởi động lại (Reload Config/Strategy):**

```bash
docker compose -f docker-compose.dev.yml restart

```

**Dừng và Xóa Container (Reset sạch):**

```bash
docker compose -f docker-compose.dev.yml down

```

**Xem Log (Thời gian thực):**

```bash
docker compose -f docker-compose.dev.yml logs -f

docker compose -f docker-compose.yml logs -f

```

### 2. Dữ liệu & Training

BƯỚC 1: XÓA MODEL HỎNG (THỦ TỤC BẮT BUỘC)
Vẫn phải xóa vì lần chạy trước đã tạo ra file rác.

```powershell
Remove-Item -Recurse -Force user_data/models/*
```

**Tải dữ liệu lịch sử (Bắt buộc trước khi Backtest):**
```powershell
docker compose -f docker-compose.dev.yml run --rm freqtrade download-data --config user_data/config_freqai.json --days 150 --timeframes 5m 15m 1h 1d --erase
```

Xóa model lỗi (Lần nữa cho chắc) Do lần chạy trước bị crash giữa chừng, file model có thể bị hỏng (corrupted pipeline).
```powershell
Remove-Item -Recurse -Force user_data/models/wolf_ai_king_btc_v1
```

**Chạy Backtesting (Kiểm thử chiến thuật):**
```powershell
docker compose -f docker-compose.dev.yml run --rm freqtrade backtesting --strategy WolfStrategy --config user_data/config_freqai.json --timerange 20260101-20260201 --freqaimodel XGBoostRegressor
```

**Chạy Backtesting (Kiểm thử chiến thuật):**
```powershell
docker compose -f docker-compose.dev.yml run --rm freqtrade backtesting --strategy WolfStrategy --config user_data/config_freqai.json --timerange 20260101-20260201 --freqaimodel XGBoostRegressor --cache none
```

Chào bạn, **Principal Engineer** đây.

Khi chúng ta thay đổi hoàn toàn chiến thuật (từ đánh SUI sang đánh BTC Leverage 10x), việc dọn dẹp "tàn dư" của chế độ cũ là **BẮT BUỘC**. Nếu không, Bot sẽ tính toán sai Profit/Loss hoặc load nhầm model AI cũ.

Dưới đây là quy trình **"Factory Reset"** cho Bot Freqtrade chạy Docker của bạn.

---

### BƯỚC 1: XÓA CƠ SỞ DỮ LIỆU GIAO DỊCH (DATABASE)

Đây là nơi lưu trữ lịch sử các lệnh cũ (SUI, lệnh thua, v.v.).

1. **Dừng Bot (nếu đang chạy):**
```powershell
docker compose down

```


2. **Xóa file database:**
Truy cập vào thư mục `user_data` trên máy tính của bạn. Tìm và xóa các file có đuôi `.sqlite`.
* Nếu bạn chạy Dry-run (Test): Xóa `tradesv3.dryrun.sqlite`.
* Nếu bạn chạy Live (Tiền thật): Xóa `tradesv3.sqlite`.


**Lệnh Powershell nhanh:**
```powershell
Remove-Item user_data/tradesv3*.sqlite

```



---

### BƯỚC 2: XÓA MODEL AI CŨ (FREQAI TRASH)

Vì bạn đã đổi chiến thuật và đổi cặp tiền (chỉ còn BTC), các model cũ đã học dữ liệu của SUI không còn giá trị. Giữ lại chỉ tốn ổ cứng và gây lỗi.

1. Vào thư mục `user_data/models`.
2. Xóa tất cả các thư mục bên trong nó (ví dụ: `wolf_ai_sui_v1`, `wolf_ai_smart_v1`...).
**Lệnh Powershell:**
```powershell
Remove-Item -Recurse -Force user_data/models/*

```



---

### BƯỚC 3: DỌN DẸP KẾT QUẢ BACKTEST CŨ

Để khi chạy Backtest mới, bạn không bị rối mắt bởi các file báo cáo cũ.

1. Vào thư mục `user_data/backtest_results`.
2. Xóa hết các file bên trong.

---

### BƯỚC 4: KHỞI ĐỘNG LẠI (SẠCH SẼ)

Sau khi xóa xong, bạn chạy lại lệnh Backtest hoặc Dry-run.
Lúc này Bot sẽ:

1. Tự tạo file Database mới tinh (Tài khoản về lại 1000 USDT).
2. Tự train lại Model AI mới chuyên cho BTC.

**Lệnh Backtest (Nitro Mode 10x):**

```powershell
docker compose -f docker-compose.dev.yml run --rm freqtrade backtesting --strategy WolfStrategy --config user_data/config_freqai.json --timerange 20260101-20260201 --freqaimodel XGBoostRegressor --cache none

```

Chúc bạn khởi đầu mới thành công với **"King BTC"**!

Chào bạn, **Principal Engineer** đây.

Chúng ta đang đối mặt với "Trùm cuối" của lỗi FreqAI. Tôi đã phân tích kỹ log của bạn và tìm ra 2 nguyên nhân cốt lõi:

1. **Lỗi `AttributeError: ... features_in`:** Đây là lỗi **"Thây ma" (Zombie Model)**.
* Bạn đã từng chạy Training bằng bản `stable` cũ. Nó sinh ra các file model cũ lưu trong thư mục `user_data/models`.
* Bây giờ bạn chạy bản `develop` mới. Code mới cố gắng đọc file model cũ -> **BẤT TƯƠNG THÍCH** (Do thư viện `datasieve` thay đổi cấu trúc dữ liệu).
* **Giải pháp:** Phải xóa sạch thư mục Model cũ để Bot train lại từ đầu.


2. **Lỗi SUI `NaNs`:** Do dữ liệu SUI bị thiếu phần đầu năm 2026.
* Log báo: `SUI data starts at 2026-01-30`.
* Nhưng bạn yêu cầu test từ `2026-01-01`. Bot không có dữ liệu quá khứ để học -> Nó báo lỗi.



---

### QUY TRÌNH "TẨY TỦY" TOÀN DIỆN (LÀM 1 LẦN LÀ XONG)

Hãy làm chính xác 3 bước này để dọn sạch rác và chạy mượt:

### BƯỚC 1: XÓA THƯ MỤC MODEL CŨ (QUAN TRỌNG NHẤT)

Đây là bước để diệt con "Zombie" gây lỗi `datasieve`.
Trên Windows, bạn vào thư mục:
`D:\AI\PYTHON\freqtrade\user_data\models`

👉 **XÓA THẲNG TAY** thư mục có tên `wolf_ai_hyperopt_local` (hoặc xóa sạch cả thư mục `models` cho sạch sẽ).

### BƯỚC 2: TẢI LẠI DATA CHO SUI (VÀ CÁC COIN MỚI)

SUI bị lỗi timeline, nên chúng ta cần tải lại và dùng cờ `--erase` để nó xóa cái cũ tải cái mới chuẩn hơn.

Chạy lệnh này trên PowerShell:

```powershell
docker compose run --rm freqtrade download-data --pairs SUI/USDT:USDT SOL/USDT:USDT LINK/USDT:USDT --timeframe 5m 1h --timerange 20251201- --erase

```

*(Tôi để timerange từ `20251201` để đảm bảo có đủ dữ liệu cho Bot học trước khi bước vào năm 2026).*

### BƯỚC 3: CHẠY HYPEROPT (VỀ ĐÍCH)

Sau khi xóa model và tải đủ data, chạy lại lệnh Hyperopt. Lần này Bot sẽ Training lại từ con số 0 (sạch sẽ, không lỗi).

```powershell
docker compose run --rm freqtrade hyperopt --hyperopt-loss SharpeHyperOptLoss --strategy WolfStrategy --spaces roi stoploss trailing --timerange 20260101-20260215 -e 100 -c user_data/config_freqai.json --freqaimodel XGBoostRegressor

```

**Lưu ý:** Quá trình Training lại từ đầu sẽ mất khoảng **15-20 phút** (nhìn dòng `Training...`). Hãy kiên nhẫn, đừng tắt ngang! Chúc mừng bạn, bạn sắp có bộ số vàng rồi! 🛠️🐺🚀


nano user_data/strategies/WolfStrategy.py