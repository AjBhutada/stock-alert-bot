import yfinance as yf
import pandas as pd
import numpy as np
import ta
import requests
import time
import os
import csv
from datetime import datetime, timedelta

# ================= TELEGRAM CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print(message)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"})
    except Exception as e:
        print(f"Telegram error: {e}")

# ================= LOAD STOCK UNIVERSE =================
with open("stocks.txt", "r") as f:
    stocks = [line.strip() + ".NS" for line in f if line.strip()]

# ================= LOAD RESULT CALENDAR =================
RESULTS_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRPYwOAHp2nWb917nR9F5QUX37yGhV7dN6q_-0falsOQx9u9BSoOKWzaHGQjPk9vQA664BiBhpC9q0H/pub?gid=0&single=true&output=csv"

results_map = {}
try:
    rdf = pd.read_csv(RESULTS_CSV_URL)
    rdf["Security Name"] = rdf["Security Name"].str.upper().str.strip()
    rdf["Result Date"]   = pd.to_datetime(rdf["Result Date"], format="%d-%b-%y", errors="coerce")
    results_map          = dict(zip(rdf["Security Name"], rdf["Result Date"]))
except:
    pass

# ================= DELIVERY DATA (loaded once) =================
delivery_map = {}

def load_delivery(trading_date):
    global delivery_map
    date_str = trading_date.strftime("%Y%m%d")
    url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
    try:
        ddf = pd.read_csv(url)
        ddf["SYMBOL"]    = ddf["SYMBOL"].str.strip().str.upper()
        ddf              = ddf[ddf["TOTTRDQTY"] > 0].copy()
        ddf["DELIV_PCT"] = ddf["DELIV_QTY"] / ddf["TOTTRDQTY"] * 100
        delivery_map     = dict(zip(ddf["SYMBOL"], ddf["DELIV_PCT"]))
        print(f"[delivery] Loaded {len(delivery_map)} records")
    except Exception as e:
        print(f"[delivery] Not available: {e}")

# ================= LOG FILE =================
LOG_FILE = "alert_log.csv"
LOG_COLS = [
    "alert_date", "symbol", "setup_type", "alert_price",
    "pred_direction", "pred_target_pct", "pred_target_price",
    "pred_stop_loss", "pred_timeframe_days",
    "ret_3d", "ret_5d", "ret_10d", "ret_20d",
    "target_hit", "sl_hit", "outcome", "status"
]

def init_log():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=LOG_COLS)
            writer.writeheader()

def append_log(rows):
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLS)
        for row in rows:
            writer.writerow(row)

def load_log():
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        return list(csv.DictReader(f))

def save_log(rows):
    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLS)
        writer.writeheader()
        writer.writerows(rows)

