import yfinance as yf
import pandas as pd
import ta
import requests
import time
import os
import numpy as np
from scipy.stats import linregress
from datetime import datetime

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

RESULTS_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRPYwOAHp2nWb917nR9F5QUX37yGhV7dN6q_-0falsOQx9u9BSoOKWzaHGQjPk9vQA664BiBhpC9q0H/pub?output=csv"

# ================= TELEGRAM =================
def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": message})

# ================= TRENDLINE FUNCTION =================
def trendline_distance(series, kind="support", lookback=252, swings=5):
    """
    Returns % distance of current price from 1-year trendline
    using last 4–5 major swing highs/lows
    """
    data = series.tail(lookback).reset_index(drop=True)

    if kind == "support":
        pivots = data[(data.shift(1) > data) & (data.shift(-1) > data)]
    else:
        pivots = data[(data.shift(1) < data) & (data.shift(-1) < data)]

    pivots = pivots.tail(swings)

    if len(pivots) < 3:
        return None

    x = np.array(pivots.index)
    y = pivots.values

    slope, intercept, *_ = linregress(x, y)

    projected_price = slope * (len(data) - 1) + intercept
    current_price = data.iloc[-1]

    return ((current_price - projected_price) / current_price) * 100

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

        # ===== Indicators =====
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

        # ===== Metrics =====
        vol_spike = ((volume.iloc[-1] - vol_avg.iloc[-1]) / vol_avg.iloc[-1]) * 100
        ema50_dist = ((last_close - ema50.iloc[-1]) / ema50.iloc[-1]) * 100
        ema200_dist = ((last_close - ema200.iloc[-1]) / ema200.iloc[-1]) * 100
        vwap_dist = ((last_close - vwap.iloc[-1]) / vwap.iloc[-1]) * 100
        atr_pct = (atr.iloc[-1] / last_close) * 100

        # ===== Candle Strength =====
        body = abs(last_close - last_open)
        candle_range = last_high - last_low
        body_ratio = body / candle_range if candle_range else 0

        # ===== Trendlines (1Y, 4–5 swings) =====
        support_line_pct = trendline_distance(close, kind="support", swings=5)
        resistance_line_pct = trendline_distance(close, kind="resistance", swings=5)

        # ===== Direction =====
        direction = "🟢📈" if last_close > ema200.iloc[-1] else "🔴📉"

        # ===== Score (internal ranking only) =====
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

        # ===== MESSAGE =====
        msg = (
            f"{direction} {symbol} | {company}\n"
            f"• Volume Spike: {vol_spike:.0f}%\n"
            f"• EMA200: {ema200_dist:.2f}% | EMA50: {ema50_dist:.2f}%\n"
            f"• VWAP: {vwap_dist:.2f}% | ATR: {atr_pct:.2f}%\n"
            f"• MACD: {'Bullish' if macd_diff.iloc[-1] > 0 else 'Bearish'}"
        )

        if support_line_pct is not None and resistance_line_pct is not None:
            msg += (
                f"\n• Resistance line is {abs(resistance_line_pct):.1f}% "
                f"and support line is {abs(support_line_pct):.1f}% from current price"
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
