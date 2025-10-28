import yfinance as yf
import pandas as pd
import numpy as np
import requests
import datetime as dt
import sqlite3
import pytz
import os
# Removed ta library imports due to 2D array issues - using manual calculations instead

# ============== CONFIG ===================
NIFTY_SYMBOL = "^NSEI"          # Yahoo Finance ticker for Nifty 50
GOLDBEES_SYMBOL = "GOLDBEES.NS" # Yahoo Finance ticker for GOLDBEES
INTERVAL = "1h"                 # 1-hour candles
LOOKBACK = "60d"                # pull 60 days to ensure sufficient history
BB_WINDOW = 130                 # ≈ 30 calendar days (20 trading days × 6.5 hours/day)
BB_STD_DEV = 2
RSI_WINDOW = 30                 # smoother RSI for hourly timeframe
VOL_AVG_WINDOW = 30             # compare current vol vs avg of last 30 bars
DB_FILE = "signals.db"
COOLDOWN_HOURS = 4
# Read from environment variables (for GitHub Actions) or use defaults (for local testing)
ONESIGNAL_API_KEY = os.getenv("ONESIGNAL_API_KEY", "os_v2_app_flemraywrrfczap5lf54vaqxpmaclo6ceunus6mkir6nay4nyd6sd374zuwuggryxteo2udfrxzrrc4yrxxcxlyfmbm4bs6zqtmsrca")
ONESIGNAL_APP_ID = os.getenv("ONESIGNAL_APP_ID", "2ac8c883-168c-4a2c-81fd-597bca82177b")
TZ = pytz.timezone("Asia/Kolkata")
# =========================================

def send_onesignal(title, msg):
    try:
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": ONESIGNAL_API_KEY
        }
        payload = {
            "app_id": ONESIGNAL_APP_ID,
            "target_channel": "push",
            "headings": {"en": title},
            "contents": {"en": msg},
            "included_segments": ["Total Subscriptions"]
        }
        response = requests.post(
            "https://api.onesignal.com/notifications",
            headers=headers,
            json=payload
        )
        if response.status_code == 200:
            print(f"OneSignal notification sent: {title}")
        else:
            print(f"OneSignal error: {response.status_code} - {response.text}")
    except Exception as e:
        print("OneSignal error:", e)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
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

def last_event_time(symbol, event_type):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT timestamp FROM signals WHERE symbol=? AND event=? ORDER BY id DESC LIMIT 1", (symbol, event_type))
    row = cur.fetchone()
    conn.close()
    return pd.to_datetime(row[0]) if row else None

