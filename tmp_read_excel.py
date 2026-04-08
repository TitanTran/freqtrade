import pandas as pd

excel_file = r'd:\PYTHON\freqtrade\user_data\data\Binance-Lịch-sử-vị-thế-Hợp-đồng-Tương-lai-202604070532(UTC+7)_45468572.xlsx'
try:
    df = pd.read_excel(excel_file, header=9)
    open_time_col = 'Đã mở'
    close_time_col = 'Đã đóng'
    
    dates_open = pd.to_datetime(df[open_time_col], format='%y-%m-%d %H:%M:%S', errors='coerce').dropna()
    dates_close = pd.to_datetime(df[close_time_col], format='%y-%m-%d %H:%M:%S', errors='coerce').dropna()
    
    with open(r'd:\PYTHON\freqtrade\excel_out.txt', 'w', encoding='utf-8') as f:
        f.write(f"Min Open Date: {dates_open.min()}\n")
        f.write(f"Max Open Date: {dates_open.max()}\n")
        f.write(f"Min Close Date: {dates_close.min()}\n")
        f.write(f"Max Close Date: {dates_close.max()}\n")
except Exception as e:
    with open(r'd:\PYTHON\freqtrade\excel_out.txt', 'w', encoding='utf-8') as f:
        f.write(f"ERROR: {e}\n")
