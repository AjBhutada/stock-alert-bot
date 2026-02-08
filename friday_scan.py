import yfinance as yf
import pandas as pd
import ta
import requests
import time
import os
from datetime import datetime, timedelta

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GSHEET_WEBHOOK = os.getenv("GSHEET_WEBHOOK_URL")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

TODAY = datetime.now().date()

# ================= TELEGRAM =================
def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# ================= GOOGLE SHEET LOG =================
def log_to_sheet(sheet, row):
    if not GSHEET_WEBHOOK:
        return
    requests.post(GSHEET_WEBHOOK, json={"sheet": sheet, "row": row})

def get_today_logged_keys():
    try:
        url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/gviz/tq?tqx=out:csv&sheet=EOD_ALERT_LOG"
        df = pd.read_csv(url)
        df["Date"] = pd.to_datetime(df["Date"]).dt.date

        today_df = df[df["Date"] == TODAY]

        return set(
            zip(
                today_df["Date"].astype(str),
                today_df["Symbol"],
                today_df["Message_Type"]
            )
        )
    except:
        return set()

# ================= LOAD STOCKS =================
with open("stocks.txt") as f:
    STOCKS = [s.strip() + ".NS" for s in f if s.strip()]

logged_today = get_today_logged_keys()
top_setups = []
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
        macd = ta.trend.MACD(c).macd_diff()
        atr = ta.volatility.AverageTrueRange(h, l, c, 14).average_true_range()
        vol_avg = v.rolling(20).mean()

        last_close = c.iloc[-1]
        last_open = o.iloc[-1]
        last_high = h.iloc[-1]
        last_low = l.iloc[-1]

        atr_pct = (atr.iloc[-1] / last_close) * 100
        if atr_pct < 1.2:
            continue

        vol_spike = ((v.iloc[-1] - vol_avg.iloc[-1]) / vol_avg.iloc[-1]) * 100

        candle_range = last_high - last_low
        body = abs(last_close - last_open)
        body_ratio = body / candle_range if candle_range > 0 else 0

        buy = body_ratio > 0.6 and last_close > (last_low + 0.7 * candle_range)
        sell = body_ratio > 0.6 and last_close < (last_low + 0.3 * candle_range)

        if not (buy or sell):
            continue

        direction = "🟢📈" if buy else "🔴📉"

        ema50_dist = abs((last_close - ema50.iloc[-1]) / ema50.iloc[-1]) * 100
        ema200_dist = abs((last_close - ema200.iloc[-1]) / ema200.iloc[-1]) * 100

        score = 0
        reasons = []

        if vol_spike > 50:
            score += 40
            reasons.append("Volume Spike")

        if ema200_dist < 1:
            score += 30
            reasons.append("EMA200 Zone")

        if ema50_dist < 1:
            score += 20
            reasons.append("EMA50 Zone")

        if macd.iloc[-1] > 0 and macd.iloc[-2] < 0:
            score += 15
            reasons.append("MACD Cross")

        if score < 65:
            continue

        symbol = stock.replace(".NS", "")
        name = t.info.get("shortName", "")

        entry = f"{direction} {symbol} | {name}\n" + " | ".join(reasons)
        top_setups.append((score, entry))

        log_key = (str(TODAY), symbol, "TOP20")

        if log_key not in logged_today:
            log_to_sheet("EOD_ALERT_LOG", [
                TODAY.strftime("%Y-%m-%d"),
                symbol,
                name,
                direction,
                score,
                ", ".join(reasons),
                round(last_close, 2),
                round(atr_pct, 2),
                "EMA200" if ema200_dist < 1 else "EMA50" if ema50_dist < 1 else "",
                "",
                "TOP20"
            ])
            logged_today.add(log_key)

    except:
        pass

    if i % 25 == 0:
        time.sleep(2)

# ================= TELEGRAM =================
top_setups.sort(reverse=True)

if top_setups:
    msg = "🟢 TOP 20 EOD SETUPS\n\n"
    for _, e in top_setups[:20]:
        msg += e + "\n\n"
    send_telegram(msg)