def log_event(symbol, event_type, row, rsi, vol_ratio):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    # Extract scalar values for calculation - handle both scalar and Series
    def extract_float(val):
        try:
            # Handle simple scalar types first
            if isinstance(val, (int, float)):
                return 0.0 if (isinstance(val, float) and np.isnan(val)) else float(val)
            
            # For pandas Series, extract the raw numpy scalar
            if isinstance(val, pd.Series):
                if len(val) == 0:
                    return 0.0
                # Use .values[0] to get numpy scalar, avoiding pandas indexing
                raw_val = val.values[0]
                # Check if it's nan using numpy
                if isinstance(raw_val, (float, np.floating)) and np.isnan(raw_val):
                    return 0.0
                return float(raw_val)
            
            # Fallback for other types
            return float(val)
        except (ValueError, TypeError, IndexError, AttributeError):
            return 0.0
    
    close_val = extract_float(row["Close"])
    close_prev_val = extract_float(row["Close_prev"])
    change_pct = ((close_val - close_prev_val) / close_prev_val * 100) if close_prev_val != 0 else 0.0
    
    bb_lband_val = extract_float(row["bb_lband"])
    rsi_val = extract_float(rsi)
    vol_ratio_val = extract_float(vol_ratio)
    
    cur.execute("""
        INSERT INTO signals (symbol, timestamp, event, close, lower_band, rsi, vol_ratio, change_pct, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        symbol,
        str(row.name),
        event_type,
        close_val,
        bb_lband_val,
        rsi_val,
        vol_ratio_val,
        change_pct,
        dt.datetime.now(TZ).isoformat()
    ))
    conn.commit()
    conn.close()
    print(f"[{symbol}] [{event_type}] logged at {row.name}")

def within_cooldown(symbol, event_type, timestamp):
    last_ts = last_event_time(symbol, event_type)
    if last_ts is None:
        return False
    diff_hours = (pd.to_datetime(timestamp) - last_ts).total_seconds() / 3600
    return diff_hours < COOLDOWN_HOURS

def check_symbol_alerts(symbol, display_name):
    """Generic function to check dip and reversal alerts for any symbol"""
    
    # ---------- Fetch data ----------
    data = yf.download(symbol, period=LOOKBACK, interval=INTERVAL, auto_adjust=True)
    if data.empty:
        print(f"No data retrieved for {display_name}.")
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
    # Calculate midpoint between middle band and lower band (early warning level)
    data["bb_mid_lower"] = (data["bb_mavg"] + data["bb_lband"]) / 2

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
        print(f"Warning: volume data missing for {display_name} (expected for index).")

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
        last_volume = float(last["Volume"].iloc[0]) if hasattr(last["Volume"], 'iloc') else float(last["Volume"])
        vol_ratio = last_volume / vol_avg

    ts = last.name  # already in IST

    # Extract scalar values for comparison
    # Use .item() or direct access since last/prev are already Series from .iloc[-1]
    last_close = float(last["Close"]) if isinstance(last["Close"], (int, float)) else float(last["Close"].iloc[0])
    last_open = float(last["Open"]) if isinstance(last["Open"], (int, float)) else float(last["Open"].iloc[0])
    last_bb_lband = float(last["bb_lband"]) if isinstance(last["bb_lband"], (int, float)) else float(last["bb_lband"].iloc[0])
    last_bb_mid_lower = float(last["bb_mid_lower"]) if isinstance(last["bb_mid_lower"], (int, float)) else float(last["bb_mid_lower"].iloc[0])
    last_bb_mavg = float(last["bb_mavg"]) if isinstance(last["bb_mavg"], (int, float)) else float(last["bb_mavg"].iloc[0])
    last_rsi = float(last["rsi"]) if isinstance(last["rsi"], (int, float)) else float(last["rsi"].iloc[0])
    prev_close = float(prev["Close"]) if isinstance(prev["Close"], (int, float)) else float(prev["Close"].iloc[0])
    prev_bb_lband = float(prev["bb_lband"]) if isinstance(prev["bb_lband"], (int, float)) else float(prev["bb_lband"].iloc[0])
    prev_bb_mid_lower = float(prev["bb_mid_lower"]) if isinstance(prev["bb_mid_lower"], (int, float)) else float(prev["bb_mid_lower"].iloc[0])

    # ---------- Stage 0: Early Warning - Price in warning zone ----------
    if (last_close < last_bb_mid_lower) and (last_close > last_bb_lband):
        if not within_cooldown(symbol, "Dip Warning", ts):
            log_event(symbol, "Dip Warning", last, last_rsi, vol_ratio)
            msg = (f"{display_name} Dip Warning ⚠️\n"
                   f"Price in warning zone\n"
                   f"Close: {last_close:.2f}\n"
                   f"Warning Level: {last_bb_mid_lower:.2f}\n"
                   f"RSI({RSI_WINDOW}): {last_rsi:.1f}\n"
                   f"Vol/Avg({VOL_AVG_WINDOW}): {vol_ratio if vol_ratio else 'N/A'}")
            send_onesignal(f"{display_name} Dip Warning ⚠️", msg)
        else:
            print(f"{display_name} Dip Warning skipped (within cooldown)")

    # ---------- Stage 1: Dip Detected ----------
    if (last_close < last_bb_lband) and (last_close < last_open):
        if not within_cooldown(symbol, "Dip Detected", ts):
            log_event(symbol, "Dip Detected", last, last_rsi, vol_ratio)
            msg = (f"{display_name} Dip Detected 📉\n"
                   f"Close: {last_close:.2f}\n"
                   f"RSI({RSI_WINDOW}): {last_rsi:.1f}\n"
                   f"Vol/Avg({VOL_AVG_WINDOW}): {vol_ratio if vol_ratio else 'N/A'}")
            send_onesignal(f"{display_name} Dip Detected 📉", msg)
        else:
            print(f"{display_name} Dip Detected skipped (within cooldown)")

    # ---------- Stage 2: Reversal Confirmed ----------
    if (last_close > last_bb_lband) and (last_close > last_open) and (prev_close < prev_bb_lband):
        if not within_cooldown(symbol, "Reversal Confirmed", ts):
            log_event(symbol, "Reversal Confirmed", last, last_rsi, vol_ratio)
            msg = (f"{display_name} Reversal 📈\n"
                   f"Close: {last_close:.2f}\n"
                   f"RSI({RSI_WINDOW}): {last_rsi:.1f}\n"
                   f"Vol/Avg({VOL_AVG_WINDOW}): {vol_ratio if vol_ratio else 'N/A'}")
            send_onesignal(f"{display_name} Reversal Confirmed 📈", msg)
        else:
            print(f"{display_name} Reversal Confirmed skipped (within cooldown)")

def main():
    init_db()
    
    # Check alerts for NIFTY
    print("\n=== Checking NIFTY alerts ===")
    check_symbol_alerts(NIFTY_SYMBOL, "NIFTY")
    
    # Check alerts for GOLDBEES
    print("\n=== Checking GOLDBEES alerts ===")
    check_symbol_alerts(GOLDBEES_SYMBOL, "GOLDBEES")

if __name__ == "__main__":
    main()