# ================= UPDATE PAST ALERT PERFORMANCE =================
def update_performance():
    rows = load_log()
    if not rows:
        return
    today    = datetime.now().date()
    changed  = 0

    for row in rows:
        if row.get("status") == "complete":
            continue
        try:
            alert_date   = datetime.strptime(row["alert_date"], "%Y-%m-%d").date()
            base         = float(row["alert_price"])
            target_price = float(row["pred_target_price"])
            sl_price     = float(row["pred_stop_loss"])
            tf_days      = int(row["pred_timeframe_days"])
            symbol       = row["symbol"]
            direction    = row["pred_direction"]
        except:
            continue

        start = (alert_date + timedelta(days=1)).strftime("%Y-%m-%d")
        end   = (today + timedelta(days=1)).strftime("%Y-%m-%d")

        try:
            hist = yf.download(symbol + ".NS", start=start, end=end,
                               progress=False, auto_adjust=True)
            if hist.empty:
                continue

            closes = hist["Close"].squeeze().dropna()
            highs  = hist["High"].squeeze().dropna()
            lows   = hist["Low"].squeeze().dropna()

            # ── returns at checkpoints ──
            for n, label in [(3,"ret_3d"),(5,"ret_5d"),(10,"ret_10d"),(20,"ret_20d")]:
                if not row.get(label) and len(closes) >= n:
                    p = float(closes.iloc[n-1])
                    row[label] = f"{(p - base) / base * 100:.2f}"

            # ── check if target or SL was hit within timeframe ──
            w_high = highs.iloc[:tf_days]
            w_low  = lows.iloc[:tf_days]

            if not w_high.empty:
                if direction == "Bullish":
                    t_hit = float(w_high.max()) >= target_price
                    s_hit = float(w_low.min())  <= sl_price
                else:
                    t_hit = float(w_low.min())  <= target_price
                    s_hit = float(w_high.max()) >= sl_price

                row["target_hit"] = str(t_hit)
                row["sl_hit"]     = str(s_hit)

                if t_hit and not s_hit:
                    row["outcome"] = "Target Hit"
                elif s_hit and not t_hit:
                    row["outcome"] = "SL Hit"
                elif t_hit and s_hit:
                    row["outcome"] = "Both Hit"
                elif len(closes) >= tf_days:
                    row["outcome"] = "Expired"
                else:
                    row["outcome"] = "Pending"

            # mark complete only after 20 trading days have passed
            all_done = all(row.get(f"ret_{x}d") for x in [3,5,10,20])
            row["status"] = "complete" if all_done else "partial"
            changed += 1

        except Exception as e:
            print(f"[perf update] {symbol}: {e}")

    save_log(rows)
    print(f"[tracker] Updated {changed} past alerts")


# =====================================================================
#  CORE ANALYSIS FUNCTIONS
# =====================================================================

def linear_regression_sr(series, window=60):
    """
    Fit linear regression over last `window` bars.
    Returns S1/S2/S3 and R1/R2/R3 at ±1/2/3 std deviations.
    """
    y       = series.values[-window:]
    x       = np.arange(len(y))
    coeffs  = np.polyfit(x, y, 1)
    fitted  = np.polyval(coeffs, x)
    std     = np.std(y - fitted)
    lr_now  = fitted[-1]
    slope   = coeffs[0]
    return {
        "lr_now": lr_now, "std": std,
        "slope":  slope,
        "trend":  "UP" if slope > 0 else "DOWN",
        "R1": lr_now + 1*std, "R2": lr_now + 2*std, "R3": lr_now + 3*std,
        "S1": lr_now - 1*std, "S2": lr_now - 2*std, "S3": lr_now - 3*std,
    }

def supertrend(high, low, close, period=10, mult=3.0):
    atr  = ta.volatility.AverageTrueRange(high, low, close, period).average_true_range()
    hl2  = (high + low) / 2
    ub   = hl2 + mult * atr
    lb   = hl2 - mult * atr
    st   = [0.0] * len(close)
    dire = [1]   * len(close)
    for i in range(1, len(close)):
        lb_i = lb.iloc[i] if lb.iloc[i] > lb.iloc[i-1] or close.iloc[i-1] < st[i-1] else lb.iloc[i-1]
        ub_i = ub.iloc[i] if ub.iloc[i] < ub.iloc[i-1] or close.iloc[i-1] > st[i-1] else ub.iloc[i-1]
        if st[i-1] == ub.iloc[i-1]:
            dire[i] = 1  if close.iloc[i] > ub_i else -1
        else:
            dire[i] = -1 if close.iloc[i] < lb_i else 1
        st[i] = lb_i if dire[i] == 1 else ub_i
    return int(pd.Series(dire).iloc[-1])

def obv_rising(close, volume, lookback=20):
    obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
    slope = np.polyfit(np.arange(lookback), obv.values[-lookback:], 1)[0]
    return slope > 0

# =====================================================================
#  EMA SETUP DETECTION  ← the new core logic
# =====================================================================

