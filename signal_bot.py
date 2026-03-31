"""
Confluence Signal Bot
BTC / ETH / SOL — 1h + 4h
Sends Telegram alerts on high-quality setups
"""

import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import requests
import time
import logging
from datetime import datetime

# ═══════════════════════════════════════════════════════════
#  CONFIG — שנה כאן
# ═══════════════════════════════════════════════════════════

TELEGRAM_TOKEN   = "8570833219:AAFU-QGrkx4ceHhe8QANWMmRNxCQPUNi_9k"    # ← הכנס טוקן הבוט
TELEGRAM_CHAT_ID = "569829841"      # ← הכנס Chat ID שלך

SYMBOLS          = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
MIN_SCORE        = 5          # מינימום ציון מתוך 8 לשליחת סיגנל
CHECK_EVERY_SEC  = 300        # בדיקה כל 5 דקות
ATR_SL_MULT      = 1.5        # מכפיל ATR ל-SL
ATR_TP1_MULT     = 2.0        # TP1
ATR_TP2_MULT     = 3.5        # TP2
ATR_TP3_MULT     = 5.5        # TP3
MIN_RR           = 2.0        # R:R מינימלי לכניסה

# ═══════════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
#  EXCHANGE
# ═══════════════════════════════════════════════════════════

exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {"defaultType": "future"}
})

# ═══════════════════════════════════════════════════════════
#  TELEGRAM
# ═══════════════════════════════════════════════════════════

def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            log.warning(f"Telegram error: {r.text}")
    except Exception as e:
        log.error(f"Telegram send failed: {e}")

# ═══════════════════════════════════════════════════════════
#  DATA FETCHING
# ═══════════════════════════════════════════════════════════

