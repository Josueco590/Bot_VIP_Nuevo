import os
import threading
import json
import asyncio
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.ext import BusinessConnectionHandler

BOT_TOKEN = os.getenv("BOT_TOKEN")

CLABE = "014470140190434923"
BENEFICIARIO = "Michelle Heras"
BANCO = "Santander"

app = Flask(__name__)
@app.route('/')
def home():
    return "Bot VIP Activo - Michelle Heras 24/7"
@app.route('/health')
def health():
    return "OK"

def cargar():
    try:
        with open("suscripciones.json", "r") as f:
            return json.load(f)
    except:
        return {}
def guardar(data):
    with open("suscripciones.json", "w") as f:
        json.dump(data, f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot VIP activo ✅ 24/7 - Michelle Heras")

async def agregar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = str(context.args[0]); dias = int(context.args[1]) if len(context.args) > 1 else 30
        data = cargar(); data[uid] = (datetime.now() + timedelta(days=dias)).isoformat()
        guardar(data)
        await update.message.reply_text(f"✅ Agregado {uid} por {dias} días\nVence: {data[uid][:10]}")
    except:
        await update.message.reply_text("Uso: /agregar ID dias")

async def ver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = cargar()
    if not data:
        await update.message.reply_text("No hay suscripciones")
        return
    texto = "📋 Suscripciones:\n\n" + "\n".join([f"{k} -> {v[:10]}" for k,v in data.items()])
    await update.message.reply_text(texto)

async def quitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = str(context.args[0]); data = cargar(); data.pop(uid, None); guardar(data)
        await update.message.reply_text(f"❌ Quitado {uid}")
    except:
        await update.message.reply_text("Uso: /quitar ID")

async def handle_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.business_message
    if not msg: return
    txt = (msg.text or "") + (msg.caption or "")
    if "ya pag" not in txt.lower(): return
    user_id = msg.from_user.id
    caption = (
        f"✅ <b>Comprobante recibido</b>\n\n"
        f"Tu ID: <code>{user_id}</code>\n"
        f"Número: <code>{txt[:60]}</code>\n\n"
        f"📋 <b>Datos de pago:</b>\n"
        f"CLABE: <code>{CLABE}</code>\n"
        f"Beneficiario: {BENEFICIARIO}\n"
        f"Banco: {BANCO}\n\n"
        f"🔹 <b>ID para copiar:</b>\n<code>{user_id}</code>"
    )
    if msg.photo:
        await context.bot.send_photo(chat_id=msg.chat.id, photo=msg.photo[-1].file_id, caption=caption, parse_mode="HTML")
    else:
        await context.bot.send_message(chat_id=msg.chat.id, text=caption, parse_mode="HTML")

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    print(f"Render usando puerto {port}")
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    threading.Thread(target=run_flask, daemon=True).start()
    print("Bot VIP con HISTORIAL, VENCIMIENTOS y ANTI-BUCLE iniciado - MODO 24/7")
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("agregar", agregar))
    application.add_handler(CommandHandler("ver", ver))
    application.add_handler(CommandHandler("quitar", quitar))
    application.add_handler(BusinessConnectionHandler(handle_business))
    application.run_polling()
