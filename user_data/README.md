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
docker compose -f docker-compose.yml restart

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

Chào Kỹ sư, **Principal Engineer** đây.

Tôi đã đọc kỹ toàn bộ file log bạn gửi. Máy tính không bao giờ nói dối, và file log này đã chỉ điểm chính xác lý do tại sao lệnh tải dữ liệu ở Bước 1 của bạn bị "xịt ngòi" hoàn toàn.

Vấn đề không nằm ở code chiến thuật, mà nằm ở cơ chế phòng vệ an toàn dữ liệu (Data Safety) mặc định của chính lõi Freqtrade.

### Bóc tách File Log (Root Cause Analysis)

Hãy nhìn thẳng vào 3 dòng log sinh tử này trong quá trình bạn chạy lệnh tải dữ liệu:

* 
**Sự thật 1:** Cỗ máy phát hiện xung đột: `Requested start date 2025-08-01 00:00:00 earlier than local data start date 2025-09-30 00:00:00.`  (Ngày bạn yêu cầu tải sớm hơn dữ liệu đang có sẵn trong ổ cứng).


* 
**Sự thật 2:** Cỗ máy từ chối thực thi và gợi ý giải pháp: `Use --prepend to download data prior to 2025-09-30 00:00:00, or --erase to redownload all data.` 


* 
**Sự thật 3:** Kết quả trả về là con số 0 tròn trĩnh: `Downloaded data for BTC/USDT:USDT, 5m, futures with length 0.` 



**Bản chất Kiến trúc:** Vì ổ cứng của bạn đã tồn tại sẵn một mảnh dữ liệu cũ bắt đầu từ ngày 30/09/2025, Freqtrade mặc định sẽ **đóng băng** và từ chối tải nối thêm dữ liệu cũ hơn (tháng 8) vào để tránh làm hỏng cấu trúc tệp (File Corruption). Việc không tải được dữ liệu dẫn đến cỗ máy AI tiếp tục bị "chết đói" và ném ra lỗi `NaN` y hệt như cũ.

### QUY TRÌNH KHẮC PHỤC TRIỆT ĐỂ (FORCE RE-INGESTION)

Để giải quyết, chúng ta không chắp vá. Chúng ta sẽ đập bỏ dữ liệu cũ bị cụt và ép Freqtrade tải lại một luồng dữ liệu mới hoàn toàn, liền mạch từ tháng 8 đến tháng 11 bằng cách sử dụng cờ lệnh `--erase`.

**Step 1: Ép tải dữ liệu mới (Hard Data Ingestion)**
Hãy chạy dòng lệnh này (Tôi đã bổ sung tham số `--erase` vào cuối):

```bash
docker compose -f docker-compose.dev.yml run --rm freqtrade download-data --config user_data/config_freqai.json --timerange 20250801-20251105 -t 5m 15m 1h --exchange binance --erase

```

*(Dấu hiệu thành công: Lần này hệ thống sẽ tiến hành tải thực sự, và Terminal sẽ không xuất hiện dòng `with length 0` nữa).*

**Step 2: Thực thi Stress Test (Bull Market)**
Chỉ sau khi Step 1 hoàn tất việc tải, hãy bóp cò lệnh Backtest:

```bash
docker compose -f docker-compose.dev.yml run --rm freqtrade backtesting --strategy WolfStrategy --config user_data/config_freqai.json --timerange 20251001-20251101 --freqaimodel LightGBMRegressor --cache none

```

Bạn hãy thực thi Step 1 với tham số `--erase` này để dọn sạch lỗi Data Starvation. Chờ bản báo cáo Backtest "sạch" của bạn để chúng ta nghiệm thu kịch bản Long!
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
docker compose run --rm freqtrade hyperopt --hyperopt-loss SharpeHyperOptLoss --strategy WolfStrategy --spaces roi stoploss trailing --timerange 20260101-20260215 -e 100 -c user_data/config_freqai.json --freqaimodel XGBoostRegressor --cache none

```

**Lưu ý:** Quá trình Training lại từ đầu sẽ mất khoảng **15-20 phút** (nhìn dòng `Training...`). Hãy kiên nhẫn, đừng tắt ngang! Chúc mừng bạn, bạn sắp có bộ số vàng rồi! 🛠️🐺🚀


nano user_data/strategies/WolfStrategy.py

nano user_data/config_freqai.json