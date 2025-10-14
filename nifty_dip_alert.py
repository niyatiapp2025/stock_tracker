import yfinance as yf
import pandas as pd
import numpy as np
import requests
import datetime as dt
import sqlite3
import pytz
# Removed ta library imports due to 2D array issues - using manual calculations instead

# ============== CONFIG ===================
NIFTY_SYMBOL = "^NSEI"          # Yahoo Finance ticker for Nifty 50
INTERVAL = "1h"                 # 1-hour candles
LOOKBACK = "60d"                # pull 60 days to ensure 30-day window has full history
BB_WINDOW = 195                 # ≈ 30 trading days × 6.5 hours/day
BB_STD_DEV = 2
RSI_WINDOW = 30                 # smoother RSI for hourly timeframe
VOL_AVG_WINDOW = 30             # compare current vol vs avg of last 30 bars
DB_FILE = "signals.db"
COOLDOWN_HOURS = 4
PUSHOVER_TOKEN = "a7fgirz5pab2d3q5vn43zd1s113cqp"
PUSHOVER_USER  = "uhn78axoo35a2kpxfr7zkm9yjzypcg"
TZ = pytz.timezone("Asia/Kolkata")
# =========================================

def send_pushover(title, msg):
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_TOKEN, "user": PUSHOVER_USER,
                  "title": title, "message": msg}
        )
    except Exception as e:
        print("Pushover error:", e)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            event TEXT,
            close REAL,
            lower_band REAL,
            rsi REAL,
            vol_ratio REAL,
            change_pct REAL,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def last_event_time(event_type):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT timestamp FROM signals WHERE event=? ORDER BY id DESC LIMIT 1", (event_type,))
    row = cur.fetchone()
    conn.close()
    return pd.to_datetime(row[0]) if row else None

def log_event(event_type, row, rsi, vol_ratio):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    # Extract scalar values for calculation
    close_val = float(row["Close"].iloc[0])
    close_prev_val = float(row["Close_prev"].iloc[0])
    change_pct = ((close_val - close_prev_val) / close_prev_val * 100) if close_prev_val != 0 else 0.0
    
    cur.execute("""
        INSERT INTO signals (timestamp, event, close, lower_band, rsi, vol_ratio, change_pct, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(row.name),
        event_type,
        close_val,
        float(row["bb_lband"].iloc[0]),
        float(rsi),
        float(vol_ratio),
        change_pct,
        dt.datetime.now(TZ).isoformat()
    ))
    conn.commit()
    conn.close()
    print(f"[{event_type}] logged at {row.name}")

def within_cooldown(event_type, timestamp):
    last_ts = last_event_time(event_type)
    if last_ts is None:
        return False
    diff_hours = (pd.to_datetime(timestamp) - last_ts).total_seconds() / 3600
    return diff_hours < COOLDOWN_HOURS

def main():
    init_db()

    # ---------- Fetch data ----------
    data = yf.download(NIFTY_SYMBOL, period=LOOKBACK, interval=INTERVAL)
    if data.empty:
        print("No data retrieved.")
        return

    # Convert timestamps from UTC → IST
    data.index = data.index.tz_convert(TZ)

    # ---------- Indicators ----------

    # Calculate Bollinger Bands manually to avoid the 2D array issue
    # Calculate moving average
    data["bb_mavg"] = data["Close"].rolling(window=BB_WINDOW).mean()
    
    # Calculate standard deviation - ensure it's a Series
    bb_std = data["Close"].rolling(window=BB_WINDOW).std()
    if hasattr(bb_std, 'squeeze'):
        bb_std = bb_std.squeeze()
    
    # Calculate upper and lower bands
    data["bb_hband"] = data["bb_mavg"] + (bb_std * BB_STD_DEV)
    data["bb_lband"] = data["bb_mavg"] - (bb_std * BB_STD_DEV)

    # Calculate RSI manually to avoid the 2D array issue
    def calculate_rsi(prices, window):
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    data["rsi"] = calculate_rsi(data["Close"], RSI_WINDOW)
    data["Close_prev"] = data["Close"].shift(1)

    # guard against NaN volumes
    if data["Volume"].isnull().all().item():
        data["Volume"] = np.nan
        print("Warning: volume data missing for ^NSEI (expected for index).")

    last = data.iloc[-1]
    prev = data.iloc[-2]

    # 30-bar rolling average volume (ignores NaNs)
    vol_avg = data["Volume"].tail(VOL_AVG_WINDOW + 1).head(VOL_AVG_WINDOW).mean()
    # Ensure vol_avg is a scalar value
    if hasattr(vol_avg, 'item'):
        vol_avg = vol_avg.item()
    elif hasattr(vol_avg, 'iloc'):
        vol_avg = vol_avg.iloc[0] if len(vol_avg) > 0 else np.nan
    
    vol_ratio = np.nan
    if not pd.isna(vol_avg) and vol_avg > 0:
        vol_ratio = last["Volume"] / vol_avg

    ts = last.name  # already in IST

    # Extract scalar values for comparison
    last_close = float(last["Close"].iloc[0])
    last_open = float(last["Open"].iloc[0])
    last_bb_lband = float(last["bb_lband"].iloc[0])
    last_rsi = float(last["rsi"].iloc[0])
    prev_close = float(prev["Close"].iloc[0])
    prev_bb_lband = float(prev["bb_lband"].iloc[0])

    # ---------- Stage 1: Dip Detected ----------
    if (last_close < last_bb_lband) and (last_close < last_open):
        log_event("Dip Detected", last, last_rsi, vol_ratio)
        if not within_cooldown("Dip Detected", ts):
            msg = (f"NIFTY Dip Detected 📉\n"
                   f"Close: {last_close:.2f}\n"
                   f"RSI({RSI_WINDOW}): {last_rsi:.1f}\n"
                   f"Vol/Avg({VOL_AVG_WINDOW}): {vol_ratio if vol_ratio else 'N/A'}")
            send_pushover("Dip Detected", msg)
        else:
            print("Dip Detected skipped (within cooldown)")

    # ---------- Stage 2: Reversal Confirmed ----------
    if (last_close > last_bb_lband) and (last_close > last_open) and (prev_close < prev_bb_lband):
        log_event("Reversal Confirmed", last, last_rsi, vol_ratio)
        if not within_cooldown("Reversal Confirmed", ts):
            msg = (f"NIFTY Reversal 📈\n"
                   f"Close: {last_close:.2f}\n"
                   f"RSI({RSI_WINDOW}): {last_rsi:.1f}\n"
                   f"Vol/Avg({VOL_AVG_WINDOW}): {vol_ratio if vol_ratio else 'N/A'}")
            send_pushover("Reversal Confirmed", msg)
        else:
            print("Reversal Confirmed skipped (within cooldown)")

if __name__ == "__main__":
    main()