def fetch_ohlcv(symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    df.set_index("ts", inplace=True)
    return df

# ═══════════════════════════════════════════════════════════
#  INDICATORS
# ═══════════════════════════════════════════════════════════

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df["ema8"]   = ta.ema(df["close"], length=8)
    df["ema21"]  = ta.ema(df["close"], length=21)
    df["ema55"]  = ta.ema(df["close"], length=55)
    df["ema200"] = ta.ema(df["close"], length=200)

    df["rsi"] = ta.rsi(df["close"], length=14)

    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    df["macd"]        = macd["MACD_12_26_9"]
    df["macd_signal"] = macd["MACDs_12_26_9"]
    df["macd_hist"]   = macd["MACDh_12_26_9"]

    bb = ta.bbands(df["close"], length=20, std=2)
    df["bb_upper"] = bb["BBU_20_2.0"]
    df["bb_lower"] = bb["BBL_20_2.0"]
    df["bb_mid"]   = bb["BBM_20_2.0"]

    stoch = ta.stoch(df["high"], df["low"], df["close"], k=14, d=3)
    df["stoch_k"] = stoch["STOCHk_14_3_3"]
    df["stoch_d"] = stoch["STOCHd_14_3_3"]

    df["atr"]    = ta.atr(df["high"], df["low"], df["close"], length=14)
    df["vol_ma"] = df["volume"].rolling(20).mean()

    return df

# ═══════════════════════════════════════════════════════════
#  CONFLUENCE SCORING
# ═══════════════════════════════════════════════════════════

def score_confluence(df1h: pd.DataFrame, df4h: pd.DataFrame):
    c1  = df1h.iloc[-1]
    c1p = df1h.iloc[-2]
    c4  = df4h.iloc[-1]

    checks_long  = {}
    checks_short = {}

    # 1. HTF Trend (4h)
    htf_bull = (c4["ema8"] > c4["ema21"] > c4["ema55"]) and (c4["close"] > c4["ema55"])
    htf_bear = (c4["ema8"] < c4["ema21"] < c4["ema55"]) and (c4["close"] < c4["ema55"])
    checks_long["📈 HTF Trend (4h)"]  = htf_bull
    checks_short["📉 HTF Trend (4h)"] = htf_bear

    # 2. EMA Stack (1h)
    ema_bull = (c1["ema8"] > c1["ema21"]) and (c1["close"] > c1["ema21"])
    ema_bear = (c1["ema8"] < c1["ema21"]) and (c1["close"] < c1["ema21"])
    checks_long["📊 EMA Stack (1h)"]  = ema_bull
    checks_short["📊 EMA Stack (1h)"] = ema_bear

    # 3. RSI
    rsi_bull = (40 < c1["rsi"] < 65) and (c1["rsi"] > c1p["rsi"])
    rsi_bear = (35 < c1["rsi"] < 60) and (c1["rsi"] < c1p["rsi"])
    checks_long["💹 RSI"]  = rsi_bull
    checks_short["💹 RSI"] = rsi_bear

    # 4. MACD Cross
    macd_cross_bull = (c1["macd"] > c1["macd_signal"]) and (c1p["macd"] <= c1p["macd_signal"])
    macd_cross_bear = (c1["macd"] < c1["macd_signal"]) and (c1p["macd"] >= c1p["macd_signal"])
    checks_long["⚡ MACD Cross"]  = macd_cross_bull
    checks_short["⚡ MACD Cross"] = macd_cross_bear

    # 5. Volume
    vol_ok = c1["volume"] > c1["vol_ma"] * 1.2
    checks_long["📦 Volume"]  = vol_ok
    checks_short["📦 Volume"] = vol_ok

    # 6. Stochastic
    stoch_bull = (c1["stoch_k"] > c1["stoch_d"]) and (c1["stoch_k"] < 80) and (c1p["stoch_k"] <= c1p["stoch_d"])
    stoch_bear = (c1["stoch_k"] < c1["stoch_d"]) and (c1["stoch_k"] > 20) and (c1p["stoch_k"] >= c1p["stoch_d"])
    checks_long["🔀 Stochastic"]  = stoch_bull
    checks_short["🔀 Stochastic"] = stoch_bear

    # 7. Bollinger Position
    bb_bull = (c1["close"] > c1["bb_mid"]) and (c1["close"] < c1["bb_upper"])
    bb_bear = (c1["close"] < c1["bb_mid"]) and (c1["close"] > c1["bb_lower"])
    checks_long["🎯 Bollinger"]  = bb_bull
    checks_short["🎯 Bollinger"] = bb_bear

    # 8. Momentum (3 נרות)
    mom_bull = c1["close"] > df1h.iloc[-4]["close"]
    mom_bear = c1["close"] < df1h.iloc[-4]["close"]
    checks_long["🚀 Momentum"]  = mom_bull
    checks_short["🚀 Momentum"] = mom_bear

    return (
        sum(checks_long.values()),
        sum(checks_short.values()),
        checks_long,
        checks_short
    )

# ═══════════════════════════════════════════════════════════
#  SL / TP
# ═══════════════════════════════════════════════════════════

def calc_levels(price: float, atr: float, direction: str):
    if direction == "long":
        sl  = price - atr * ATR_SL_MULT
        tp1 = price + atr * ATR_TP1_MULT
        tp2 = price + atr * ATR_TP2_MULT
        tp3 = price + atr * ATR_TP3_MULT
    else:
        sl  = price + atr * ATR_SL_MULT
        tp1 = price - atr * ATR_TP1_MULT
        tp2 = price - atr * ATR_TP2_MULT
        tp3 = price - atr * ATR_TP3_MULT

    risk   = abs(price - sl)
    reward = abs(tp1 - price)
    rr     = round(reward / risk, 2) if risk > 0 else 0
    return sl, tp1, tp2, tp3, rr

# ═══════════════════════════════════════════════════════════
#  MESSAGE
# ═══════════════════════════════════════════════════════════

def build_message(symbol, direction, price, sl, tp1, tp2, tp3, rr, score, checks):
    emoji   = "🟢" if direction == "long" else "🔴"
    dir_str = "LONG ▲" if direction == "long" else "SHORT ▼"
    sym     = symbol.replace("/", "")
    sign    = "+" if direction == "long" else "-"
    sl_sign = "-" if direction == "long" else "+"

    def pct(a, b): return abs(a - b) / b * 100

    checks_str = "\n".join(
        f"{'✅' if v else '❌'} {k}" for k, v in checks.items()
    )

    now = datetime.utcnow().strftime("%d/%m %H:%M UTC")

    return (
        f"{emoji} <b>{dir_str}  —  {sym}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📍 <b>כניסה:</b>  ${price:,.2f}\n"
        f"🛑 <b>SL:</b>      ${sl:,.2f}  ({sl_sign}{pct(price,sl):.1f}%)\n"
        f"🎯 <b>TP1:</b>    ${tp1:,.2f}  ({sign}{pct(tp1,price):.1f}%)\n"
        f"🎯 <b>TP2:</b>    ${tp2:,.2f}  ({sign}{pct(tp2,price):.1f}%)\n"
        f"🎯 <b>TP3:</b>    ${tp3:,.2f}  ({sign}{pct(tp3,price):.1f}%)\n"
        f"📊 <b>R:R:</b>    1 : {rr}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Confluence: {score}/8</b>\n"
        f"{checks_str}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {now} | TF: 1h+4h\n"
        f"⚠️ לא המלצת השקעה — נהל סיכונים!"
    )

# ═══════════════════════════════════════════════════════════
#  ANTI-SPAM
# ═══════════════════════════════════════════════════════════

alerted: dict = {}

def should_alert(symbol: str, direction: str) -> bool:
    if alerted.get(symbol) == direction:
        return False
    alerted[symbol] = direction
    return True

# ═══════════════════════════════════════════════════════════
#  ANALYZE
# ═══════════════════════════════════════════════════════════

def analyze(symbol: str):
    try:
        df1h = add_indicators(fetch_ohlcv(symbol, "1h"))
        df4h = add_indicators(fetch_ohlcv(symbol, "4h"))
    except Exception as e:
        log.error(f"Fetch error {symbol}: {e}")
        return

    long_s, short_s, cl, cs = score_confluence(df1h, df4h)
    price = df1h.iloc[-1]["close"]
    atr   = df1h.iloc[-1]["atr"]

    log.info(f"{symbol.replace('/',''):<10} Long={long_s}/8  Short={short_s}/8  ${price:,.2f}")

    for direction, score, checks in [("long", long_s, cl), ("short", short_s, cs)]:
        if score >= MIN_SCORE:
            sl, tp1, tp2, tp3, rr = calc_levels(price, atr, direction)
            if rr >= MIN_RR and should_alert(symbol, direction):
                msg = build_message(symbol, direction, price, sl, tp1, tp2, tp3, rr, score, checks)
                send_telegram(msg)
                log.info(f"  ✅ {direction.upper()} alert sent — score={score} rr={rr}")
            break
    else:
        alerted[symbol] = "none"

# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════

def main():
    log.info("🚀 Bot started")
    send_telegram(
        "🤖 <b>Confluence Signal Bot פעיל!</b>\n"
        "📡 עוקב: BTCUSDT | ETHUSDT | SOLUSDT\n"
        "⏱ בדיקה כל 5 דקות | TF: 1h + 4h\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "סיגנל יישלח רק כשלפחות 5/8 גורמים מיושרים ✅"
    )

    while True:
        log.info("─── Scanning ───")
        for sym in SYMBOLS:
            analyze(sym)
            time.sleep(2)
        time.sleep(CHECK_EVERY_SEC)

if __name__ == "__main__":
    main()
