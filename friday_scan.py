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
    requests.post(url, data={"chat_id": CHAT_ID, "text": message})

# ================= LOAD STOCK UNIVERSE =================
with open("stocks.txt", "r") as f:
    stocks = [line.strip() + ".NS" for line in f if line.strip()]

# ================= LOAD RESULT CALENDAR =================
RESULTS_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRPYwOAHp2nWb917nR9F5QUX37yGhV7dN6q_-0falsOQx9u9BSoOKWzaHGQjPk9vQA664BiBhpC9q0H/pub?gid=0&single=true&output=csv"

results_map = {}
try:
    rdf = pd.read_csv(RESULTS_CSV_URL)
    rdf["Security Name"] = rdf["Security Name"].str.upper().str.strip()
    rdf["Result Date"] = pd.to_datetime(rdf["Result Date"], format="%d-%b-%y", errors="coerce")
    results_map = dict(zip(rdf["Security Name"], rdf["Result Date"]))
except:
    pass

candidates = []

# ================= SCAN =================
for i, stock in enumerate(stocks, 1):
    try:
        ticker = yf.Ticker(stock)
        df = ticker.history(period="1y")

        if df.empty or len(df) < 200:
            continue

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]

        last_close = close.iloc[-1]

        # ===== Indicators =====
        ema50 = close.ewm(span=50).mean()
        ema200 = close.ewm(span=200).mean()
        vwap = (volume * (high + low + close) / 3).cumsum() / volume.cumsum()
        atr = ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range()
        macd_diff = ta.trend.MACD(close).macd_diff()
        vol_avg = volume.rolling(20).mean()

        ema50_dist = (last_close - ema50.iloc[-1]) / ema50.iloc[-1] * 100
        ema200_dist = (last_close - ema200.iloc[-1]) / ema200.iloc[-1] * 100
        vwap_dist = (last_close - vwap.iloc[-1]) / vwap.iloc[-1] * 100
        vol_spike = (volume.iloc[-1] - vol_avg.iloc[-1]) / vol_avg.iloc[-1] * 100
        atr_pct = atr.iloc[-1] / last_close * 100

        score = 0

        if vol_spike > 50:
            score += 40
        if abs(ema200_dist) < 2:
            score += 25
        if abs(ema50_dist) < 2:
            score += 15
        if abs(vwap_dist) < 2:
            score += 10
        if atr_pct > 2:
            score += 10

        macd_text = "Bullish" if macd_diff.iloc[-1] > 0 else "Bearish"
        score += 10

        # ===== Fibonacci (1-year swing) =====
        year_high = high.max()
        year_low = low.min()

        fib_50 = year_low + 0.5 * (year_high - year_low)
        fib_618 = year_low + 0.618 * (year_high - year_low)

        fib_text = ""
        if abs(last_close - fib_618) / fib_618 * 100 <= 1:
            score += 15
            fib_text = "Near 61.8%"
        elif abs(last_close - fib_50) / fib_50 * 100 <= 1:
            score += 10
            fib_text = "Near 50%"

        if score < 70:
            continue

        direction = "🟢📈" if last_close > ema200.iloc[-1] else "🔴📉"

        symbol = stock.replace(".NS", "")

        try:
            name = ticker.info.get("shortName", "")
        except:
            name = ""

        entry = f"{direction} {symbol}"
        if name:
            entry += f" | {name}"

        entry += f"\n• Volume Spike: {vol_spike:.0f}%"

        # ===== DELIVERY DATA (MATCH SAME TRADING DATE) =====
        try:
            last_trading_date = df.index[-1].date()
            date_str = last_trading_date.strftime("%Y%m%d")

            delivery_url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"

            ddf = pd.read_csv(delivery_url)
            ddf["SYMBOL"] = ddf["SYMBOL"].str.strip().str.upper()

            row = ddf[ddf["SYMBOL"] == symbol]
            if not row.empty:
                total = row["TOTTRDQTY"].values[0]
                delivery = row["DELIV_QTY"].values[0]

                if total > 0:
                    d_pct = delivery / total * 100

                    if d_pct > 60:
                        tag = "🔥 Very High"
                    elif d_pct > 40:
                        tag = "High"
                    elif d_pct > 25:
                        tag = "Moderate"
                    else:
                        tag = "Low"

                    entry += f"\n• Delivery: {d_pct:.0f}% ({tag})"

        except:
            pass  # Skip delivery if file not available

        entry += (
            f"\n• EMA200: {ema200_dist:.2f}% | EMA50: {ema50_dist:.2f}%"
            f"\n• VWAP: {vwap_dist:.2f}% | ATR: {atr_pct:.2f}%"
            f"\n• MACD: {macd_text}"
        )

        if fib_text:
            entry += f"\n• Fibonacci: {fib_text}"

        if symbol in results_map and pd.notna(results_map[symbol]):
            entry += f"\n• Result Date: {results_map[symbol].strftime('%d %B %Y')}"

        candidates.append((score, entry))

    except:
        pass

    if i % 25 == 0:
        time.sleep(2)

# ================= SEND TELEGRAM =================
candidates.sort(reverse=True)

if candidates:
    msg = "🟢 TOP 15 EOD SETUPS\n\n"
    for _, e in candidates[:15]:
        msg += e + "\n\n"
    send_telegram(msg)
else:
    send_telegram("ℹ️ EOD Scan completed. No strong setups today.")
