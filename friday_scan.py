import yfinance as yf
import pandas as pd
import ta
import requests
import time
import os
import numpy as np
from datetime import datetime

# ================= TELEGRAM CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# ================= LOAD STOCK UNIVERSE =================
with open("stocks.txt") as f:
    stocks = [x.strip().upper() + ".NS" for x in f if x.strip()]

# ================= LOAD RESULT CALENDAR =================
RESULTS_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRPYwOAHp2nWb917nR9F5QUX37yGhV7dN6q_-0falsOQx9u9BSoOKWzaHGQjPk9vQA664BiBhpC9q0H/pub?output=csv"

results_map = {}
try:
    rdf = pd.read_csv(RESULTS_URL)
    rdf["Security Name"] = rdf["Security Name"].str.upper().str.strip()
    rdf["Result Date"] = pd.to_datetime(rdf["Result Date"], errors="coerce")
    results_map = dict(zip(rdf["Security Name"], rdf["Result Date"]))
except:
    pass

# ================= SUPPORT / RESISTANCE (1 YEAR, SWINGS) =================
def support_resistance(close, lookback=252):
    data = close.tail(lookback)
    highs = data.nlargest(5)
    lows = data.nsmallest(5)
    resistance = highs.mean()
    support = lows.mean()
    return support, resistance

# ================= MAIN SCAN =================
candidates = []
today = datetime.today().date()

for i, stock in enumerate(stocks, 1):
    try:
        t = yf.Ticker(stock)
        df = t.history(period="1y")

        if df.empty or len(df) < 200:
            continue

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]

        last_close = close.iloc[-1]

        ema50 = close.ewm(span=50).mean().iloc[-1]
        ema200 = close.ewm(span=200).mean().iloc[-1]

        ema50_pct = ((last_close - ema50) / ema50) * 100
        ema200_pct = ((last_close - ema200) / ema200) * 100

        vwap = (volume * (high + low + close) / 3).cumsum() / volume.cumsum()
        vwap_pct = ((last_close - vwap.iloc[-1]) / vwap.iloc[-1]) * 100

        atr = ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range().iloc[-1]
        atr_pct = (atr / last_close) * 100

        macd = ta.trend.MACD(close).macd_diff()
        macd_signal = "Bullish" if macd.iloc[-1] > 0 and macd.iloc[-2] < 0 else \
                      "Bearish" if macd.iloc[-1] < 0 and macd.iloc[-2] > 0 else "Neutral"

        vol_avg = volume.rolling(20).mean().iloc[-1]
        vol_spike = ((volume.iloc[-1] - vol_avg) / vol_avg) * 100 if vol_avg else 0

        support, resistance = support_resistance(close)
        support_pct = ((support - last_close) / last_close) * 100
        resistance_pct = ((resistance - last_close) / last_close) * 100

        score = (
            min(vol_spike / 10, 30)
            + (5 - abs(ema50_pct))
            + (5 - abs(ema200_pct))
            + (5 - abs(vwap_pct))
            + (10 if macd_signal != "Neutral" else 0)
        )

        direction = "🟢📈" if last_close > ema200 else "🔴📉"

        symbol = stock.replace(".NS", "")
        name = t.info.get("shortName", "")

        msg = (
            f"{direction} {symbol} | {name}\n"
            f"• Volume Spike: {vol_spike:.0f}%\n"
            f"• EMA200: {ema200_pct:.2f}% | EMA50: {ema50_pct:.2f}%\n"
            f"• VWAP: {vwap_pct:.2f}% | ATR: {atr_pct:.2f}%\n"
            f"• MACD: {macd_signal}\n"
            f"• Resistance is {resistance_pct:.1f}% up and support is {abs(support_pct):.1f}% down of current price"
        )

        if symbol in results_map and pd.notna(results_map[symbol]):
            msg += f"\n• Result Date: {results_map[symbol].strftime('%d %B %Y')}"

        candidates.append((score, msg))

    except:
        pass

    if i % 25 == 0:
        time.sleep(2)

# ================= SEND TELEGRAM =================
candidates.sort(reverse=True)

final_msg = "🟢 TOP 20 EOD SETUPS\n\n"
for _, m in candidates[:20]:
    final_msg += m + "\n\n"

send_telegram(final_msg)
send_telegram("✅ EOD Scan completed successfully")