def detect_ema_setup(close, ema50_s, ema200_s, macd_diff, rsi_s):
    """
    Returns (setup_type, description) or (None, None) if no setup found.

    Three setups we look for:
      A — "Approaching EMA200 from below"  → stock trying to reclaim EMA200
      B — "Pullback to EMA50 in uptrend"   → dip to 50 EMA, trend intact
      C — "Golden Cross forming"            → EMA50 just crossed EMA200
    """
    last      = float(close.iloc[-1])
    e50       = float(ema50_s.iloc[-1])
    e200      = float(ema200_s.iloc[-1])
    rsi       = float(rsi_s.iloc[-1])
    macd_now  = float(macd_diff.iloc[-1])
    macd_prev = float(macd_diff.iloc[-2])

    dist_to_200 = (last - e200) / e200 * 100   # negative = below EMA200
    dist_to_50  = (last - e50)  / e50  * 100   # negative = below EMA50

    # ── SETUP C: Golden Cross (highest priority) ─────────────────────
    # EMA50 crossed above EMA200 in the last 5 bars
    crossed = False
    for j in range(1, 6):
        prev_50  = float(ema50_s.iloc[-j-1])
        prev_200 = float(ema200_s.iloc[-j-1])
        curr_50  = float(ema50_s.iloc[-j])
        curr_200 = float(ema200_s.iloc[-j])
        if prev_50 <= prev_200 and curr_50 > curr_200:
            crossed = True
            break

    if crossed:
        return (
            "🌟 Golden Cross",
            "EMA50 just crossed above EMA200 — strong long-term bullish signal"
        )

    # ── SETUP A: Approaching EMA200 from below ───────────────────────
    # Price is below EMA200 but within 3%, AND MACD turning up, RSI rising
    macd_turning_up = macd_now > macd_prev
    if -3.0 <= dist_to_200 <= 0 and macd_turning_up:
        return (
            "🔼 Approaching EMA200",
            f"Price is {abs(dist_to_200):.1f}% below EMA200 and pushing up — breakout watch"
        )

    # ── SETUP B: Pullback to EMA50 in uptrend ────────────────────────
    # Price is above EMA200 (uptrend confirmed) AND pulled back to EMA50
    above_200 = last > e200
    if above_200 and -2.0 <= dist_to_50 <= 1.5 and rsi > 40:
        return (
            "📉➡📈 EMA50 Pullback",
            f"Uptrend intact (above EMA200), price dipped to EMA50 — buy-the-dip zone"
        )

    return None, None


# =====================================================================
#  PREDICTION ENGINE
# =====================================================================

def make_prediction(last, lr, atr_pct, adx, direction, setup_type):
    """
    Returns dict with target, stop loss, timeframe, direction.
    """
    atr_abs = last * atr_pct / 100

    if direction == "Bullish":
        # target = next resistance above price
        target = next((lr[k] for k in ["R1","R2","R3"] if lr[k] > last), lr["R1"])
        sl     = lr["S1"] - 0.5 * atr_abs
        # Golden Cross gets an extra push — target R2
        if setup_type == "🌟 Golden Cross":
            target = next((lr[k] for k in ["R2","R3"] if lr[k] > last), lr["R2"])
    else:
        target = next((lr[k] for k in ["S1","S2","S3"] if lr[k] < last), lr["S1"])
        sl     = lr["R1"] + 0.5 * atr_abs

    target_pct = abs(target - last) / last * 100

    # timeframe: how many ATR-sized days to reach target, adjusted by trend strength
    base_days = target_pct / atr_pct if atr_pct > 0 else 10
    adx_mult  = 0.6 if adx >= 40 else 0.85 if adx >= 25 else 1.2 if adx >= 20 else 1.8
    tf_days   = max(2, min(25, round(base_days * adx_mult)))

    sl_pct = abs(sl - last) / last * 100

    return {
        "direction":    direction,
        "target_price": round(target, 2),
        "target_pct":   round(target_pct, 2),
        "stop_loss":    round(sl, 2),
        "sl_pct":       round(sl_pct, 2),
        "tf_days":      tf_days,
    }


