import yfinance as yf
import pandas as pd
import ta
import requests
import time
import os
from datetime import datetime

# ================= TELEGRAM CONFIG (FROM GITHUB SECRETS) =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_telegram(message):
    print("DEBUG BOT_TOKEN:", "SET" if BOT_TOKEN else "MISSING")
    print("DEBUG CHAT_ID:", "SET" if CHAT_ID else "MISSING")

    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets missing")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    r = requests.post(url, data=payload)
    print("Telegram response:", r.text)

send_telegram("✅ Bot test: GitHub Actions → Telegram connection OK")

# ================= LOAD STOCK UNIVERSE =================
with open("stocks.txt", "r") as f:
    stocks = [line.strip() + ".NS" for line in f if line.strip()]

print(f"Loaded {len(stocks)} stocks")

# ================= LOAD RESULT CALENDAR (GOOGLE SHEET) =================
RESULTS_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRPYwOAHp2nWb917nR9F5QUX37yGhV7dN6q_-0falsOQx9u9BSoOKWzaHGQjPk9vQA664BiBhpC9q0H/pub?gid=0&single=true&output=csv"

try:
    results_df = pd.read_csv(RESULTS_CSV_URL)
    results_df["Symbol"] = results_df["Symbol"].str.upper().str.strip()
    results_df["Result_Date"] = pd.to_datetime(results_df["Result_Date"], errors="coerce")
    results_map = dict(zip(results_df["Symbol"], results_df["Result_Date"]))
except Exception as e:
    print("Result calendar error:", e)
    results_map = {}

high_conviction = []
medium_conviction = []

today = datetime.today().date()

# ================= SCAN =================
for i, stock in enumerate(stocks, 1):
    try:
        df = yf.Ticker(stock).history(period="3mo")

        if df.empty or len(df) < 60:
            continue

        close = pd.Series(df["Close"].values, index=df.index)
        volume = pd.Series(df["Volume"].values, index=df.index)
        high = pd.Series(df["High"].values, index=df.index)
        low = pd.Series(df["Low"].values, index=df.index)

        # Indicators
        ema200 = close.ewm(span=200).mean()
        rsi = ta.momentum.RSIIndicator(close, 14).rsi()
        vol_avg = volume.rolling(20).mean()

        # VWAP
        vwap = (volume * (high + low + close) / 3).cumsum() / volume.cumsum()

        # MACD
        macd = ta.trend.MACD(close)
        macd_diff = macd.macd_diff()

        last_close = close.iloc[-1]
        last_volume = volume.iloc[-1]
        rsi_val = rsi.iloc[-1]

        ema200_dist = ((last_close - ema200.iloc[-1]) / ema200.iloc[-1]) * 100
        vol_spike = ((last_volume - vol_avg.iloc[-1]) / vol_avg.iloc[-1]) * 100
        vwap_dist = ((last_close - vwap.iloc[-1]) / vwap.iloc[-1]) * 100

        score = 0
        signals = []

        # 🔥 Volume (highest weight)
        if vol_spike > 50:
            score += 50
            signals.append(f"VOL +{vol_spike:.0f}%")

        # EMA 200 proximity
        if abs(ema200_dist) < 1:
            score += 30
            signals.append(f"Near EMA200: {ema200_dist:.2f}%")

        # RSI extremes
        if rsi_val > 70 or rsi_val < 30:
            score += 20
            signals.append(f"RSI: {rsi_val:.1f}")

        # VWAP proximity
        if abs(vwap_dist) < 1:
            score += 20
            signals.append(f"VWAP: {vwap_dist:.2f}%")

        # MACD crossover
        if macd_diff.iloc[-1] > 0 and macd_diff.iloc[-2] < 0:
            score += 20
            signals.append("MACD: Bullish Crossover")
        elif macd_diff.iloc[-1] < 0 and macd_diff.iloc[-2] > 0:
            score += 20
            signals.append("MACD: Bearish Crossover")

        if score < 60:
            continue

        # Direction
        bias = "🟢📈 BULL" if last_close > ema200.iloc[-1] and rsi_val > 50 else "🔴📉 BEAR"

        # Result date logic
        symbol_clean = stock.replace(".NS", "")
        result_date = results_map.get(symbol_clean)

        result_text = "Not Declared"
        warning = ""

        if pd.notna(result_date):
            result_text = result_date.strftime("%d-%b-%Y")
            days_left = (result_date.date() - today).days
            if 0 <= days_left <= 3:
                warning = " ⚠ Upcoming result in 3 days"

        entry = (
            f"{bias} | {symbol_clean}\n"
            + "\n".join(signals)
            + f"\nResult: {result_text}{warning}"
        )

        if score >= 90:
            high_conviction.append((score, entry))
        else:
            medium_conviction.append((score, entry))

    except Exception as e:
        print(stock, "error:", e)

    # Rate limit safety
    if i % 25 == 0:
        time.sleep(2)

# ================= SEND TELEGRAM =================
high_conviction.sort(reverse=True)
medium_conviction.sort(reverse=True)

if high_conviction:
    msg = "🟢 HIGH CONVICTION SETUPS (EOD)\n\n"
    for _, e in high_conviction[:20]:
        msg += e + "\n\n"
    send_telegram(msg)

if medium_conviction:
    msg = "🟡 MEDIUM CONVICTION SETUPS (EOD)\n\n"
    for _, e in medium_conviction[:30]:
        msg += e + "\n\n"
    send_telegram(msg)



