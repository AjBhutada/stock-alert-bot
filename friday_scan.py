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
GSHEET_WEBHOOK = os.getenv("GSHEET_WEBHOOK_URL")

TODAY = datetime.now().date().strftime("%Y-%m-%d")

# ================= TELEGRAM =================
def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# ================= GOOGLE SHEET LOG =================
def log_to_sheet(row):
    if not GSHEET_WEBHOOK:
        return
    payload = {
        "sheet": "EOD_ALERT_LOG",
        "row": row
    }
    requests.post(GSHEET_WEBHOOK, json=payload)

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

        vol_spike = ((v.iloc[-1] - vol_avg.iloc[-1]) / vol_avg.iloc[-1]) * 100
        ema50_dist = ((last_close - ema50.iloc[-1]) / ema50.iloc[-1]) * 100
        ema200_dist = ((last_close - ema200.iloc[-1]) / ema200.iloc[-1]) * 100
        vwap_dist = ((last_close - vwap.iloc[-1]) / vwap.iloc[-1]) * 100
        atr_pct = (atr.iloc[-1] / last_close) * 100

        candle_range = last_high - last_low
        body = abs(last_close - last_open)
        body_ratio = body / candle_range if candle_range > 0 else 0

        buy = body_ratio > 0.6 and last_close > (last_low + 0.7 * candle_range)
        sell = body_ratio > 0.6 and last_close < (last_low + 0.3 * candle_range)

        if not (buy or sell):
            continue

        direction = "🟢📈" if buy else "🔴📉"

        # ---- Close activity (last 45 minutes) ----
        try:
            intra = t.history(period="1d", interval="15m")
            last3 = intra.tail(3)
            day_high = intra["High"].max()
            day_low = intra["Low"].min()

            close_strength = (last_close - day_low) / (day_high - day_low)
            vol_ratio = last3["Volume"].sum() / (intra["Volume"].mean() * 3)

            if close_strength > 0.7 and vol_ratio > 1.3:
                close_activity = "Strong Buying"
            elif close_strength < 0.3 and vol_ratio > 1.3:
                close_activity = "Strong Selling"
            else:
                close_activity = "Neutral"
        except:
            close_activity = "Unavailable"

        delivery_proxy = (
            (vol_spike > 50) * 40 +
            (body_ratio > 0.6) * 30 +
            (abs(vwap_dist) > 0.3) * 30
        )

        support = df["Low"].tail(60).min()
        resistance = df["High"].tail(60).max()
        support_pct = ((last_close - support) / last_close) * 100
        resistance_pct = ((resistance - last_close) / last_close) * 100

        score = (
            min(vol_spike, 100) +
            (abs(ema200_dist) < 1) * 40 +
            (abs(ema50_dist) < 1) * 25 +
            (abs(vwap_dist) < 0.5) * 20 +
            (macd.iloc[-1] > 0 and macd.iloc[-2] < 0) * 15 +
            (close_activity != "Neutral") * 10
        )

        symbol = stock.replace(".NS", "")
        company = t.info.get("shortName", "")

        result_date = ""
        if symbol in results_map and pd.notna(results_map[symbol]):
            result_date = results_map[symbol].strftime("%d %B %Y")

        message = (
            f"{direction} {symbol} | {company}\n"
            f"• Volume: {vol_spike:.0f}%\n"
            f"• EMA200: {ema200_dist:.2f}% | EMA50: {ema50_dist:.2f}%\n"
            f"• VWAP: {vwap_dist:.2f}% | ATR: {atr_pct:.2f}%\n"
            f"• MACD: {'Bullish' if macd.iloc[-1] > 0 else 'Bearish'} ({macd.iloc[-1]:.2f})\n"
            f"• Close Activity: {close_activity}\n"
            f"• Delivery Proxy: {delivery_proxy}/100\n"
            f"• Support: {support_pct:.2f}% | Resistance: {resistance_pct:.2f}%"
        )

        if result_date:
            message += f"\n• Result Date: {result_date}"

        top_candidates.append((score, message))

        log_to_sheet([
            TODAY,
            symbol,
            company,
            direction,
            round(score, 1),
            round(vol_spike, 1),
            round(ema200_dist, 2),
            round(ema50_dist, 2),
            round(vwap_dist, 2),
            round(atr_pct, 2),
            round(macd.iloc[-1], 2),
            close_activity,
            delivery_proxy,
            round(support_pct, 2),
            round(resistance_pct, 2),
            result_date,
            "TOP20"
        ])

        if abs(ema50_dist) < 1 or abs(ema200_dist) < 1:
            ema_watch.append(message)

    except:
        pass

    if i % 25 == 0:
        time.sleep(2)

# ================= TELEGRAM =================
top_candidates.sort(reverse=True)

if top_candidates:
    msg = "🟢 TOP 20 EOD HIGH-CONVICTION SETUPS\n\n"
    for _, m in top_candidates[:20]:
        msg += m + "\n\n"
    send_telegram(msg)

if ema_watch:
    msg = "⚠ EMA APPROACH WATCHLIST (NEXT-DAY BIAS)\n\n"
    for m in ema_watch[:30]:
        msg += m + "\n\n"
    send_telegram(msg)
