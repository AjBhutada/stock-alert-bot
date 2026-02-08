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

TODAY = datetime.now().strftime("%d-%b-%Y")

# ================= TELEGRAM =================
def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets missing")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# ================= START CONFIRMATION =================
send_telegram("🚀 EOD Scan started (GitHub Actions running)")

# ================= GOOGLE SHEET LOG =================
def log_to_sheet(row):
    if not GSHEET_WEBHOOK:
        return
    payload = {"sheet": "EOD_ALERT_LOG", "row": row}
    requests.post(GSHEET_WEBHOOK, json=payload)

# ================= LOAD STOCKS =================
with open("stocks.txt") as f:
    STOCKS = [s.strip() + ".NS" for s in f if s.strip()]

send_telegram(f"📊 Loaded {len(STOCKS)} stocks for EOD scan")

# ================= LOAD RESULT CALENDAR =================
RESULTS_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRPYwOAHp2nWb917nR9F5QUX37yGhV7dN6q_-0falsOQx9u9BSoOKWzaHGQjPk9vQA664BiBhpC9q0H/pub?output=csv"

results_map = {}
try:
    rdf = pd.read_csv(RESULTS_URL)
    rdf["Security Name"] = rdf["Security Name"].str.upper().str.strip()
    rdf["Result Date"] = pd.to_datetime(
        rdf["Result Date"], format="%d-%b-%y", errors="coerce"
    )
    results_map = dict(zip(rdf["Security Name"], rdf["Result Date"]))
except:
    send_telegram("⚠️ Result calendar could not be loaded")

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

        body = abs(last_close - last_open)
        candle_range = last_high - last_low
        body_ratio = body / candle_range if candle_range else 0

        direction = "🟢📈" if last_close > ema200.iloc[-1] else "🔴📉"

        score = (
            min(vol_spike, 100)
            + (abs(ema200_dist) < 1) * 40
            + (abs(ema50_dist) < 1) * 25
            + (abs(vwap_dist) < 0.5) * 20
            + (macd.iloc[-1] > 0 and macd.iloc[-2] < 0) * 15
            + (body_ratio > 0.6) * 10
        )

        symbol = stock.replace(".NS", "")
        company = t.info.get("shortName", "")

        msg = (
            f"{direction} {symbol} | {company}\n"
            f"• Volume Spike: {vol_spike:.0f}%\n"
            f"• EMA200: {ema200_dist:.2f}% | EMA50: {ema50_dist:.2f}%\n"
            f"• VWAP: {vwap_dist:.2f}% | ATR: {atr_pct:.2f}%\n"
            f"• MACD: {'Bullish' if macd.iloc[-1] > 0 else 'Bearish'}"
        )

        if symbol in results_map and pd.notna(results_map[symbol]):
            msg += f"\n• Result Date: {results_map[symbol].strftime('%d %B %Y')}"

        top_candidates.append((score, msg))

        if abs(ema50_dist) < 1 or abs(ema200_dist) < 1:
            ema_watch.append(msg)

    except:
        pass

    if i % 25 == 0:
        time.sleep(2)

# ================= FINAL TELEGRAM =================
top_candidates.sort(reverse=True)

if top_candidates:
    msg = "🟢 TOP 20 EOD SETUPS (Ranked)\n\n"
    for _, m in top_candidates[:20]:
        msg += m + "\n\n"
else:
    msg = "ℹ️ No high-quality EOD setups today"

send_telegram(msg)

if ema_watch:
    msg = "⚠️ EMA PROXIMITY WATCHLIST\n\n"
    for m in ema_watch[:30]:
        msg += m + "\n\n"
else:
    msg = "ℹ️ No EMA-proximity stocks today"

send_telegram(msg)

send_telegram("✅ EOD Scan completed successfully")
