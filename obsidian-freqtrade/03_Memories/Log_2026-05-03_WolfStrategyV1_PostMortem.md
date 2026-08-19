---
title: "Post-Mortem: Lỗi Logic Chí Mạng Trong WolfStrategy V1"
date: "2026-05-03"
tags: ["#lessons_learned", "#smc", "#freqtrade", "#strategy", "#postmortem"]
---

# Lỗi Logic Chí Mạng Trong WolfStrategy V1 (Thua Lỗ Liên Tục)

File này lưu trữ những bài học cốt lõi từ việc phân tích mã nguồn `WolfStrategy.py` (V7.0/V8.5 SMC) khi bot chạy thực tế (hoặc backtest) gặp tình trạng liên tục thua lỗ. Mục tiêu là **TUYỆT ĐỐI KHÔNG MẮC LẠI** trong quá trình thiết kế và nâng cấp các phiên bản tiếp theo.

## Danh Sách Các Lỗi Chí Mạng Đã Phát Hiện

### 1. Mâu Thuẫn Giữa Triết Lý (SMC) và Thực Thi (Momentum Lagging)
- **Vấn đề:** Code mất rất nhiều dòng tính toán các chỉ báo SMC nâng cao (như `bos_bullish`, `choch_bullish`, `bull_sweep` ở khung 15m). Tuy nhiên, **KHÔNG CÓ TÍN HIỆU NÀO ĐƯỢC DÙNG** trong `populate_entry_trend`. 
- Thực tế bot vào lệnh bằng `close > ema_50` và `adx > 25`. Đây là chiến lược đánh theo Momentum/Trend có độ trễ cao. Mua khi `ADX > 25` thường dẫn đến việc "đu đỉnh" ngay lúc sóng 15m cạn kiệt, dính ngay nhịp pullback (sweep) thay vì chờ sweep xong mới mua.

### 2. Spam Entry Từ Tín Hiệu Khung Lớn (Signal Spooling)
- **Vấn đề:** Tín hiệu quét thanh khoản 4H (`bull_sweep_4h`) được `rolling(3).max()` để giữ `True` trong suốt 12 tiếng. 
- Tại khung 15m, chỉ cần `bull_sweep_4h` là True thì `enter_long` liên tục được kích hoạt rải rác trong 12 tiếng đó. 
- **Hệ quả:** Nếu lệnh trước dính Stoploss (do chưa tạo đáy xong), bot sẽ ngay lập tức mua tiếp lệnh mới ngay cây nến 15m kế tiếp và tiếp tục dính SL.

### 3. Tỷ Lệ Rủi Ro / Phần Thưởng (RR) Phi Lý Với Đòn Bẩy x5
- **Vấn đề:** Bot fix cứng đòn bẩy `5.0`.
- Stoploss (SL) được fix tĩnh ở mức `-0.04` (BTC) và `-0.06` (Alts). Khi nhân đòn bẩy x5, mỗi lệnh thua tài khoản sẽ **bốc hơi 20% đến 30% margin**. Mức rủi ro này quá kinh khủng cho khung 15m.
- Take Profit (TP) lại được code đòi hỏi quá cao ở hàm `custom_exit`: yêu cầu `current_profit > 0.15` (giá chạy 15% -> x5 là ROI 75%). 
- **Hệ quả:** Thắng được 5-10% không chịu chốt, gồng qua đỉnh và đảo chiều đâm thẳng vào Stoploss. Lẽ ra thắng nhưng thành thua lỗ nặng.

### 4. Mù "Short" Trong Downtrend
- **Vấn đề:** Set `can_short = True` nhưng hàm `populate_entry_trend` không hề có logic cho `enter_short`. 
- **Hệ quả:** Trong downtrend, bot hoàn toàn không có khả năng Short để kiếm tiền, mà chỉ chực chờ bắt dao rơi (bắt đáy Long) dẫn đến rủi ro "cháy tài khoản".

---

## Các Nguyên Tắc Coding Bắt Buộc Từ Nay Về Sau

1. **Nhất Quán Tín Hiệu (Signal Consistency):** 
   - Đã khai báo đánh theo phương pháp gì (SMC, Hành vi giá, Crossover), thì `populate_entry_trend` **BẮT BUỘC** phải gọi chính xác các cột DataFrame của phương pháp đó (`bos`, `choch`, `sweep`).

2. **Khung Thời Gian Kép (Multi-Timeframe Logic):**
   - **Tuyệt đối không lấy Trigger (điểm cò) từ khung lớn (1H, 4H, 1D) để làm tín hiệu mua trực tiếp cho khung nhỏ (15m, 5m).**
   - Khung lớn chỉ dùng làm **BIAS** (Context/Bộ lọc xu hướng). 
   - Khung nhỏ phải có **TRIGGER ĐỘC LẬP** (Ví dụ: Chờ Sweep ở 4H, sau đó phải có BOS/CHoCH tại 15m thì mới kích hoạt `enter_long`).

3. **Quản Lý Vốn Cơ Động (Dynamic Risk Management):**
   - Bắt buộc phải đồng bộ hóa Stoploss và đòn bẩy. Nếu đánh x5, mức SL trên giá chỉ nên ở quanh `1-2%` (tương đương rủi ro 5-10% margin). 
   - Thay vì fix TP cứng, hãy dùng Trailing Stoploss theo ATR hoặc đóng lệnh từng phần (Partial Exit) khi giá chạm các vùng thanh khoản kháng cự/hỗ trợ gần nhất.

4. **Đủ Long - Đủ Short:**
   - Nếu `can_short = True`, phải đảm bảo biến `enter_short` được gán logic đầy đủ, soi gương (mirror) ngược lại với `enter_long`. Không bao giờ bỏ trống.
