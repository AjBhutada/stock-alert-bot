import yfinance as yf
import pandas as pd
import ta
import requests
import time
import os
from datetime import datetime

# ================= TELEGRAM CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    requests.post(url, data=payload)

# ================= LOAD STOCK UNIVERSE =================
with open("stocks.txt", "r") as f:
    stocks = [line.strip() + ".NS" for line in f if line.strip()]

# ================= LOAD RESULT CALENDAR =================
RESULTS_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRPYwOAHp2nWb917nR9F5QUX37yGhV7dN6q_-0falsOQx9u9BSoOKWzaHGQjPk9vQA664BiBhpC9q0H/pub?gid=0&single=true&output=csv"

results_map = {}
try:
    results_df = pd.read_csv(RESULTS_CSV_URL)
    results_df["Security Name"] = results_df["Security Name"].str.upper().str.strip()
    results_df["Result Date"] = pd.to_datetime(
    results_df["Result Date"],
    format="%d-%b-%y",
    errors="coerce"
)
    results_map = dict(zip(results_df["Security Name"], results_df["Result Date"]))
except:
    pass

high_conviction = []
medium_conviction = []

today = datetime.today().date()

# ================= SCAN =================
for i, stock in enumerate(stocks, 1):
    try:
        ticker = yf.Ticker(stock)
        df = ticker.history(period="3mo")

        if df.empty or len(df) < 60:
            continue

        close = df["Close"]
        volume = df["Volume"]
        high = df["High"]
        low = df["Low"]

        ema200 = close.ewm(span=200).mean()
        rsi = ta.momentum.RSIIndicator(close, 14).rsi()
        vol_avg = volume.rolling(20).mean()
        vwap = (volume * (high + low + close) / 3).cumsum() / volume.cumsum()
        macd = ta.trend.MACD(close).macd_diff()

        last_close = close.iloc[-1]
        rsi_val = rsi.iloc[-1]

        ema200_dist = ((last_close - ema200.iloc[-1]) / ema200.iloc[-1]) * 100
        vol_spike = ((volume.iloc[-1] - vol_avg.iloc[-1]) / vol_avg.iloc[-1]) * 100
        vwap_dist = ((last_close - vwap.iloc[-1]) / vwap.iloc[-1]) * 100

        score = 0
        signals = []

        if vol_spike > 50:
            score += 50
            signals.append(f"Volume Spike: +{vol_spike:.0f}%")

        if abs(ema200_dist) < 1:
            score += 30
            signals.append(f"Near EMA200 ({ema200_dist:.2f}%)")

        if abs(vwap_dist) < 1:
            score += 20
            signals.append(f"Near VWAP ({vwap_dist:.2f}%)")

        if macd.iloc[-1] > 0 and macd.iloc[-2] < 0:
            score += 20
            signals.append("MACD Bullish Crossover")
        elif macd.iloc[-1] < 0 and macd.iloc[-2] > 0:
            score += 20
            signals.append("MACD Bearish Crossover")

        if score < 60:
            continue

        direction = "🟢📈" if last_close > ema200.iloc[-1] and rsi_val > 50 else "🔴📉"

        symbol = stock.replace(".NS", "")
        company_name = ""
        try:
            company_name = ticker.info.get("shortName", "")
        except:
            pass

        header = f"{direction} {symbol}"
        if company_name:
            header += f" | {company_name}"

        entry = header + "\n" + "\n".join(signals)

        if symbol in results_map:
            rd = results_map[symbol]
            if pd.notna(rd):
                entry += f"\nResult Date: {rd.strftime('%d %B %Y')}"

        if score >= 90:
            high_conviction.append((score, entry))
        else:
            medium_conviction.append((score, entry))

    except:
        pass

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

if not high_conviction and not medium_conviction:
    send_telegram("ℹ️ EOD Scan completed. No high-probability setups today.")

