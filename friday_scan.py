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

TODAY = datetime.now().date()

# ================= TELEGRAM =================
def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# ================= LOAD STOCK UNIVERSE =================
with open("stocks.txt") as f:
    STOCKS = [s.strip() + ".NS" for s in f if s.strip()]

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

top_candidates = []
ema_watch = []

# ================= SCAN =================
for i, stock in enumerate(STOCKS, 1):
    try:
        t = yf.Ticker(stock)
        df = t.history(period="9mo")

        if df.empty or len(df) < 120:
            continue

        o, h, l, c, v = df["Open"], df["High"], df["Low"], df["Close"], df["Volume"]

        # Core indicators
        ema50 = c.ewm(span=50).mean()
        ema200 = c.ewm(span=200).mean()
        vwap = (v * (h + l + c) / 3).cumsum() / v.cumsum()
        atr = ta.volatility.AverageTrueRange(h, l, c, 14).average_true_range()
        macd = ta.trend.MACD(c).macd_diff()
        vol_avg = v.rolling(20).mean()

        last_close = c.iloc[-1]
        last_open = o.iloc[-1]
        last_high = h.iloc[-1]
        last_low = l.iloc[-1]

        # Percent metrics
        vol_spike = ((v.iloc[-1] - vol_avg.iloc[-1]) / vol_avg.iloc[-1]) * 100
        ema50_dist = ((last_close - ema50.iloc[-1]) / ema50.iloc[-1]) * 100
        ema200_dist = ((last_close - ema200.iloc[-1]) / ema200.iloc[-1]) * 100
        vwap_dist = ((last_close - vwap.iloc[-1]) / vwap.iloc[-1]) * 100
        atr_pct = (atr.iloc[-1] / last_close) * 100

        # Candle intent
        candle_range = last_high - last_low
        body = abs(last_close - last_open)
        body_ratio = body / candle_range if candle_range > 0 else 0

        buy_intent = body_ratio > 0.6 and last_close > (last_low + 0.7 * candle_range)
        sell_intent = body_ratio > 0.6 and last_close < (last_low + 0.3 * candle_range)

        if not (buy_intent or sell_intent):
            continue

        direction = "🟢📈" if buy_intent else "🔴📉"

        # Close activity (last 45 minutes)
        try:
            intra = t.history(period="1d", interval="15m")
            last_3 = intra.tail(3)
            day_high = intra["High"].max()
            day_low = intra["Low"].min()

            close_strength = (last_close - day_low) / (day_high - day_low)
            close_vol_ratio = last_3["Volume"].sum() / (intra["Volume"].sum() / len(intra) * 3)

            close_activity = (
                "Strong Buying" if close_strength > 0.7 and close_vol_ratio > 1.3 else
                "Strong Selling" if close_strength < 0.3 and close_vol_ratio > 1.3 else
                "Neutral"
            )
        except:
            close_activity = "Unavailable"

        # Delivery proxy
        delivery_score = (
            40 * (vol_spike > 50) +
            30 * (body_ratio > 0.6) +
            30 * (abs(vwap_dist) > 0.3)
        )

        # Support / resistance (60-day)
        sup = df["Low"].tail(60).min()
        res = df["High"].tail(60).max()
        sup_dist = ((last_close - sup) / last_close) * 100
        res_dist = ((res - last_close) / last_close) * 100

        # Score
        score = 0
        score += min(vol_spike, 100)
        score += 40 if abs(ema200_dist) < 1 else 0
        score += 25 if abs(ema50_dist) < 1 else 0
        score += 20 if abs(vwap_dist) < 0.5 else 0
        score += 15 if macd.iloc[-1] > 0 and macd.iloc[-2] < 0 else 0
        score += 10 if close_activity != "Neutral" else 0

        symbol = stock.replace(".NS", "")
        name = t.info.get("shortName", "")

        result_line = ""
        if symbol in results_map and pd.notna(results_map[symbol]):
            result_line = f"\n• Result Date: {results_map[symbol].strftime('%d %B %Y')}"

        message = (
            f"{direction} {symbol} | {name}\n"
            f"• Volume: {vol_spike:.0f}%\n"
            f"• EMA200: {ema200_dist:.2f}% | EMA50: {ema50_dist:.2f}%\n"
            f"• VWAP: {vwap_dist:.2f}% | ATR: {atr_pct:.2f}%\n"
            f"• MACD: {'Bullish' if macd.iloc[-1] >
