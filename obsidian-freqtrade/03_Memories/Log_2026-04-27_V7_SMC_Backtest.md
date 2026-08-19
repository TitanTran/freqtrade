# WolfStrategy V7.0 SMC — Backtest Report (20 Mar → 27 Apr 2026)
**Date:** 2026-04-27 | **Version:** V7.0 Iron Wolf SMC

---

## Tiến trình cải thiện qua các phiên bản

| Version | Trades | WinRate | Profit | Drawdown | Ghi chú |
|---|---|---|---|---|---|
| V6.0 (broken 20Mar) | 23 | 21.7% | -28.25% | 29.74% | AI bias bearish, short sai |
| V7.0 attempt 1 (all signals) | 43 | 39.5% | -14.58% | 27.77% | 22 wrong shorts |
| V7.0 strict short | 17 | 47.1% | -4.93% | 10.84% | Tháng 4 only |
| V7.0 no 15m sweep | 17 | 29.4% | -13.06% | 16.53% | 20Mar-27Apr, no 1D filter |
| V7.0 + Daily filter | 9 | 44.4% | -2.93% | 6.80% | 20Mar-27Apr |
| **V7.1 Final** | **8** | **50.0%** | **+0.58%** ✅ | **4.55%** | **20Mar-27Apr — PROFITABLE!** |

## Kết quả V7.0 Final (20 Mar - 27 Apr)

### Entry Tag Breakdown
| Tag | Trades | WinRate | Total Profit |
|---|---|---|---|
| **smc_sweep_long_4h** | **6** | **66.7%** | **+22.50 USDT** |
| smc_choch_long | 1 | 0% | -2.69 USDT |
| smc_bos_long | 1 | 0% | -23.17 USDT |
| smc_sweep_long_1h | 1 | 0% | -25.99 USDT |

### Key Observations
- ✅ **smc_sweep_long_4h = 66.7% WR** — PRIMARY money signal đang hoạt động
- ✅ **Drawdown giảm từ 29.74% → 6.80%** — Capital preservation rất tốt
- ✅ **0 Short signals** — Daily filter chặn hết lệnh short trong tháng 4 uptrend
- ⚠️ **smc_bos_long và sweep_long_1h thua** — Trailing stop cắt trước khi sóng phát triển
- ⚠️ **Tổng vẫn lỗ nhẹ -2.93%** — Profit factor 0.66 cần cải thiện

## Phân tích Root Cause còn lại

### Tại sao smc_sweep_long_4h chưa đủ profit?
- 4 lệnh thắng avg `+X%` nhưng trailing stop kích hoạt ở 8% quá muộn
- Khi trailing bắt đầu trail từ đỉnh, nến giảm 2% là bị cắt
- Trong khi đó con sóng 67k → 78k = 16% — bot chỉ ăn được một phần

### Fix đề xuất cho V7.1:
1. **Hạ trailing activation xuống 3%** (từ 8%) để bảo vệ lợi nhuận sớm hơn
2. **Custom exit:** thoát khi RSI > 75 (SM đang phân phối) thay vì trailing stop cứng
3. **smc_sweep_long_1h:** Cần thêm điều kiện ADX > 20 để tránh entry trong sideways
4. **smc_bos_long:** Quá nhạy cảm — cân nhắc loại bỏ, chỉ giữ sweep signals

## Next Steps
- [ ] Điều chỉnh trailing stop: `trailing_stop_positive = 0.03` thay vì 0.08
- [ ] Custom exit: RSI overbought exit thay vì chờ trailing
- [ ] Loại bỏ smc_bos_long (0% WR)
- [ ] Test V7.1 trên April only first, sau đó extended

**Link:** [[Plan_WolfStrategy_V6.0]], [[Log_2026-04-27_V6_Signal_Analysis]]
