# TECHNICAL LOG: V5.90 PROPHET WOLF - POST-MORTEM
**Date:** 2026-04-27
**Period Analysed:** 2026-03-25 to 2026-04-27 (Live on VPS)

## 📊 Live Performance Summary
| Metric | Result | Target (V5.10) | Delta |
| --- | --- | --- | --- |
| Total Trades | 24 | - | - |
| Win Rate | **45.83%** | > 70% | 🔴 -24.2% |
| Total ROI | **-9.27% Σ** | > 30% | 🔴 FAIL |
| Max Drawdown | **20.64%** | < 10% | 🔴 DOUBLE |
| Profit Factor | **0.71** | > 1.5 | 🔴 FAIL |
| Expectancy | **-1.13** | Positive | 🔴 FAIL |

## 🔴 Root Cause Analysis (5 Critical Bugs)

### BUG #1: Dead Code Override (CRITICAL)
**Severity: CRITICAL** — Đây là lỗi nghiêm trọng nhất.
Trong `populate_entry_trend`, có 2 cặp biến `long_precision_cond` và `short_precision_cond`
được định nghĩa hai lần. Bản thứ nhất (đủ điều kiện bảo vệ) bị **ghi đè hoàn toàn** bởi bản thứ hai (yếu hơn nhiều).

```python
# LINE 308: Bản 1 - CÓ đủ bộ lọc: RSI < 40, volume, macro_bearish_4h
long_precision_cond = (
    ... & (dataframe["rsi"] < 40)
    ... & (dataframe["macro_bearish_4h"])  # <-- BỘ LỌC 4H
    ... & (dataframe[predict_col] > 0.0)
)

# LINE 350: Bản 2 - OVERRIDE! Không có RSI, không có 4H filter!
long_precision_cond = (  # <-- GHI ĐÈ bản 1
    common_cond
    & (dataframe["mfi_low_divergence"] == 1)
    & (dataframe["close"] > dataframe["ema_25"])
    & (dataframe[predict_col] > 0.01)
)
```
**Hậu quả thực tế:** Lệnh short #24 vào ngày 26/04 đã bỏ qua bộ lọc `macro_bearish_4h`, khiến bot Short vào giữa một uptrend 4H mạnh.

### BUG #2: Thoát lệnh Khung 1H cho lệnh Scalp 15m (CRITICAL)
**Severity: CRITICAL** — Gây ra toàn bộ khoản lỗ của lệnh #24.
`exit_short_cond` (dòng 483) chờ EMA 20 cắt lên EMA 50 trên khung **1H**. Với giao dịch 15m đòn bẩy 5x, độ trễ này biến lỗ 1.5% thành -8%.

### BUG #3: Panic Sniper vào ngược chiều Climax Volume (HIGH)
**Severity: HIGH** — Vi phạm trực tiếp nguyên tắc đã ghi trong [[Strategy_Safety_Checklist]].
`long_panic_cond` (dòng 366) KÍCH HOẠT khi Volume > 3x mean. Nhưng checklist V5.10 nói phải **CHẶN** khi Volume > 3x mean (Volume Climax = Bẫy). Đây là lỗi đảo ngược logic.

### BUG #4: Stoploss Quá Rộng (-12%) (HIGH)
**Severity: HIGH** — Không bảo vệ tài khoản $300.
Với 5x leverage, stoploss -12% = -60% margin. Bot không có cơ chế tự bảo vệ thực sự.

### BUG #5: Trailing Stop Tắt (MEDIUM)
**Severity: MEDIUM** — Bỏ lỡ lợi nhuận.
`trailing_stop = False` khiến bot không khóa được lợi nhuận khi lệnh đang xanh.

---
**Status:** POST-MORTEM COMPLETE → Xem kế hoạch tại [[Plan_WolfStrategy_V6.0]]
