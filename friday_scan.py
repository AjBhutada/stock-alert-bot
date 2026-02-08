import yfinance as yf
import pandas as pd
import ta
import requests
import time
import os
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

with open("stocks.txt") as f:
    stocks = [s.strip() + ".NS" for s in f if s.strip()]

high_conv, mid_conv = [], []
ema_bias_list = []

for i, stock in enumerate(stocks, 1):
    try:
        t = yf.Ticker(stock)
        df = t.history(period="6mo")

        if df.empty or len(df) < 60:
            continue

        close = df["Close"]
        volume = df["Volume"]
        high = df["High"]
        low = df["Low"]

        ema50 = close.ewm(span=50).mean()
        ema200 = close.ewm(span=200).mean()
        rsi = ta.momentum.RSIIndicator(close, 14).rsi()
        vol_avg = volume.rolling(20).mean()

        last_close = close.iloc[-1]
        last_vol = volume.iloc[-1]
        vol_spike = ((last_vol - vol_avg.iloc[-1]) / vol_avg.iloc[-1]) * 100

        # Candle intent
        candle_range = high.iloc[-1] - low.iloc[-1]
        body = abs(close.iloc[-1] - df["Open"].iloc[-1])
        body_ratio = body / candle_range if candle_range > 0 else 0

        buy_intent = body_ratio > 0.6 and close.iloc[-1] > (low.iloc[-1] + 0.7 * candle_range)
        sell_intent = body_ratio > 0.6 and close.iloc[-1] < (low.iloc[-1] + 0.3 * candle_range)

        # Support / Resistance
        support = close.iloc[-20:].min()
        resistance = close.iloc[-20:].max()
        near_support = abs((last_close - support) / support) * 100 < 1
        near_resistance = abs((last_close - resistance) / resistance) * 100 < 1

        score = 0
        signals = []

        if vol_spike > 50:
            score += 40
            signals.append(f"Volume +{vol_spike:.0f}%")

        ema200_dist = abs((last_close - ema200.iloc[-1]) / ema200.iloc[-1]) * 100
        if ema200_dist < 1:
            score += 30
            signals.append(f"Near EMA200 ({ema200_dist:.2f}%)")

        if rsi.iloc[-1] > 70 or rsi.iloc[-1] < 30:
            score += 20
            signals.append(f"RSI {rsi.iloc[-1]:.1f}")

        direction = "🟢📈" if buy_intent else "🔴📉" if sell_intent else None

        symbol = stock.replace(".NS", "")
        name = t.info.get("shortName", "")

        header = f"{direction} {symbol}"
        if name:
            header += f" | {name}"

        entry = header + "\n" + "\n".join(signals)

        if score >= 70:
            high_conv.append((score, entry))
        elif score >= 55:
            mid_conv.append((score, entry))

        # EMA APPROACH LIST (TOMORROW BIAS)
        ema50_dist = abs((last_close - ema50.iloc[-1]) / ema50.iloc[-1]) * 100

        if (ema50_dist < 1 or ema200_dist < 1) and vol_spike > 40:
            bias = "🟢📈" if buy_intent else "🔴📉" if sell_intent else None
            if bias:
                txt = f"{bias} {symbol}"
                if name:
                    txt += f" | {name}"
                if ema200_dist < 1:
                    txt += f"\n• Near EMA200 ({ema200_dist:.2f}%)"
                else:
                    txt += f"\n• Near EMA50 ({ema50_dist:.2f}%)"
                txt += "\n• Delivery-like Buying" if buy_intent else "\n• Delivery-like Selling"
                if near_support:
                    txt += "\n• Near Support"
                if near_resistance:
                    txt += "\n• Near Resistance"
                ema_bias_list.append(txt)

    except:
        pass

    if i % 25 == 0:
        time.sleep(2)

# SEND MESSAGES
high_conv.sort(reverse=True)
mid_conv.sort(reverse=True)

if high_conv:
    msg = "🟢 HIGH CONVICTION SETUPS (EOD)\n\n"
    for _, e in high_conv[:20]:
        msg += e + "\n\n"
    send_telegram(msg)

if mid_conv:
    msg = "🟡 MEDIUM CONVICTION SETUPS (EOD)\n\n"
    for _, e in mid_conv[:25]:
        msg += e + "\n\n"
    send_telegram(msg)

if ema_bias_list:
    msg = "🚀 EMA APPROACH – TOMORROW BIAS (EOD)\n\n"
    for e in ema_bias_list[:15]:
        msg += e + "\n\n"
    send_telegram(msg)