def signal_votes(last, ema200, lr, rsi, macd_diff_val, st_dir, obv_up):
    """6-signal majority vote → direction + confidence."""
    votes = [
        1 if last > ema200        else -1,
        1 if lr["trend"] == "UP"  else -1,
        1 if st_dir == 1          else -1,
        1 if rsi > 50             else -1,
        1 if macd_diff_val > 0    else -1,
        1 if obv_up               else -1,
    ]
    bull = sum(1 for v in votes if v == 1)
    bear = 6 - bull
    direction  = "Bullish" if bull >= bear else "Bearish"
    conf_votes = max(bull, bear)
    conf_label = (
        "Very High 🔥" if conf_votes == 6 else
        "High ✅"       if conf_votes == 5 else
        "Medium ⚠️"    if conf_votes == 4 else
        "Low ❓"
    )
    return direction, conf_label, bull


# =====================================================================
#  TELEGRAM MESSAGE FORMATTER
# =====================================================================

def format_message(rank, symbol, name, setup_type, setup_desc,
                   last, lr, indicators, pred, delivery_pct,
                   result_str, conf_label, bull_votes):

    e50, e200, rsi, adx, atr_pct, vol_spike, macd_val, st_dir = indicators

    def f(v): return f"₹{v:.2f}"

    # direction icon
    d_icon = "🟢📈" if pred["direction"] == "Bullish" else "🔴📉"

    # delivery tag
    dlabel = ""
    if delivery_pct is not None:
        if   delivery_pct >= 65: dlabel = "🔥 Exceptional"
        elif delivery_pct >= 50: dlabel = "💪 Very High"
        elif delivery_pct >= 35: dlabel = "✅ High"
        elif delivery_pct >= 20: dlabel = "⚖️ Moderate"
        else:                    dlabel = "⚠️ Low"

    # RSI label
    rsi_label = (
        "Overbought ⚠️" if rsi >= 70 else
        "Bullish 🟢"    if rsi >= 55 else
        "Neutral ⚖️"   if rsi >= 45 else
        "Bearish 🔴"    if rsi >= 30 else
        "Oversold 💡"
    )

    # ADX label
    adx_label = (
        "Very strong 💪" if adx >= 40 else
        "Trending 📈"    if adx >= 25 else
        "Weak 〰️"       if adx >= 20 else
        "Ranging 😴"
    )

    msg = (
        f"{'─'*32}\n"
        f"#{rank}  {d_icon} <b>{symbol}</b>"
        + (f"  |  {name}" if name else "")
        + f"\n\n🔍 <b>Setup: {setup_type}</b>"
        f"\n{setup_desc}"
        f"\n"
        f"\n📐 <b>Support &amp; Resistance  (LR Channel)</b>"
        f"\n  🔴 R3 {f(lr['R3'])}  ·  R2 {f(lr['R2'])}  ·  R1 {f(lr['R1'])}"
        f"\n  ▶ CMP {f(last)}"
        f"\n  🟢 S1 {f(lr['S1'])}  ·  S2 {f(lr['S2'])}  ·  S3 {f(lr['S3'])}"
        f"\n"
        f"\n📊 <b>Indicators</b>"
        f"\n  RSI {rsi:.1f} — {rsi_label}"
        f"\n  ADX {adx:.1f} — {adx_label}"
        f"\n  MACD: {'▲ Positive' if macd_val > 0 else '▼ Negative'}"
        f"\n  Supertrend: {'Bullish 🟩' if st_dir == 1 else 'Bearish 🟥'}"
        f"\n  EMA50 {f(e50)}  ·  EMA200 {f(e200)}"
        f"\n  ATR {atr_pct:.2f}%  ·  Vol Spike {vol_spike:+.0f}%"
    )

    if delivery_pct is not None:
        msg += f"\n  Delivery {delivery_pct:.0f}% — {dlabel}"

    msg += (
        f"\n"
        f"\n🎯 <b>Prediction  ({conf_label}  [{bull_votes}/6 signals])</b>"
        f"\n  Direction:  <b>{pred['direction']}</b>"
        f"\n  Target:     {f(pred['target_price'])}  (+{pred['target_pct']:.1f}%)"
        f"\n  Stop Loss:  {f(pred['stop_loss'])}  (-{pred['sl_pct']:.1f}%)"
        f"\n  Timeframe:  ~{pred['tf_days']} trading days"
    )

    if result_str:
        msg += f"\n\n📅 Result Date: <b>{result_str}</b>"

    return msg


