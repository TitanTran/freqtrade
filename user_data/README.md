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

```

### 2. Dữ liệu & Training

**Tải dữ liệu lịch sử (Bắt buộc trước khi Backtest):**
```powershell
docker compose -f docker-compose.dev.yml run --rm freqtrade download-data --timerange 20251201-20260205 -t 5m 15m 1h --config user_data/config_freqai.json --erase
```

Xóa model lỗi (Lần nữa cho chắc) Do lần chạy trước bị crash giữa chừng, file model có thể bị hỏng (corrupted pipeline).
```powershell
Remove-Item -Recurse -Force user_data/models/wolf_ai_v1
```

**Chạy Backtesting (Kiểm thử chiến thuật):**
```powershell
docker compose -f docker-compose.dev.yml run --rm freqtrade backtesting --strategy WolfStrategy --config user_data/config_freqai.json --timerange 20260101-20260201 --freqaimodel XGBoostRegressor
```

### PHẦN 3: Cách xuất Log ra file (Không cần Copy/Paste)

Là một kỹ sư, chúng ta không nên bôi đen copy thủ công từ Terminal. Hãy dùng kỹ thuật **Redirection (Chuyển hướng luồng ra)** của Linux/Docker.

#### Cách 1: Ghi log Backtest ra file riêng (Khuyên dùng)

Khi chạy lệnh backtest, bạn thêm ký tự `>` và tên file vào cuối câu lệnh.

```powershell
docker compose -f docker-compose.dev.yml run --rm freqtrade backtesting --strategy WolfStrategy --config user_data/config_freqai.json --timerange 20260101-20260201 --freqaimodel XGBoostRegressor > ket_qua_backtest.txt

```

* **Kết quả:** Màn hình sẽ không hiện gì cả (hoặc chỉ hiện lỗi), toàn bộ bảng báo cáo đẹp đẽ sẽ được lưu vào file `ket_qua_backtest.txt` nằm ngay thư mục hiện tại. Bạn chỉ cần mở file đó lên xem.

#### Cách 2: Lấy log của Bot đang chạy (Live/Dry-run)

Nếu bot đang chạy ngầm (`up -d`), bạn muốn xuất toàn bộ log từ lúc khởi động ra file:

```powershell
docker compose -f docker-compose.dev.yml logs > full_log_bot.txt

```

#### Cách 3: Theo dõi Log và Ghi ra file cùng lúc (Tee)

Nếu bạn dùng PowerShell, lệnh `Tee-Object` giúp bạn vừa nhìn thấy trên màn hình, vừa lưu vào file:

```powershell
# Lệnh ví dụ
docker compose ... backtesting ... | Tee-Object -FilePath "log_bao_cao.txt"

```


### 3. Giao diện (FreqUI)

**Cài đặt UI (Chỉ chạy 1 lần đầu):**

```bash
docker compose -f docker-compose.dev.yml run --rm freqtrade install-ui

```

* **Truy cập Dashboard:** `http://localhost:8080`
* **User/Pass:** Xem trong `config_freqai.json` phần `api_server`.

## ⚠️ Lưu ý quan trọng

1. **Mô hình AI:** Đảm bảo `freqaimodel` được set là `XGBoostRegressor` trong `config_freqai.json` hoặc lệnh chạy.
2. **Ignored Files:** Thư mục `user_data/models` và `user_data/data` rất nặng, không được đẩy lên Git.

```

---

### Phần 2: Hướng dẫn đẩy code lên Git (Bypass .gitignore)

Vì mặc định Freqtrade sẽ ignore toàn bộ thư mục `user_data/` (để tránh lộ key hoặc data rác), nên bạn cần dùng lệnh `git add --force` (hoặc `-f`) để ép Git theo dõi các file quan trọng mà bạn muốn.

Thực hiện các lệnh sau tại Terminal thư mục gốc `freqtrade/`:

#### Bước 1: Khởi tạo Repo (Nếu chưa có)
```bash
git init
git branch -M main

```

#### Bước 2: Add file (Quan trọng)

Sử dụng `-f` cho các file nằm trong `user_data`:

```bash
# 1. Add file Docker Compose ở root
git add docker-compose.dev.yml

# 2. Force add các file trong user_data (Bỏ qua .gitignore)
git add -f user_data/strategies/WolfStrategy.py
git add -f user_data/config_freqai.json
git add -f user_data/README.md

```

#### Bước 3: Commit và Push

```bash
git commit -m "Initial commit: WolfStrategy FreqAI setup with XGBoost"

# Thay URL bên dưới bằng Link Repo GitHub/GitLab của bạn
git remote add origin https://github.com/username/ten-repo-cua-ban.git
git push -u origin main

```

**Mẹo:** Sau này khi bạn sửa code trong `WolfStrategy.py`, bạn chỉ cần `git add .` và `git commit` như bình thường, vì Git đã bắt đầu theo dõi file đó rồi (nó chỉ bị ignore khi chưa được add lần đầu thôi).