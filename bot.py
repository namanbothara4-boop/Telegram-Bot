import logging
import requests
import sqlite3
from datetime import datetime
from typing import List, Dict, Any

import yfinance as yf
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters
)

from apscheduler.schedulers.background import BackgroundScheduler

# ------------------------- Logging -------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------------- Config -------------------------
TELEGRAM_TOKEN = "8235562125:AAHu9eJlS4p9lt4RjAKFSlYd_fewJpB0ioc"
DB_PATH = "ipo_users.db"

# ------------------------- DB Setup -------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY,
        notify_time TEXT DEFAULT '09:00',
        sector_filter TEXT DEFAULT '',
        budget_filter TEXT DEFAULT '',
        risk_filter TEXT DEFAULT '',
        subscribed INTEGER DEFAULT 0
    )
    """)
    conn.commit()
    conn.close()

def set_user(chat_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users(chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    conn.close()

# ------------------------- IPO Fetching -------------------------
def fallback_ipos() -> List[Dict[str, Any]]:
    return [
        {
            "name": "Green Energy Ltd",
            "open_date": "2025-09-01",
            "close_date": "2025-09-04",
            "price_band": "₹120 – ₹135",
            "lot_size": "100",
            "expected_listing_gain": "15–20%",
            "risk": "Moderate",
            "details": "Renewable energy sector IPO",
            "gmp": "₹30"
        },
        {
            "name": "TechNova Solutions",
            "open_date": "2025-09-05",
            "close_date": "2025-09-09",
            "price_band": "₹450 – ₹500",
            "lot_size": "30",
            "expected_listing_gain": "25–30%",
            "risk": "High",
            "details": "AI & IT services",
            "gmp": "₹85"
        }
    ]

def fetch_real_ipos() -> List[Dict[str, Any]]:
    try:
        url = "https://api.ipoalerts.in/ipos?status=open"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            ipos = []
            for item in data:
                ipos.append({
                    "name": item.get("company", "Unknown IPO"),
                    "open_date": item.get("openDate", "TBA"),
                    "close_date": item.get("closeDate", "TBA"),
                    "price_band": item.get("priceBand", "TBA"),
                    "lot_size": str(item.get("lotSize", "TBA")),
                    "expected_listing_gain": "—",
                    "risk": "Moderate",
                    "details": item.get("exchange", ""),
                    "gmp": item.get("gmp", "—")
                })
            if ipos:
                return ipos
    except Exception as e:
        logger.warning("ipoalerts fetch failed: %s", e)
    return fallback_ipos()

# ------------------------- Stock Fetching -------------------------
def fetch_stock(symbol: str) -> Dict[str, Any]:
    try:
        ticker = yf.Ticker(symbol + ".NS")  # NSE stocks
        data = ticker.history(period="1d")
        info = ticker.info

        if not data.empty:
            last_price = round(data["Close"].iloc[-1], 2)
            high = round(data["High"].iloc[-1], 2)
            low = round(data["Low"].iloc[-1], 2)
        else:
            last_price = high = low = "—"

        return {
            "symbol": symbol.upper(),
            "price": last_price,
            "change": round(info.get("regularMarketChangePercent", 0), 2),
            "high": high,
            "low": low,
            "year_high": info.get("fiftyTwoWeekHigh", "—"),
            "year_low": info.get("fiftyTwoWeekLow", "—")
        }
    except Exception as e:
        logger.warning("Stock fetch failed: %s", e)
        return {"symbol": symbol, "price": "—", "change": "—"}

# ------------------------- News Fetching -------------------------
def fetch_market_news() -> List[str]:
    try:
        url = "https://newsapi.org/v2/top-headlines"
        params = {
            "country": "in",
            "category": "business",
            "apiKey": "pub_37376d6d1b42ac8c12f6f28dc7e8e1"  # demo key, replace if needed
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            articles = r.json().get("articles", [])
            return [f"📰 {a['title']}" for a in articles[:5]]
    except Exception as e:
        logger.warning("News fetch failed: %s", e)
    return ["📰 Market is stable today.", "📈 Investors eye upcoming IPOs."]

# ------------------------- Tools -------------------------
def sip_calculator(amount: int, years: int, rate: float) -> str:
    total_invested = amount * 12 * years
    future_value = amount * (((1 + rate/12)**(12*years) - 1) / (rate/12)) * (1 + rate/12)
    return (
        f"💰 SIP Calculator Result\n\n"
        f"Invested: ₹{total_invested:,}\n"
        f"Expected Corpus: ₹{int(future_value):,}\n"
        f"Assumed Return: {int(rate*100)}% p.a."
    )

# ------------------------- Message Helpers -------------------------
def format_ipo_card(ipo: Dict[str, Any]) -> str:
    return (
        f"📌 **{ipo['name']}**\n"
        f"🗓 Open: {ipo['open_date']} – Close: {ipo['close_date']}\n"
        f"💰 Price Band: {ipo['price_band']}\n"
        f"📦 Lot Size: {ipo['lot_size']}\n"
        f"📊 GMP: {ipo.get('gmp','—')}\n"
        f"📊 Expected Gain: {ipo['expected_listing_gain']}\n"
        f"🔥 Risk: {ipo['risk']}\n"
        f"ℹ️ {ipo['details']}\n"
    )

def main_menu() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("📢 Upcoming IPOs", callback_data="UPCOMING")],
        [InlineKeyboardButton("📊 GMP & Listing Gain", callback_data="PREDICTIONS")],
        [InlineKeyboardButton("📈 Track Stocks", callback_data="STOCKS")],
        [InlineKeyboardButton("📰 Market News", callback_data="NEWS")],
        [InlineKeyboardButton("🧮 SIP Calculator", callback_data="SIP")],
        [InlineKeyboardButton("🔔 Subscribe Alerts", callback_data="SUBSCRIBE")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="SETTINGS")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="HELP")]
    ]
    return InlineKeyboardMarkup(buttons)

# ------------------------- Handlers -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    set_user(chat_id)
    await update.message.reply_text(
        "👋 Welcome to **IPO Alert Bot**\n\n"
        "Your personal assistant for IPO news, GMP, stocks & calculators.\n\n"
        "Choose an option below 👇",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "ℹ️ **How to use IPO Alert Bot**\n\n"
        "• 📢 *Upcoming IPOs* – See latest IPO list.\n"
        "• 📊 *Predictions* – Get GMP & gain insights.\n"
        "• 📈 *Stocks* – Track stock prices.\n"
        "• 📰 *News* – Market headlines.\n"
        "• 🧮 *SIP* – Calculate SIP returns.\n"
        "• 🔔 *Subscribe* – Daily IPO alerts.\n"
        "• ⚙️ *Settings* – Filters (sector, budget, risk).\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "UPCOMING":
        ipos = fetch_real_ipos()
        text = "\n\n".join(format_ipo_card(ipo) for ipo in ipos[:5])
        await query.edit_message_text(
            "📢 **Upcoming IPOs**\n\n" + text,
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    elif query.data == "PREDICTIONS":
        ipos = fetch_real_ipos()
        text = "\n\n".join(f"{ipo['name']} → GMP {ipo.get('gmp','—')} | Gain {ipo['expected_listing_gain']}" for ipo in ipos[:5])
        await query.edit_message_text(
            "📊 **Listing Gain Predictions**\n\n" + text,
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    elif query.data == "STOCKS":
        await query.edit_message_text(
            "📈 Send me a stock symbol (e.g., RELIANCE, TCS).",
            reply_markup=main_menu()
        )

    elif query.data == "NEWS":
        news = "\n\n".join(fetch_market_news())
        await query.edit_message_text(
            "📰 **Market News**\n\n" + news,
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    elif query.data == "SIP":
        result = sip_calculator(10000, 10, 0.12)
        await query.edit_message_text(result, parse_mode="Markdown", reply_markup=main_menu())

    elif query.data == "SUBSCRIBE":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET subscribed=1 WHERE chat_id=?", (query.message.chat_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text(
            "✅ You are now subscribed for daily IPO alerts!",
            reply_markup=main_menu()
        )

    elif query.data == "SETTINGS":
        await query.edit_message_text(
            "⚙️ Settings: Soon you can filter IPOs by sector, budget, and risk.",
            reply_markup=main_menu()
        )

    elif query.data == "HELP":
        await query.edit_message_text("ℹ️ Use /help to see bot features explained.", reply_markup=main_menu())

async def echo_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    if text.isalpha():
        stock = fetch_stock(text)
        msg = (
            f"📈 **{stock['symbol']}**\n"
            f"💰 Price: {stock['price']} (Change: {stock['change']}%)\n"
            f"⬆️ High: {stock['high']} | ⬇️ Low: {stock['low']}\n"
            f"📊 52W High: {stock['year_high']} | 52W Low: {stock['year_low']}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ Please use the menu buttons.")

# ------------------------- Scheduler -------------------------
scheduler = BackgroundScheduler()

def send_daily_alerts(app):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM users WHERE subscribed=1")
    users = c.fetchall()
    conn.close()

    ipos = fetch_real_ipos()
    text = "📢 **Daily IPO Update**\n\n" + "\n\n".join(format_ipo_card(ipo) for ipo in ipos[:3])

    for (chat_id,) in users:
        try:
            app.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.error("Failed to send to %s: %s", chat_id, e)

# ------------------------- Main -------------------------
def main():
    init_db()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_text))

    scheduler.add_job(lambda: send_daily_alerts(app), "cron", hour=9, minute=0)
    scheduler.start()

    app.run_polling()

if __name__ == "__main__":
    main()