# =====================================================================
#  MAIN SCAN
# =====================================================================

init_log()

candidates           = []
delivery_loaded      = False

for i, stock in enumerate(stocks, 1):
    try:
        ticker = yf.Ticker(stock)
        df     = ticker.history(period="1y")

        if df.empty or len(df) < 200:
            continue

        close  = df["Close"]
        high   = df["High"]
        low    = df["Low"]
        volume = df["Volume"]

        # load delivery once
        if not delivery_loaded:
            load_delivery(df.index[-1].date())
            delivery_loaded = True

        symbol    = stock.replace(".NS", "")
        last      = float(close.iloc[-1])
        deliv_pct = delivery_map.get(symbol)

        # ── compute indicators ────────────────────────────────────────
        ema50_s  = close.ewm(span=50).mean()
        ema200_s = close.ewm(span=200).mean()
        e50      = float(ema50_s.iloc[-1])
        e200     = float(ema200_s.iloc[-1])

        rsi_s     = ta.momentum.RSIIndicator(close, 14).rsi()
        rsi       = float(rsi_s.iloc[-1])
        macd_d    = ta.trend.MACD(close).macd_diff()
        macd_val  = float(macd_d.iloc[-1])
        adx       = float(ta.trend.ADXIndicator(high, low, close, 14).adx().iloc[-1])

        atr_s   = ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range()
        atr_pct = float(atr_s.iloc[-1]) / last * 100

        vol_avg   = float(volume.rolling(20).mean().iloc[-1])
        vol_spike = (float(volume.iloc[-1]) - vol_avg) / vol_avg * 100 if vol_avg > 0 else 0

        st_dir = supertrend(high, low, close)
        obv_up = obv_rising(close, volume)

        window = min(60, len(close))
        lr     = linear_regression_sr(close, window)

        # ── VWAP ──────────────────────────────────────────────────────
        vwap      = (volume * (high + low + close) / 3).cumsum() / volume.cumsum()
        vwap_dist = (last - float(vwap.iloc[-1])) / float(vwap.iloc[-1]) * 100

        # ── Fibonacci ─────────────────────────────────────────────────
        year_high = float(high.max())
        year_low  = float(low.min())
        fib_618   = year_low + 0.618 * (year_high - year_low)
        fib_50    = year_low + 0.500 * (year_high - year_low)
        fib_text  = ""
        if abs(last - fib_618) / fib_618 * 100 <= 1.5:
            fib_text = "Near Fib 61.8% 🔑"
        elif abs(last - fib_50) / fib_50 * 100 <= 1.5:
            fib_text = "Near Fib 50% 🔑"

        # ── EMA SETUP DETECTION ───────────────────────────────────────
        setup_type, setup_desc = detect_ema_setup(
            close, ema50_s, ema200_s, macd_d, rsi_s
        )

        # ── also keep original EMA proximity check as fallback ────────
        ema200_dist = (last - e200) / e200 * 100
        ema50_dist  = (last - e50)  / e50  * 100

        if setup_type is None:
            # fall back to original proximity filter
            if abs(ema200_dist) >= 3 and abs(ema50_dist) >= 3:
                continue   # not near any EMA — skip
            if abs(ema200_dist) < 3:
                setup_type = "📍 Near EMA200"
                setup_desc = f"Price within {abs(ema200_dist):.1f}% of EMA200"
            else:
                setup_type = "📍 Near EMA50"
                setup_desc = f"Price within {abs(ema50_dist):.1f}% of EMA50"

        # ── direction + confidence ────────────────────────────────────
        direction, conf_label, bull_votes = signal_votes(
            last, e200, lr, rsi, macd_val, st_dir, obv_up
        )

        # ── prediction ────────────────────────────────────────────────
        pred = make_prediction(last, lr, atr_pct, adx, direction, setup_type)

        # ── company name ──────────────────────────────────────────────
        try:    name = ticker.info.get("shortName", "")
        except: name = ""

        # ── result date ───────────────────────────────────────────────
        result_str = ""
        if symbol in results_map and pd.notna(results_map.get(symbol)):
            result_str = results_map[symbol].strftime("%d %B %Y")

        indicators = (e50, e200, rsi, adx, atr_pct, vol_spike, macd_val, st_dir)

        # ── build score for ranking only (not shown in message) ───────
        rank_score = 0
        if setup_type == "🌟 Golden Cross":           rank_score += 50
        elif setup_type == "🔼 Approaching EMA200":   rank_score += 40
        elif setup_type == "📉➡📈 EMA50 Pullback":   rank_score += 35
        else:                                          rank_score += 20
        rank_score += bull_votes * 5
        if rsi > 50:                                  rank_score += 5
        if macd_val > 0:                              rank_score += 5
        if adx > 25:                                  rank_score += 5
        if deliv_pct and deliv_pct >= 40:             rank_score += 5
        if fib_text:                                  rank_score += 5

        candidates.append((
            rank_score, symbol, name, setup_type, setup_desc,
            last, lr, indicators, pred, deliv_pct, result_str,
            conf_label, bull_votes, fib_text
        ))

    except Exception as e:
        print(f"[{stock}] {e}")

    if i % 25 == 0:
        time.sleep(2)

