import os
import asyncio
import logging
from datetime import datetime, timezone

import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_IDS = set(filter(None, os.getenv("ALLOWED_CHAT_IDS", "").split(",")))
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "15"))
MAX_SYMBOLS = int(os.getenv("MAX_SYMBOLS", "40"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "5"))

BASE = "https://fapi.binance.com"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("signalbazan")

async def get_json(session, path, params=None):
    async with session.get(BASE + path, params=params, timeout=aiohttp.ClientTimeout(total=15)) as r:
        r.raise_for_status()
        return await r.json()

def rsi(values, period=14):
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(len(values)-period, len(values)):
        change = values[i] - values[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)

def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    out = values[0]
    for value in values[1:]:
        out = alpha * value + (1-alpha) * out
    return out

def analyze(candles):
    # Exclude the still-forming latest candle.
    candles = candles[:-1]
    if len(candles) < 60:
        return None
    closes = [float(c[4]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    volumes = [float(c[5]) for c in candles]
    price = closes[-1]
    r = rsi(closes)
    fast = ema(closes[-40:], 12)
    slow = ema(closes[-40:], 26)
    avg_vol = sum(volumes[-21:-1]) / 20
    vol_ratio = volumes[-1] / avg_vol if avg_vol else 0
    trend_up = closes[-1] > closes[-7] and fast is not None and slow is not None and fast > slow
    trend_down = closes[-1] < closes[-7] and fast is not None and slow is not None and fast < slow
    score_long = int(trend_up) + int(r is not None and 50 <= r <= 68) + int(vol_ratio >= 1.2) + int(price > max(highs[-21:-1]))
    score_short = int(trend_down) + int(r is not None and 32 <= r <= 50) + int(vol_ratio >= 1.2) + int(price < min(lows[-21:-1]))
    if score_long >= MIN_SCORE and score_long > score_short:
        side = "LONG 🟢"
        stop = min(lows[-7:])
        risk = price - stop
        if risk <= 0: return None
        t1, t2 = price + risk, price + 2*risk
        score = score_long
    elif score_short >= MIN_SCORE and score_short > score_long:
        side = "SHORT 🔴"
        stop = max(highs[-7:])
        risk = stop - price
        if risk <= 0: return None
        t1, t2 = price - risk, price - 2*risk
        score = score_short
    else:
        return None
    return {
        "side": side, "price": price, "stop": stop, "t1": t1, "t2": t2,
        "rsi": r, "vol_ratio": vol_ratio, "score": score
    }

async def scan_market():
    async with aiohttp.ClientSession() as session:
        info = await get_json(session, "/fapi/v1/exchangeInfo")
        allowed = {s["symbol"] for s in info["symbols"]
                   if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT"
                   and s.get("contractType") == "PERPETUAL"}
        tickers = await get_json(session, "/fapi/v1/ticker/24hr")
        tickers = [t for t in tickers if t.get("symbol") in allowed]
        tickers.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
        symbols = [t["symbol"] for t in tickers[:MAX_SYMBOLS]]
        results = []
        sem = asyncio.Semaphore(5)

        async def one(symbol):
            async with sem:
                try:
                    candles = await get_json(session, "/fapi/v1/klines",
                                             {"symbol": symbol, "interval": "15m", "limit": 100})
                    signal = analyze(candles)
                    if signal:
                        signal["symbol"] = symbol
                        results.append(signal)
                except Exception as e:
                    log.warning("scan failed for %s: %s", symbol, e)

        await asyncio.gather(*(one(s) for s in symbols))
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

def fmt_signal(s):
    return (
        f"{s['side']} | {s['symbol']} | 15m\n"
        f"قیمت بررسی: {s['price']:.8g}\n"
        f"حد ضرر پیشنهادی: {s['stop']:.8g}\n"
        f"هدف ۱ (حدود 1R): {s['t1']:.8g}\n"
        f"هدف ۲ (حدود 2R): {s['t2']:.8g}\n"
        f"RSI: {s['rsi']:.1f} | حجم نسبت به میانگین: {s['vol_ratio']:.2f}x\n"
        f"امتیاز شرایط: {s['score']}/4\n"
        "یادآوری: این سیگنال آزمایشی و مبتنی بر قواعد ساده است؛ تضمین سود نیست. "
        "قبل از معامله، قیمت و ریسک را مستقل بررسی کن."
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if CHAT_IDS and chat_id not in CHAT_IDS:
        await update.message.reply_text("این ربات هنوز برای این چت فعال نشده است.")
        return
    await update.message.reply_text(
        "سلام! 🤖 SignalBazan AI فعال است.\n"
        "/scan — اسکن بازار همین حالا\n"
        "/status — وضعیت تنظیمات\n"
        "/help — راهنما\n\n"
        "نسخه فعلی آزمایشی است و فقط داده عمومی بازار را می‌خواند؛ معامله‌ای انجام نمی‌دهد."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "دستورها:\n/start شروع\n/scan اسکن فوری\n/status وضعیت\n\n"
        "نسخه اولیه فقط ۱۵ دقیقه‌ای و تا تعداد محدودی از قراردادهای پرحجم USDT را بررسی می‌کند."
    )

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Chat ID این گفتگو: {chat_id}\\n"
        "این عدد را فقط در تنظیم ALLOWED_CHAT_IDS روی سرور وارد کن؛ توکن ربات را جایی منتشر نکن."
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"وضعیت: فعال\nبازه اسکن خودکار: هر {SCAN_INTERVAL_MINUTES} دقیقه\n"
        f"حداکثر نماد در هر اسکن: {MAX_SYMBOLS}\n"
        "منبع داده فعلی: Binance USDⓈ-M Futures public market data\n"
        "معامله خودکار: خاموش"
    )

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("در حال اسکن بازار؛ چند لحظه صبر کن…")
    try:
        results = await scan_market()
        if not results:
            await update.message.reply_text("در این اسکن سیگنالی با فیلترهای فعلی پیدا نشد؛ این بهتر از سیگنال ضعیف است.")
            return
        for s in results[:8]:
            await update.message.reply_text(fmt_signal(s))
    except Exception:
        log.exception("manual scan error")
        await update.message.reply_text("اسکن ناموفق بود؛ اتصال یا محدودیت منبع داده را بررسی می‌کنیم.")

async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_IDS:
        log.info("No ALLOWED_CHAT_IDS configured; scheduled messages are disabled.")
        return
    try:
        results = await scan_market()
        for chat_id in CHAT_IDS:
            if results:
                for s in results[:5]:
                    await context.bot.send_message(chat_id=chat_id, text=fmt_signal(s))
            else:
                await context.bot.send_message(chat_id=chat_id, text="اسکن دوره‌ای انجام شد؛ فعلاً سیگنال واجد شرایطی نیست.")
    except Exception:
        log.exception("scheduled scan error")

def main():
    if not TOKEN:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN environment variable. See README.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.add_handler(CommandHandler("status", status))\n    app.add_handler(CommandHandler("id", id_cmd))
    app.job_queue.run_repeating(scheduled_scan, interval=SCAN_INTERVAL_MINUTES*60, first=60)
    log.info("SignalBazan AI starting")
    app.run_polling()

if __name__ == "__main__":
    main()
