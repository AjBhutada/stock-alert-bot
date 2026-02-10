import yfinance as yf
import pandas as pd
import ta
import requests
import time
import os
from datetime import datetime

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

RESULTS_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRPYwOAHp2nWb917nR9F5QUX37yGhV7dN6q_-0falsOQx9u9BSoOKWzaHGQjPk9vQA664BiBhpC9q0H/pub?output=csv"

# ================= TELEGRAM =================
def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets missing")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": message})

# ================= LOAD STOCK UNIVERSE =================
with open("stocks.txt", "r") as f:
    STOCKS = [s.strip() + ".NS" for s in f if s.strip()]

# ================= LOAD RESULT CALENDAR =================
results_map = {}
try:
    rdf = pd.read_csv(RESULTS_URL)
    rdf["Security Name"] = rdf["Security Name"].str.upper().str.strip()
    rdf["Result Date"] = pd.to_datetime(
        rdf["Result Date"], format="%d-%b-%y", errors="coerce"
    )
    results_map = dict(zip(rdf["Security Name"], rdf["Result Date"]))
except:
    pass

# ================= SCAN =================
candidates = []

for i, stock in enumerate(STOCKS, 1):
    try:
        ticker = yf.Ticker(stock)
        df = ticker.history(period="9mo")

        if df.empty or len(df) < 120:
            continue

        open_ = df["Open"]
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        volume = df["Volume"]

        # Indicators
        ema50 = close.ewm(span=50).mean()
        ema200 = close.ewm(span=200).mean()
        vwap = (volume * (high + low + close) / 3).cumsum() / volume.cumsum()
        atr = ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range()
        macd_diff = ta.trend.MACD(close).macd_diff()
        vol_avg = volume.rolling(20).mean()

        last_close = close.iloc[-1]
        last_open = open_.iloc[-1]
        last_high = high.iloc[-1]
        last_low = low.iloc[-1]

        # Metrics
        vol_spike = ((volume.iloc[-1] - vol_avg.iloc[-1]) / vol_avg.iloc[-1]) * 100
        ema50_dist = ((last_close - ema50.iloc[-1]) / ema50.iloc[-1]) * 100
        ema200_dist = ((last_close - ema200.iloc[-1]) / ema200.iloc[-1]) * 100
        vwap_dist = ((last_close - vwap.iloc[-1]) / vwap.iloc[-1]) * 100
        atr_pct = (atr.iloc[-1] / last_close) * 100

        # Candle strength
        body = abs(last_close - last_open)
        candle_range = last_high - last_low
        body_ratio = body / candle_range if candle_range else 0

        # ===== Support & Resistance (20-day swing) =====
        lookback = 20
        recent_close = close.tail(lookback)
        support_price = recent_close.min()
        resistance_price = recent_close.max()
        support_pct = ((last_close - support_price) / last_close) * 100
        resistance_pct = ((resistance_price - last_close) / last_close) * 100

        # Direction
        direction = "🟢📈" if last_close > ema200.iloc[-1] else "🔴📉"

        # Score (internal ranking only)
        score = (
            min(vol_spike, 150)
            + (abs(ema200_dist) < 1) * 40
            + (abs(ema50_dist) < 1) * 25
            + (abs(vwap_dist) < 0.5) * 20
            + (macd_diff.iloc[-1] > 0 and macd_diff.iloc[-2] < 0) * 15
            + (body_ratio > 0.6) * 10
        )

        symbol = stock.replace(".NS", "")
        company = ""
        try:
            company = ticker.info.get("shortName", "")
        except:
            pass

        msg = (
            f"{direction} {symbol} | {company}\n"
            f"• Volume Spike: {vol_spike:.0f}%\n"
            f"• EMA200: {ema200_dist:.2f}% | EMA50: {ema50_dist:.2f}%\n"
            f"• VWAP: {vwap_dist:.2f}% | ATR: {atr_pct:.2f}%\n"
            f"• MACD: {'Bullish' if macd_diff.iloc[-1] > 0 else 'Bearish'}\n"
            f"• Resistance is {resistance_pct:.1f}% up and support is {support_pct:.1f}% down of current price"
        )

        if symbol in results_map and pd.notna(results_map[symbol]):
            msg += f"\n• Result Date: {results_map[symbol].strftime('%d %B %Y')}"

        candidates.append((score, msg))

    except:
        pass

    if i % 25 == 0:
        time.sleep(2)

# ================= FINAL TELEGRAM =================
candidates.sort(reverse=True)

if candidates:
    final_msg = "🟢 TOP 20 EOD SETUPS (Ranked)\n\n"
    for _, m in candidates[:20]:
        final_msg += m + "\n\n"
    send_telegram(final_msg)
else:
    send_telegram("ℹ️ No high-quality EOD setups today")

send_telegram("✅ EOD Scan completed successfully")
