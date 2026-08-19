# TECHNICAL LOG: V6.0 SIGNAL ANALYSIS — WHY BOT MISSED LONG OPPORTUNITIES
**Date:** 2026-04-27
**Analyst:** Post-backtest deep diagnostic

---

## 📊 Market Context (20 Mar - 27 Apr 2026)

| Pair | Price Change | Max DD | Avg ADX | Character |
| --- | --- | --- | --- | --- |
| BTC/USDT | **+11.2%** | -7.9% | 27.5 | TRENDING UP (từ đầu tháng 4) |
| BNB/USDT | **-1.2%** | -11.4% | 25.1 | CHOPPY (giảm Mar, tăng giữa Apr) |

**Top 3 Long Opportunities bị bỏ lỡ:**
1. **14 Apr 04:00** — BTC +5.3% trong 24h | RSI=70 | ADX=36
2. **13 Apr 20:00** — BTC +5.2% trong 24h | RSI=70 | ADX=33
3. **22 Apr 16:00** — BTC +5.1% trong 24h | RSI=66 | ADX=22

---

## 🔬 3 Root Cause (Từ Diagnostic Script)

### BUG A: AI Model Bias Bearish Cực Nặng (PRIMARY ROOT CAUSE)
```
AI Score Distribution (April 2026):
  Mean   : -0.0168  <-- Luôn âm!
  Score > 0.008 (Long)  : 6.0% candles
  Score < -0.008 (Short): 63.0% candles
```
**Nguyên nhân:** Formula target `&-rr_score = max_gain - (max_loss * 2.0)` nhân hệ số **2.0** vào max_loss.
Điều này làm AI luôn "sợ" downside hơn là tin vào upside. Trong uptrend rõ ràng như BTC tháng 4 (+11%), AI vẫn cho điểm âm cho hầu hết candles vì công thức bất công.

**Fix đã áp dụng:** Đổi `* 2.0` → `* 1.2` (cân bằng hơn).

### BUG B: `long_precision_cond` — MATHEMATICAL IMPOSSIBILITY (0 signals)
```
C2: low < local_low (sweep down)  =  5.6% candles
C3: green candle (close > open)   = 51.6% candles
C2 AND C3 simultaneously          =  0.3% candles → thêm điều kiện → 0 signals
```
Điều kiện C2 (quét đáy = nến dump) và C3 (nến xanh đóng) là **loại trừ nhau về mặt vật lý**.
Một cây nến vừa quét đáy mới (tức là đang dump), lại vừa đóng cửa xanh = cực kỳ hiếm.
**Kết quả:** Precision Long không kích hoạt một lần nào trong toàn bộ 2497 nến.

**Fix đã áp dụng:** Thay `low < local_low` bằng `low < bb_lowerband` + `close > bb_lowerband` (BB rejection candle).

### BUG C: `bos_long_rider` — AI threshold quá cao + Signal bị RSI blocked
Các cơ hội Long thực sự (RSI=65-70, ADX=33-36) bị block vì:
1. AI threshold `> 0.02` nhưng AI score trung bình chỉ -0.0168 (không bao giờ đạt)
2. Điều kiện RSI < 70 (no_fomo) chặn đúng các nến pivot khi RSI đang ở 68-70

**Kết quả:** `bos_long_rider` cũng không fire khi BTC đang trending mạnh nhất.

---

## 💡 Key Insight: Bot Short Vào Đâu?
Bot short 5 lần, TẤT CẢ trong tuần **26-29 Mar** và **4-5 Apr**:
- Đây là giai đoạn BTC đang trong downtrend ngắn (tuần 23-29 Mar: -3%, tuần 30 Mar-5 Apr: khởi động lên nhưng chưa rõ)
- `macro_bearish_4h` đúng trong giai đoạn này
- Nhưng `short_bos_cond` và exit 15m đã cắt quá muộn → thua -4%/lần

---

## 📋 Fix Status

| Fix | Mô tả | Đã áp dụng | Kết quả |
| --- | --- | --- | --- |
| A | `max_loss * 2.0` → `1.2` | ✅ | Cần retrain AI |
| B | `long_precision`: BB rejection thay liquidity sweep | ✅ | Cần backtest |
| C | `bos_long`: AI threshold `0.02` → `0.008` + MACD confirm | ✅ | Đang test |
| D | `vwap_bounce_long` signal mới | ✅ | WinRate 0% — vấn đề exit timing |
| E | Exit 15m thêm `macdhist momentum` confirm | ✅ | Cần test |

---

## 🔮 Dự đoán sau khi Fix AI (cần retrain với formula mới)
Với `max_loss * 1.2` thay vì `2.0`:
- Score > 0.008 nên tăng từ **6%** lên ~**30-40%** candles
- Bot sẽ có đủ Long signals trong uptrend BTC tháng 4
- Cần chạy lại backtest sau khi AI được train lại hoàn toàn

---
**Next Action:** `BACKTEST` sau khi AI model được retrain với formula mới
**Link:** [[Plan_WolfStrategy_V6.0]], [[Log_2026-04-27_V590_PostMortem]]
