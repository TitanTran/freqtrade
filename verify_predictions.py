import pandas as pd
import glob
import sys
files = glob.glob("user_data/models/altcoin_guerrilla_10x_15m/backtesting_predictions/*_prediction.feather")
if not len(files):
    print("No prediction files found")
    sys.exit(1)
f = files[0]
df = pd.read_feather(f)
print(f"Columns in {f}:")
print(df.columns)
print("\nMax values for probability columns:")
for col in df.columns:
    if 'target' in col:
        print(f"{col}: {df[col].max()}")
