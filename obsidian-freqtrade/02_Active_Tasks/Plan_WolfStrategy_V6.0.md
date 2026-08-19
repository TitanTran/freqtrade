# IMPLEMENTATION PLAN: WolfStrategy V6.0 — THE IRON WOLF
**Date Created:** 2026-04-27
**Target:** +30% to +40% ROI / month | Max Drawdown < 10%
**Capital:** ~$295 USDT (after current drawdown)
**Leverage:** 5x Fixed
**Status:** 🔴 PENDING IMPLEMENTATION

---

## 🎯 Philosophy Shift
> V5.90 là một "Thợ Săn Mù" — vào lệnh nhiều, thoát lệnh chậm, không có kỷ luật tài khoản.
> V6.0 sẽ là "Sniper có Giáp" — ít lệnh hơn, thoát nhanh hơn, bảo vệ vốn tuyệt đối.

---

## 📋 Fix Checklist (Theo thứ tự ưu tiên)

### 🔴 FIX #1: Xóa Dead Code Override (CRITICAL)
**File:** `WolfStrategy.py` dòng 350-362
**Hành động:** Xóa bỏ bản định nghĩa thứ 2 của `long_precision_cond` và `short_precision_cond` (dòng 350-362). Giữ lại bản tốt hơn ở dòng 308-327 nhưng bổ sung thêm `mfi_low_divergence` vào đó.
- [ ] Merge điều kiện hai bản thành một điều kiện duy nhất
- [ ] Thêm lại `macro_bearish_4h` vào short
- [ ] Thêm lại `rsi < 40` vào long precision

### 🔴 FIX #2: Harmonize Exit Timeframe (CRITICAL)
**File:** `WolfStrategy.py` dòng 474-491
**Hành động:** Thay exit condition từ khung 1H sang khung 15m.
```python
# TRƯỚC (CHẬM - 1H)
exit_long_cond = (df["close"] < df["ema_50_1h"]) & (df["ema_20_1h"] < df["ema_50_1h"])

# SAU (NHANH - 15m)
exit_long_cond = (
    (df["close"] < df["ema_25"])       # Gãy EMA 25 (15m)
    & (df["rsi"] < 50)                  # RSI xác nhận suy yếu
    & (df["macd"] < df["macdsignal"])  # MACD xác nhận đảo chiều
)
```
- [ ] Viết lại `exit_long_cond` dùng EMA 25 (15m)
- [ ] Viết lại `exit_short_cond` dùng EMA 25 (15m)

### 🔴 FIX #3: Sửa Logic Panic Sniper (HIGH)
**File:** `WolfStrategy.py` dòng 364-371
**Hành động:** Panic Sniper hiện đang KÍCH HOẠT khi volume > 3x mean — đây là Vi phạm Safety Checklist. Phải sửa thành BỘ LỌC (chặn entry khi volume climax) KHÔNG PHẢI điều kiện vào lệnh.
```python
# TRƯỚC: Bắt đáy khi volume điên rồ (Sai!)
long_panic_cond = (df["volume"] > df["volume_mean"] * 3) & ...

# SAU: Bắt đáy KHI volume ổn định sau một cú climax (Đúng!)
volume_climax_recent = (df["volume"].shift(1) > df["volume_mean"].shift(1) * 3)
long_panic_cond = (
    volume_climax_recent                             # Cú spike đã xảy ra ở nến TRƯỚC
    & (df["volume"] < df["volume_mean"] * 1.5)      # Hiện tại volume đã bình thường
    & (df["low"] < df["bb_lowerband"])
    & (df["close"] > df["open"])                    # Nến xanh xác nhận hồi phục
    & (df["rsi"] < 35)                              # Còn ở vùng oversold
    & (df["macro_bullish_4h"])                      # Chỉ Long khi 4H còn bullish
)
```
- [ ] Thay `volume_mean * 3` trigger thành look-back 1 nến
- [ ] Thêm `macro_bullish_4h` filter
- [ ] Thêm RSI oversold < 35 filter

### 🟠 FIX #4: Tightened Stoploss + Trailing (HIGH)
**File:** `WolfStrategy.py` dòng 18-20
```python
# V6.0: Chặt chẽ hơn
stoploss = -0.035          # 3.5% giá = 17.5% margin loss (chấp nhận được)
trailing_stop = True
trailing_stop_positive = 0.02   # Kích hoạt trailing sau khi đạt +2%
trailing_stop_positive_offset = 0.025  # Trailing lock tại +2.5%
trailing_only_offset_is_reached = True
```
- [ ] Sửa `stoploss` từ -0.12 xuống -0.035
- [ ] Bật `trailing_stop = True`
- [ ] Cấu hình `trailing_stop_positive` và `trailing_stop_positive_offset`

### 🟠 FIX #5: Tăng AI Score Threshold (MEDIUM)
**File:** `WolfStrategy.py`
**Hành động:** Ngưỡng hiện tại `predict_col > 0.0` quá thấp. Tăng lên `> 0.02` cho Long và `< -0.02` cho Short để chỉ vào lệnh khi AI thực sự tự tin.
- [ ] Thay ngưỡng AI Long từ `0.0` lên `0.02`
- [ ] Thay ngưỡng AI Short từ `-0.01` xuống `-0.02`

### 🟡 FIX #6: Thêm Emergency Custom Exit (MEDIUM)
**File:** `WolfStrategy.py` `custom_exit()` dòng 68-92
**Hành động:** Thêm bộ cắt lỗ kỹ thuật sớm khi lệnh đi ngược chiều mạnh.
```python
# Cắt lỗ khẩn cấp: Lỗ > 2% VÀ momentum tiếp tục đi ngược
if current_profit < -0.02 and last_candle["rsi"] > 65 and trade.trade_direction == "short":
    return "emergency_exit_short"
if current_profit < -0.02 and last_candle["rsi"] < 35 and trade.trade_direction == "long":
    return "emergency_exit_long"
```
- [ ] Thêm emergency exit cho Short (RSI > 65)
- [ ] Thêm emergency exit cho Long (RSI < 35)

---

## 📊 Expected Performance (Post-Fix Projection)

| Metric | V5.90 (Actual) | V6.0 (Projected) |
| --- | --- | --- |
| Win Rate | 45.83% | **65-70%** |
| Monthly ROI | -9.27% | **+30% to +40%** |
| Max Drawdown | 20.64% | **< 8%** |
| Avg Trade Duration | 11h | **2-4h** |
| Profit Factor | 0.71 | **> 2.0** |

---

## 🗓️ Deployment Plan
1. **Ngày 27/04:** Implement tất cả fix trên local (không deploy live).
2. **Ngày 28-29/04:** Backtest lại với dữ liệu 20/03 - 27/04 để xác nhận.
3. **Ngày 30/04:** Deploy lên VPS và chạy dry-run 48h.
4. **Ngày 02/05:** Nếu dry-run hợp lý, switch sang live với capital $295.

---

## 📂 Files to Modify
- `user_data/strategies/WolfStrategyV1/WolfStrategy.py` — Code fixes
- `user_data/strategies/WolfStrategyV1/config.json` — Giữ nguyên (OK)

## Links
- Post-mortem: [[Log_2026-04-27_V590_PostMortem]]
- Safety Checklist: [[Strategy_Safety_Checklist]]
