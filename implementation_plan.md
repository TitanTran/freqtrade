# Cứu hộ "Cháy Tài Khoản" - WolfStrategyAlt

Bot đang bị "bào" mòn tài khoản do tỷ lệ Winrate quá thấp (32.9%) so với tỷ lệ dính Stoploss (hit rate ~67%). Tỷ lệ cược (Risk:Reward) hiện tại là Lời 25% / Lỗ 16% chưa đủ bù đắp lại lượng lệnh bị quét stoploss do độ nhiễu của thị trường (Crypto Alts giật 1.5% rất dễ) cộng đòn bẩy 10X.

Dưới đây là kế hoạch sửa chữa toàn diện chiến lược để bot bảo vệ vốn tốt hơn, đồng thời ngắm bắn chuẩn xác hơn:

## Đề xuất thay đổi

### 1. Kích hoạt & Tối ưu Dynamic Risk Management (Trailing Stop + ROI)
Code hiện tại đang bị "chốt non" hoặc quét SL sớm. Chúng ta sẽ thay đổi cách tiếp cận:
- **Hành động:** 
  - [MODIFY] Thay đổi `minimal_roi`: Để mốc 0.25 (25%) nhưng thêm các mốc cao hơn hoặc dãn ra để cho phép `trailing_stop` làm việc.
  - [MODIFY] Bật `trailing_stop = True`: Cấu hình `trailing_stop_positive` và `trailing_stop_positive_offset` để bám sát xu hướng khi đã có lãi.
  - [MODIFY] Mở lại và nâng cấp hàm `custom_stoploss`: 
    - Giai đoạn 1: Bảo vệ vốn (Move to Breakeven) khi đạt mức lợi nhuận nhỏ (VD: 2% gốc ~ 20% đòn bẩy).
    - Giai đoạn 2: Trailing theo ATR để không bị văng bởi nhiễu 5m nhưng vẫn giữ được lãi khi trend đảo chiều mạnh.

### 2. Market Trend Filter (Khung 1D)
Ngăn chặn Bot vào lệnh khi xu hướng lớn của thị trường đang sụp đổ.
- **Hành động:**
  - [MODIFY] `informative_pairs`: Thêm cặp tiền ở khung `1d`.
  - [MODIFY] `populate_indicators`: Tính toán EMA 50/200 hoặc nến Heikin Ashi trên khung `1d` để xác định "mùa" giao dịch.
  - [MODIFY] `populate_entry_trend`: Thêm điều kiện: Chỉ `enter_long` khi giá 1D > EMA và `enter_short` khi giá 1D < EMA (hoặc tùy biến theo yêu cầu).

### 3. Sửa lỗi Window của VWAP (24h)
Chiến lược đang chạy khung 5m (do config override), nên window 96 chỉ là 8 tiếng.
- **Hành động:** 
  - [MODIFY] Cập nhật `window=288` trong `populate_indicators` để khớp với 24 giờ thực tế ở khung 5m.

### 3. Tăng cường "Mắt thần" cho AI (Feature Engineering)
Nhìn vào hàm `feature_engineering_expand_all`, AI hiện tại đang bị "bịt mắt". Bạn đã xoá bỏ MACD, RSI, ADX... nên dữ liệu huấn luyện (Training Data) của AI chỉ có đúng 2 feature là `OBV` và `Bollinger Band Width`. AI không có khái niệm về việc giá đang "quá mua/quá bán" hay xung lượng đang kiệt sức.
- **Hành động:**
  - [NEW] Bổ sung thêm một vài chỉ báo cốt yếu nhưng nhẹ nhàng vào Data Train: Khoảng cách giá đến VWAP (Distance to VWAP), ROC (Rate of Change - để đo gia tốc giá) và RSI (cơ bản để lọc nhiễu vùng đỉnh/đáy).
  - Điều này giúp FreqAI đưa ra xác suất `> 0.65` đáng tin cậy hơn, nâng tỷ lệ Winrate lên thay vì chỉ cược mù sờ voi.

### 4. Tối ưu lại Target Engineering của mô hình AI
- **Hành động:**
  - Ở `5m`, `horizon=48` (4 tiếng) là hợp lý. 
  - Tuy nhiên, ta nên thu hẹp nhẹ `max_loss` trong điều kiện nhãn, để bắt AI tìm các vùng Setup cực kỳ an toàn (Risk cực thấp).

## Open Questions

- Bạn có muốn tôi giữ lại nguyên mức chốt lời cứng (`minimal_roi = {"0": 0.25}`) hay tôi có thể điều chỉnh lại mốc này kết hợp với `Trailing Stop` để bot "ăn" được những đoạn trend dài hơn thay vì chốt non?
- Bạn có muốn thêm tính năng khoá Trading khi thị trường quá xấu (Market Trend Filter bằng khung 1D) không?

## Verification Plan
1. Xóa toàn bộ file Model cũ để huấn luyện lại FreqAI với các Data Features mới.
2. Chạy lại Backtest qua `docker-compose run` hoặc Terminal nội bộ trong giai đoạn `2026-02-01` đến `2026-03-29`.
3. So sánh báo cáo (Winrate, Max Drawdown). Mục tiêu giảm Max Drawdown dưới mức hiện tại (84%).
