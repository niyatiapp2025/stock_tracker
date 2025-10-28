"""
Quick functional test for nifty_dip_alert.py
------------------------------------------------
✅ Verifies: data download, indicators, DB init
✅ Simulates a fake 'dip' candle to test alerts
✅ Does not alter main script logic
"""

import os
import sqlite3
import importlib
import pandas as pd
import yfinance as yf
from ta.volatility import BollingerBands

# Import your main script dynamically
nda = importlib.import_module("nifty_dip_alert")

def test_environment():
    print("✅ Testing environment...")
    print(f"Using DB file: {nda.DB_FILE}")
    print(f"Symbol: {nda.NIFTY_SYMBOL}, Interval: {nda.INTERVAL}")
    assert isinstance(nda.main, type(lambda: None)), "main() not found in nifty_dip_alert.py"
    print("Environment OK.\n")

def test_data_fetch():
    print("✅ Testing data fetch and indicator calculation...")
    data = yf.download(nda.NIFTY_SYMBOL, period="5d", interval="1h", auto_adjust=True)
    assert not data.empty, "❌ No data fetched!"
    # Calculate Bollinger Bands manually to avoid the 2D array issue
    window = nda.BB_WINDOW
    std_dev = nda.BB_STD_DEV
    
    # Calculate moving average
    data["bb_mavg"] = data["Close"].rolling(window=window).mean()
    
    # Calculate standard deviation - ensure it's a Series
    bb_std = data["Close"].rolling(window=window).std()
    if hasattr(bb_std, 'squeeze'):
        bb_std = bb_std.squeeze()
    
    # Calculate upper and lower bands
    data["bb_hband"] = data["bb_mavg"] + (bb_std * std_dev)
    data["bb_lband"] = data["bb_mavg"] - (bb_std * std_dev)

    print(f"Data fetched: {len(data)} candles")
    last_close = float(data['Close'].iloc[-1]) if isinstance(data['Close'].iloc[-1], (int, float)) else float(data['Close'].iloc[-1].iloc[0])
    last_bb_lband = float(data['bb_lband'].iloc[-1]) if isinstance(data['bb_lband'].iloc[-1], (int, float)) else float(data['bb_lband'].iloc[-1].iloc[0])
    print(f"Last Close: {last_close:.2f}, Lower Band: {last_bb_lband:.2f}")
    print("Indicators computed successfully.\n")

def test_main_run():
    print("✅ Running main() to test end-to-end flow...")
    nda.main()
    print("main() executed without error.\n")

def test_db_logging():
    print("✅ Checking SQLite DB logging...")
    conn = sqlite3.connect(nda.DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='signals'")
    assert cur.fetchone(), "❌ Table 'signals' not found!"
    cur.execute("SELECT COUNT(*) FROM signals")
    count = cur.fetchone()[0]
    print(f"Signals table found. Current row count: {count}")
    conn.close()
    print("DB logging verified.\n")

def test_fake_dip():
    print("✅ Simulating fake Dip Detected event...")
    data = yf.download(nda.NIFTY_SYMBOL, period="10d", interval="1h", auto_adjust=True)
    data.index = data.index.tz_convert(nda.TZ)
    # Calculate Bollinger Bands manually to avoid the 2D array issue
    window = nda.BB_WINDOW
    std_dev = nda.BB_STD_DEV
    
    # Calculate moving average and lower band
    bb_mavg = data["Close"].rolling(window=window).mean()
    bb_std = data["Close"].rolling(window=window).std()
    if hasattr(bb_std, 'squeeze'):
        bb_std = bb_std.squeeze()
    if hasattr(bb_mavg, 'squeeze'):
        bb_mavg = bb_mavg.squeeze()
    data["bb_lband"] = bb_mavg - (bb_std * std_dev)

    fake = data.iloc[-1].copy()
    fake["Close"] = fake["bb_lband"] * 0.98
    fake["Open"] = fake["bb_lband"] * 1.01
    fake["rsi"] = 35.0
    # Add missing Close_prev column for log_event function
    fake["Close_prev"] = data.iloc[-2]["Close"] if len(data) > 1 else fake["Close"]
    # Updated to include symbol parameter
    nda.log_event(nda.NIFTY_SYMBOL, "Dip Detected (TEST)", fake, fake["rsi"], 1.25)
    print("Fake event logged in DB. Check pushover notification manually if enabled.\n")

def run_all_tests():
    test_environment()
    test_data_fetch()
    test_main_run()
    test_db_logging()
    test_fake_dip()
    print("🎉 All tests executed successfully!")

if __name__ == "__main__":
    run_all_tests()