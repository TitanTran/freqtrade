# 🐺 WolfStrategy - FreqAI Futures Trading Bot

Dự án phát triển Bot giao dịch Futures sử dụng FreqAI (Machine Learning) với mô hình **XGBoostRegressor**. Chiến thuật tập trung vào quản lý rủi ro bảo thủ, kết hợp AI và Cấu trúc giá (Break of Structure - BoS) để bắt xu hướng (Trend Following).

## 🛠 Yêu cầu hệ thống
* **Hạ tầng:** Docker & Docker Compose.
* **RAM:** Tối thiểu 16GB (Khuyến nghị 32GB cho việc Training AI ở Local).
* **OS:** Windows (PowerShell/WSL2) cho Local Dev; Linux (Ubuntu/Debian) cho VPS Live.

## 📂 Cấu trúc dự án cốt lõi
* `user_data/strategies/WolfStrategy.py`: Logic chiến thuật chính (Entry/Exit/Stoploss/FreqAI Targets).
* `user_data/config_freqai.json`: Cấu hình Bot, tham số FreqAI, API Keys và danh sách cặp tiền.
* `docker-compose.dev.yml`: Cấu hình Docker cho môi trường Local/Testing.
* `docker-compose.yml`: Cấu hình Docker cho môi trường Live/VPS.

---

## 💻 PHẦN 1: MÔI TRƯỜNG LOCAL (DEVELOPMENT & TESTING)
*(Thực thi trên máy cá nhân - Windows PowerShell - Sử dụng file `docker-compose.dev.yml`)*

### 1. Quản trị Dữ liệu (Data Ingestion)
Tải dữ liệu nến để Backtest hoặc Train AI. Sử dụng cờ `--erase` để ép tải lại từ đầu nếu dữ liệu cũ bị lỗi (Data Starvation).
```powershell
docker-compose run --rm freqtrade download-data --config user_data/config_freqai.json --timerange 20250101-20260310 -t 15m 1h --exchange binance --erase

```

### 2. Backtest & Hyperopt

**Chạy Backtest (Kiểm tra chiến thuật):**

```powershell
docker-compose run --rm freqtrade backtesting --strategy WolfStrategy --config user_data/config_freqai.json --timerange 20260101-20260310 --freqaimodel XGBoostRegressor --cache none

```

**Chạy Backtest (Kiểm tra chiến thuật Học tăng cường):**

```powershell
python -m freqtrade backtesting --strategy WolfRLStrategy --config config_rl.json --timerange 20260101-20260301 --freqaimodel ReinforcementLearner
```

**Chạy Hyperopt (Tối ưu hóa thông số):**

```powershell
docker compose -f docker-compose.dev.yml run --rm freqtrade hyperopt --hyperopt-loss SharpeHyperOptLoss --strategy WolfStrategy --spaces roi stoploss trailing --timerange 20260101-20260215 -e 100 -c user_data/config_freqai.json --freqaimodel XGBoostRegressor --cache none

```
**Lệnh Xuất Trận Khởi Động (CMD):**
```powershell
python -m freqtrade backtesting --strategy WolfRLStrategy --config user_data/config_rl.json --timerange 20260101-20260301 --freqaimodel ReinforcementLearner

```

### 3. Dọn dẹp Rác Local (Factory Reset)

*(Sử dụng khi đổi chiến thuật, đổi cặp tiền hoặc model AI bị lỗi Zombie)*

```powershell
# Xóa Database cũ (Lịch sử trade)
Remove-Item user_data/tradesv3*.sqlite

# Xóa toàn bộ Model AI cũ
Remove-Item -Recurse -Force user_data/models/*

# Xóa file báo cáo Backtest cũ
Remove-Item -Recurse -Force user_data/backtest_results/*

### Kích hoạt môi trường ảo bằng cái tên mới:
PowerShell
.\ft_venv\Scripts\activate
(Thành công: Chữ (ft_venv) màu xanh sẽ hiện ra ở đầu dòng).

## 🌐 PHẦN 2: MÔI TRƯỜNG LIVE (VPS PRODUCTION)

*(Thực thi trên VPS Linux - Terminal SSH - Đánh tiền thật)*

### 1. Điều khiển Cỗ máy (Docker)

*(Luôn dùng nhóm lệnh này sau khi sửa file `WolfStrategy.py` hoặc `config.json`)*

```bash
# Khởi động Bot chạy ngầm
docker compose up -d

# Khởi động lại Bot (Nạp code mới)
docker compose restart

# Tắt Bot hoàn toàn
docker compose down

# Xem Log hệ thống trực tiếp (Ấn Ctrl+C để thoát)
docker compose logs -f freqtrade

docker compose logs -f --tail=100 freqtrade

```

*(Nếu cài đặt trực tiếp qua Systemd thay vì Docker):*

```bash
sudo systemctl start freqtrade
sudo systemctl restart freqtrade
sudo systemctl stop freqtrade
sudo journalctl -u freqtrade -f

```

### 2. Quản lý File trực tiếp trên VPS

```bash
# Sửa code chiến thuật
nano user_data/strategies/WolfStrategy.py

# Sửa cấu hình Bot
nano user_data/config.json

# Sửa cấu hình Bot (Đang sữ dụng)
nano user_data/config_freqai.json
# (Lưu file trong Nano: Ctrl + O -> Enter -> Ctrl + X)

```

### 3. Đặt lại Hệ thống Live (System Reset)

*(Cảnh báo: Phải TẮT BOT trước khi chạy lệnh này. Sử dụng khi muốn xóa sạch lịch sử Trade cũ bị nhiễu để bắt đầu chiến dịch mới).*

```bash
# Đổi tên file để lưu trữ thay vì xóa vĩnh viễn
mv user_data/tradesv3.sqlite user_data/tradesv3_archive.sqlite

# Nếu có chạy Dry-run trước đó, dọn luôn:
mv user_data/tradesv3.dryrun.sqlite user_data/tradesv3_dryrun_archive.sqlite

```

### 4. Tiện ích VPS (Clean up)

Dọn dẹp màn hình terminal bị loạn và xóa bộ nhớ lịch sử các lệnh đã gõ:

```bash
history -c && rm ~/.bash_history && clear

```