import yfinance as yf
import pandas as pd
import ta
import requests
import time
from datetime import datetime

# ================= TELEGRAM CONFIG =================
BOT_TOKEN = "8214091785:AAFzhQLjV8A6CjuIjoAIXCheE696dz3bYJo"
CHAT_ID = "1944866756"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    requests.post(url, data=payload)

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
    print("Error loading result calendar:", e)
    results_map = {}

high_conviction = []
medium_conviction = []

today = datetime.today().date()

# ================= SCAN =================
for i, stock in enumerate(stocks, 1):
    try:
        df = yf.Ticker(stock).history(period="3mo")

        if df.empty or len(df) < 50:
            continue

        close = pd.Series(df["Close"].values, index=df.index)
        volume = pd.Series(df["Volume"].values, index=df.index)

        ema50 = close.ewm(span=50).mean()
        ema200 = close.ewm(span=200).mean()
        rsi = ta.momentum.RSIIndicator(close, 14).rsi()
        vol_avg = volume.rolling(20).mean()

        last_close = close.iloc[-1]
        last_volume = volume.iloc[-1]
        rsi_val = rsi.iloc[-1]

        ema50_dist = ((last_close - ema50.iloc[-1]) / ema50.iloc[-1]) * 100
        ema200_dist = ((last_close - ema200.iloc[-1]) / ema200.iloc[-1]) * 100
        vol_spike = ((last_volume - vol_avg.iloc[-1]) / vol_avg.iloc[-1]) * 100

        score = 0
        reasons = []

        if abs(ema200_dist) < 1:
            score += 40
            reasons.append(f"EMA200 {ema200_dist:.2f}%")

        if abs(ema50_dist) < 1:
            score += 25
            reasons.append(f"EMA50 {ema50_dist:.2f}%")

        if vol_spike > 50:
            score += 30
            reasons.append(f"VOL +{vol_spike:.0f}%")

        if rsi_val > 70 or rsi_val < 30:
            score += 20
            reasons.append(f"RSI {rsi_val:.1f}")

        if score < 50:
            continue

        # -------- Bull / Bear --------
        bias = "🟢 BULLISH" if last_close > ema50.iloc[-1] and rsi_val > 50 else "🔴 BEARISH"

        # -------- Result Date & Warning --------
        symbol_clean = stock.replace(".NS", "")
        result_date = results_map.get(symbol_clean)

        result_text = "Not Declared"
        warning = ""

        if pd.notna(result_date):
            result_text = result_date.strftime("%d-%b-%Y")
            days_to_result = (result_date.date() - today).days

            if 0 <= days_to_result <= 3:
                warning = " ⚠ Upcoming result in 3 days"

        entry = (
            f"{bias} | {symbol_clean}\n"
            f"Score: {score}\n"
            f"{', '.join(reasons)}\n"
            f"RSI: {rsi_val:.1f}\n"
            f"Result: {result_text}{warning}"
        )

        if score >= 70:
            high_conviction.append((score, entry))
        else:
            medium_conviction.append((score, entry))

    except:
        pass

    # -------- RATE LIMIT PROTECTION --------
    if i % 25 == 0:
        time.sleep(2)

# ================= SEND TELEGRAM =================
high_conviction.sort(reverse=True)
medium_conviction.sort(reverse=True)

if high_conviction:
    msg = "🟢 HIGH CONVICTION SETUPS (FRIDAY EOD)\n\n"
    for _, e in high_conviction[:20]:
        msg += e + "\n\n"
    send_telegram(msg)

if medium_conviction:
    msg = "🟡 MEDIUM CONVICTION SETUPS (FRIDAY EOD)\n\n"
    for _, e in medium_conviction[:30]:
        msg += e + "\n\n"
    send_telegram(msg)