# =====================================================================
#  SEND + LOG
# =====================================================================

candidates.sort(key=lambda x: x[0], reverse=True)
top15 = candidates[:15]

if top15:
    today_str = datetime.now().strftime("%d %b %Y")
    send_telegram(
        f"🔔 <b>EOD SETUPS — {today_str}</b>\n"
        f"📋 {len(top15)} setups from {len(stocks)} scanned\n"
        f"{'─'*30}"
    )
    time.sleep(0.5)

    log_rows = []
    for rank, item in enumerate(top15, 1):
        (_, symbol, name, setup_type, setup_desc,
         last, lr, indicators, pred, deliv_pct,
         result_str, conf_label, bull_votes, fib_text) = item

        msg = format_message(
            rank, symbol, name, setup_type, setup_desc,
            last, lr, indicators, pred, deliv_pct,
            result_str, conf_label, bull_votes
        )

        # append fibonacci note if present
        if fib_text:
            msg += f"\n🔑 {fib_text}"

        send_telegram(msg)
        time.sleep(0.6)

        # ── log this alert ──────────────────────────────────────────
        today = datetime.now().strftime("%Y-%m-%d")
        log_rows.append({
            "alert_date":          today,
            "symbol":              symbol,
            "setup_type":          setup_type,
            "alert_price":         str(round(last, 2)),
            "pred_direction":      pred["direction"],
            "pred_target_pct":     str(pred["target_pct"]),
            "pred_target_price":   str(pred["target_price"]),
            "pred_stop_loss":      str(pred["stop_loss"]),
            "pred_timeframe_days": str(pred["tf_days"]),
            "ret_3d": "", "ret_5d": "", "ret_10d": "", "ret_20d": "",
            "target_hit": "", "sl_hit": "", "outcome": "Pending",
            "status": "pending",
        })

    append_log(log_rows)

    send_telegram(
        "⚠️ <b>Disclaimer:</b> For educational purposes only.\n"
        "Always do your own analysis. Not financial advice."
    )

else:
    send_telegram("ℹ️ EOD Scan complete — no strong setups found today.")

# ── update performance of past alerts ──────────────────────────────
print("[scanner] Checking past alert performance...")
update_performance()
print(f"[scanner] Done. {len(top15)} setups sent.")
