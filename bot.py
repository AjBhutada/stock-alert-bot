# ================================
# CRYPTO TECHNICAL ALERT BOT
# ================================

from binance.client import Client
import pandas as pd
import ta
import requests
import time
from datetime import datetime

# -------- TELEGRAM CONFIG --------
BOT_TOKEN = "8214091785:AAFzhQLjV8A6CjuIjoAIXCheE696dz3bYJo"
CHAT_ID = "1944866756"

# -------- CRYPTO CONFIG ----------
SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT"
]

INTERVAL = Client.KLINE_INTERVAL_5MINUTE
SCAN_DELAY = 300  # 5 minutes

# -------- ALERT CONTROL ----------
ALERT_COOLDOWN_MINUTES = 60
last_alert_time = {}

# -------- TELEGRAM FUNCTION ------
def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }
    requests.post(url, data=payload)

# -------- DATA FETCH -------------
def fetch_data(symbol):
    client = Client()
    klines = client.get_klines(
        symbol=symbol,
        interval=INTERVAL,
        limit=120
    )

    df = pd.DataFrame(klines, columns=[
        'time','open','high','low','close','volume',
        'close_time','qav','trades','taker_base',
        'taker_quote','ignore'
    ])

    df[['open','high','low','close','volume']] = df[
        ['open','high','low','close','volume']
    ].astype(float)

    return df

# -------- SIGNAL LOGIC ------------
def check_signal(df, symbol):
    df['EMA_50'] = df['close'].ewm(span=50).mean()
    df['RSI'] = ta.momentum.RSIIndicator(df['close'], 14).rsi()
    df['VOL_AVG'] = df['volume'].rolling(20).mean()

    last = df.iloc[-1]

    ema_touch = abs(last['close'] - last['EMA_50']) / last['EMA_50'] < 0.004
    volume_spike = last['volume'] > 2 * last['VOL_AVG']
    rsi_ok = (last['RSI'] > 30) and (last['RSI'] < 70)

    send_telegram(f"🧪 TEST ALERT for {symbol}")

    now = datetime.now()

    if symbol in last_alert_time:
        diff = (now - last_alert_time[symbol]).total_seconds() / 60
        if diff < ALERT_COOLDOWN_MINUTES:
            return

    last_alert_time[symbol] = now

    message = (
        f"🚨 CRYPTO ALERT\n\n"
        f"Pair: {symbol}\n"
        f"Timeframe: 5m\n"
        f"Price: {round(last['close'], 4)}\n"
        f"EMA50 touched\n"
        f"RSI: {round(last['RSI'], 2)}\n"
        f"Volume Spike\n"
        f"Time: {now.strftime('%H:%M:%S')}"
    )

    send_telegram(message)

# -------- MAIN LOOP --------------
send_telegram("✅ Crypto bot started successfully")

while True:
    try:
        for symbol in SYMBOLS:
            df = fetch_data(symbol)
            check_signal(df, symbol)

        print("Scan completed")
        time.sleep(SCAN_DELAY)

    except Exception as e:
        send_telegram(f"❌ Bot error:\n{e}")
        time.sleep(60)
