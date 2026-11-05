from flask import Flask
import asyncio
import html
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from html import escape as html_escape
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, BusinessConnectionHandler, CommandHandler

BOT_TOKEN = os.getenv("BOT_TOKEN")

flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "Bot VIP Activo 24/7 - Michelle Heras Santander"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    print(f"Render usando puerto {port}")
    flask_app.run(host="0.0.0.0", port=port)

def keep_alive():
    import threading
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()


ADMIN_ID = 8737553272
GROUP_VIP_ID = -1002176820843
DATA_FILE = "bot_data.json"
HISTORY_FILE = "historial.json"
SUBSCRIBERS_FILE = "suscriptores.json"
MEXICO_CITY = ZoneInfo("America/Mexico_City")
EXPIRATION_CHECK_INTERVAL_SECONDS = 60 * 60
expiration_notification_failures = set()
expiration_monitor_task = None

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_subscribers():
    if not os.path.exists(SUBSCRIBERS_FILE):
        return {}
    with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
        subscribers = json.load(f)
    if not isinstance(subscribers, dict):
        raise ValueError("suscriptores.json debe contener un objeto JSON")
    return subscribers

def save_subscribers(subscribers):
    temporary_file = f"{SUBSCRIBERS_FILE}.tmp"
    with open(temporary_file, "w", encoding="utf-8") as f:
        json.dump(subscribers, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(temporary_file, SUBSCRIBERS_FILE)

def load_conversation_history():
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        history = json.load(f)
    if not isinstance(history, dict):
        raise ValueError("historial.json debe contener un objeto JSON")
    return history

def save_conversation_history(history):
    temporary_file = f"{HISTORY_FILE}.tmp"
    with open(temporary_file, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(temporary_file, HISTORY_FILE)

def append_conversation_message(user_id, full_name, username, message_text, sender, foto_id=None):
    history = load_conversation_history()
    entries = history.setdefault(str(user_id), [])
    if not isinstance(entries, list):
        raise ValueError(f"El historial del usuario {user_id} no es una lista")
    entry = {
        "id": int(user_id),
        "nombre": full_name,
        "username": username,
        "mensaje": message_text,
        "fecha_hora": datetime.now().astimezone().isoformat(timespec="seconds"),
        "emisor": sender,
    }
    if foto_id:
        entry["foto_id"] = foto_id
    entries.append(entry)
    save_conversation_history(history)

def migrate_legacy_history():
    if os.path.exists(HISTORY_FILE):
        return
    legacy_data = load_data()
    migrated_history = {}
    for user_id, user_data in legacy_data.items():
        if not isinstance(user_data, dict):
            continue
        legacy_username = user_data.get("username") or ""
        if legacy_username.startswith("@"):
            username = legacy_username
            full_name = "Cliente"
        else:
            username = "Sin username"
            full_name = legacy_username or "Cliente"
        legacy_entries = user_data.get("history", [])
        if not isinstance(legacy_entries, list):
            continue
        migrated_entries = []
        for old_entry in legacy_entries:
            if not isinstance(old_entry, dict):
                continue
            foto_id = old_entry.get("foto_id")
            entry = {
                "id": int(user_id) if str(user_id).isdigit() else str(user_id),
                "nombre": full_name,
                "username": username,
                "mensaje": old_entry.get("texto") or ("[foto]" if foto_id else "[mensaje no textual]"),
                "fecha_hora": old_entry.get("fecha") or "Fecha anterior no registrada",
                "emisor": "cliente",
            }
            if foto_id:
                entry["foto_id"] = foto_id
            migrated_entries.append(entry)
        if migrated_entries:
            migrated_history[str(user_id)] = migrated_entries
    save_conversation_history(migrated_history)

def describe_message(message):
    if message.text:
        return message.text
    if message.caption:
        return message.caption
    media_labels = (
        ("photo", "[foto]"),
        ("video", "[video]"),
        ("video_note", "[video corto]"),
        ("voice", "[nota de voz]"),
        ("audio", "[audio]"),
        ("document", "[documento]"),
        ("sticker", "[sticker]"),
        ("animation", "[animación]"),
        ("location", "[ubicación]"),
        ("venue", "[lugar]"),
        ("contact", "[contacto]"),
        ("poll", "[encuesta]"),
        ("dice", "[dado]"),
    )
    for attribute, label in media_labels:
        if getattr(message, attribute, None):
            return label
    return "[mensaje no textual]"

def mensaje_comprobante(nombre, username, user_id, texto_mensaje, veces=3):
    username_text = f"@{username}" if username else "Sin username"
    texto = (
        f"🔔 <b>NUEVO COMPROBANTE VIP ({veces} veces)</b>\n"
        f"De: {html_escape(str(nombre))}\n"
        f"Username: {html_escape(username_text)}\n"
        f"ID: <code>{user_id}</code>\n"
        f"Texto: {html_escape(str(texto_mensaje))}\n\n"
        f"👉 <a href=\"tg://user?id={user_id}\">ENTRAR A LA CONVERSACIÓN CON {html_escape(str(nombre))}</a>"
    )
    return texto

def build_admin_contact_link(user_id, full_name):
    return (
        f"👉 <a href=\"tg://user?id={user_id}\">ENTRAR A LA CONVERSACIÓN CON "
        f"{html_escape(full_name)}</a>"
    )

async def send_admin_notice(bot, message, user_id, full_name):
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=f"{message}\n\n{build_admin_contact_link(user_id, full_name)}",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

async def reply_admin(bot, message, user_id=None, full_name=None):
    if user_id is not None:
        full_name = full_name or f"Usuario {user_id}"
        message = f"{message}\n\n{build_admin_contact_link(user_id, full_name)}"
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=message,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

async def get_user_display_name(bot, user_id):
    user_id = str(user_id)
    history = load_conversation_history()
    entries = history.get(user_id, [])
    if isinstance(entries, list):
        for entry in reversed(entries):
            if isinstance(entry, dict) and entry.get("nombre"):
                return str(entry["nombre"])
    try:
        chat = await bot.get_chat(int(user_id))
        full_name = getattr(chat, "full_name", None)
        if full_name:
            return full_name
    except Exception as error:
        print(f"No pude consultar el nombre de {user_id}: {error}")
    return f"Usuario {user_id}"

async def remove_user_from_vip_group(bot, user_id):
    await bot.ban_chat_member(GROUP_VIP_ID, int(user_id))
    await bot.unban_chat_member(GROUP_VIP_ID, int(user_id))

async def check_expired_subscribers(application):
    subscribers = load_subscribers()
    now = datetime.now(MEXICO_CITY)
    for subscriber_key, subscriber in list(subscribers.items()):
        if not isinstance(subscriber, dict):
            print(f"Registro de suscriptor inválido para ID {subscriber_key}")
            continue
        try:
            user_id = int(subscriber.get("user_id", subscriber_key))
            expiration = datetime.fromisoformat(subscriber["fecha_vencimiento"])
            if expiration.tzinfo is None:
                expiration = expiration.replace(tzinfo=MEXICO_CITY)
        except (KeyError, TypeError, ValueError) as error:
            print(f"Fecha de vencimiento inválida para ID {subscriber_key}: {error}")
            continue
        if expiration > now:
            continue
        full_name = str(subscriber.get("nombre") or f"Usuario {user_id}")
        try:
            await remove_user_from_vip_group(application.bot, user_id)
        except Exception as error:
            print(f"No pude sacar del grupo VIP al usuario {user_id}: {error}")
            if user_id not in expiration_notification_failures:
                try:
                    await send_admin_notice(
                        application.bot,
                        f"⚠️ No pude sacar a {html_escape(full_name)} ID {user_id} "
                        f"del grupo VIP: {html_escape(str(error)[:300])}",
                        user_id,
                        full_name,
                    )
                    expiration_notification_failures.add(user_id)
                except Exception as notice_error:
                    print(f"No pude avisar al admin sobre el usuario {user_id}: {notice_error}")
            continue
        subscribers.pop(subscriber_key, None)
        save_subscribers(subscribers)
        expiration_notification_failures.discard(user_id)
        try:
            await send_admin_notice(
                application.bot,
                f"🔔 VENCIDO - Saqué a {html_escape(full_name)} ID {user_id} "
                "del grupo VIP por vencimiento",
                user_id,
                full_name,
            )
        except Exception as error:
            print(f"No pude enviar el aviso de vencimiento para {user_id}: {error}")

async def subscription_expiration_monitor(application):
    while True:
        try:
            await check_expired_subscribers(application)
        except Exception as error:
            print(f"Error al revisar vencimientos VIP: {error}")
        await asyncio.sleep(EXPIRATION_CHECK_INTERVAL_SECONDS)

async def start_subscription_expiration_monitor(application):
    global expiration_monitor_task
    expiration_monitor_task = asyncio.create_task(
        subscription_expiration_monitor(application)
    )

async def stop_subscription_expiration_monitor(application):
    global expiration_monitor_task
    if expiration_monitor_task is None:
        return
    expiration_monitor_task.cancel()
    try:
        await expiration_monitor_task
    except asyncio.CancelledError:
        pass
    expiration_monitor_task = None

def split_long_text(text, max_length=1800):
    return [text[index:index + max_length] for index in range(0, len(text), max_length)]

def normalizar(texto):
    if not texto:
        return ""
    texto = texto.lower()
    texto = ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )
    texto = re.sub(r'[^\w\s]', ' ', texto)
    return texto

def normalize(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def contains_any(norm_text, keywords):
    return any(k in norm_text for k in keywords)

MSG_VIP = """Holaa amor 💖

Grupo VIP $200mxn/$15 dólares (mensual)

(NO HAGO ENCUENTROS NI VIDEOLLAMADAS)

¿Que incluye mi Grupo VIP? ⭐️

- Acceso 1 Mes
- Videos Sexo Oral
- Videos Sexo Anal
- Videos Cogiendo
- Videos Colaboraciones
- Fotos en lencería
- Fotos sin censura
- Lives en vivo
🔥 Más de 100 videos y más de 400 fotos disponibles para ver y se actualiza constantemente 🔥
Y mucho más...

Venta de tangas usadas $900 pesos México / $130 dólares USA (ya con envío incluido)

👉 Escribe la palabra "Pagar" para ver los métodos de pago"""
vip_info_texto = MSG_VIP

MSG_TANGAS = """Holaa amor 💖

Venta de tangas usadas $900 pesos México (ya con envío incluido) / $130 dólares USA (ya con envío incluido)

Envíos a México y USA, puedes recibir directamente en tu domicilio o recoger en paquetería en tu localidad.

Incluye video usando la tanguita modelándola para ti.

Una vez realizado tu pago, Mich Ivy se pondrá en contacto personalmente contigo para hacer tu guía e informarte sobre el proceso de envío.

👉 Escribe la palabra "Pagar" para ver los métodos de pago"""

metodos_pago_texto = """💳 MÉTODOS DE PAGO MÉXICO:

• Transferencia:
Santander
CLABE: 014470140190434923
Beneficiario: Michelle Heras
Concepto: Tu nombre de usuario de Telegram
Precio: $200 pesos México

• Pago en efectivo OXXO 🇲🇽
Número de tarjeta: 4915669550533218
Precio: $200 pesos México


💵 MÉTODOS DE PAGO USA:

• Remitly:
Escribe la palabra Remitly y Mich Ivy te dará los datos de pago personalmente.
Precio Grupo VIP: $15 dólares USA
Precio Tangas: $130 dólares USA

• PayPal + Comisión:
https://www.paypal.me/soyandiwin
Precio Grupo VIP: $17 dólares USA (precio final con comisión incluida)
Precio Tangas: $140 dólares USA (precio final con comisión y envío incluidos)

👉 Cuando realices el pago, escribe "Ya pagué" y envía la foto de tu comprobante aquí mismo."""

MSG_YAPAGUE_VIP_1 = "¡Recibido! 💖 En breve serás agregado al Grupo VIP. Tiempo de espera aproximado 1 hora."
MSG_YAPAGUE_VIP_2 = "Soy un asistente virtual, ya recibí tu comprobante 🙏 Por favor ten paciencia, Mich Ivy te agregará al Grupo VIP personalmente. Tiempo de espera aproximado 1 hora."
MSG_YAPAGUE_TANGA_1 = "¡Recibido! 💖 En breve Mich Ivy te pedirá la información para enviar tu tanga a tu domicilio o para que la recojas en una paquetería en tu localidad. Tiempo de espera aproximado 1 hora."
MSG_YAPAGUE_TANGA_2 = "Soy un asistente virtual, ya recibí tu comprobante de tu tanga 🙏 Por favor ten paciencia, Mich Ivy se pondrá en contacto personalmente contigo para hacer tu guía de envío. Tiempo de espera aproximado 1 hora."
MSG_REMITLY_1 = "Hola amor 💖 En breve Mich Ivy te proporcionará la información de pago por Remitly personalmente 🙏 Tiempo de espera aproximado 1 hora"
MSG_REMITLY_2 = "Soy un asistente virtual, ya recibí tu solicitud de pago por Remitly 🙏 Por favor ten paciencia, Mich Ivy te enviará el link de pago actualizado personalmente en breve. Tiempo de espera aproximado 1 hora"
MSG_CONFIANZA = """Entiendo tu desconfianza amor 💖 Soy Mich Ivy, llevo más de 2 años con mi Grupo VIP y tengo cientos de clientes.

El proceso es 100% seguro:
- Me envías tu comprobante con la palabra "Ya pagué"
- Verifico tu pago personalmente
- Te agrego al Grupo VIP en máximo 1 hora

👉 Escribe la palabra "Pagar" para ver los métodos de pago seguros"""
MSG_RENOVACION = """Hola amor 💖

La renovación del Grupo VIP es el mismo precio: $200 pesos México / $15 dólares USA mensual
PayPal + Comisión: $17 dólares USA (ya con comisión incluida, precio final)

👉 Escribe la palabra "Pagar" para ver los métodos de pago y renovar hoy mismo"""
MSG_QUEJA_1 = "Soy un asistente virtual, ya recibí tu comprobante amor 🙏 Mich Ivy está verificando los pagos, a veces tarda un poco más por la fila de pagos, pero sí te agregará personalmente al Grupo VIP, por favor ten paciencia 💖 Tiempo aproximado 1 hora"
MSG_QUEJA_2 = "Amor, entiendo tu espera 🙏 Ya tienes tu lugar apartado, Mich Ivy te agregará en breve personalmente, a veces hay muchos pagos por verificar, pero sí te agrega seguro 💖"
MSG_ENCUENTROS = """Hola amor 💖 No realizo encuentros ni videollamadas 🙏 Solo venta de contenido de mi Grupo VIP y tangas usadas

👉 Si te interesa mi contenido escribe "Información Grupo VIP" para ver qué incluye o "Pagar" para ver métodos de pago"""
MSG_AUDIO = "Hola amor 💖 No puedo escuchar audios de voz, soy un asistente virtual 🙏 Por favor escríbeme tu mensaje aquí en texto y con gusto te ayudo"
MSG_STICKER = """Hola amor 💖 Para ayudarte escríbeme:
👉 "Información Grupo VIP" para ver qué incluye
👉 "Pagar" para ver métodos de pago"""
MSG_PRUEBA = """Amor 💖 No envío pruebas gratuitas de mi contenido 🙏 Solo los adelantos que están en mi grupo gratis que es de donde vienes 🥰

El Grupo VIP es el contenido completo sin censura + todos mis videos

👉 Escribe "Información Grupo VIP" para saber más o "Pagar" para realizar tu pago"""
MSG_NO_CONTEMPLADA = """Hola amor 💖 Soy el asistente virtual de Mich Ivy. Para ayudarte más rápido escribe:
👉 "Información VIP" para ver qué incluye
👉 "Pagar" para ver métodos de pago

Si quieres algo personalizado o tienes una duda diferente, en breve Mich Ivy te contesta personalmente."""

KW_VIP = ["hola","que tal","q tal","que onda","buenas","holi","hey","hi","hello","info vip","informacion vip","informacion grupo vip","grupo vip","precio vip","cuanto cuesta el vip","informacion grupo vip 🔥"]
KW_TANGAS = ["tanga","tangas usadas","info tangas","cuanto cuestan las tangas"]
KW_PAGAR = ["pagar","metodos de pago","precio","cuanto cuesta","donde te deposito","como te pago"]
KW_YAPAGUE = ["ya pague","yapague","ya deposite","yadeposite","ya te deposite","ya te pague","ya te transferi","te deposite","te transferi","te pague","te mande comprobante","comprobante","ya quedo"]
KW_REMITLY = ["remitly","remitli","remtily","remilti","remity"]
KW_CONFIANZA = ["es seguro","si me agregas","no es estafa","si es real","tienes referencias","es confiable"]
KW_RENOVACION = ["se me vencio","se me acabo","se me termino","quiero renovar","renovar vip","renovacion","renuevo","quiero entrar de nuevo al vip","quiero volver a entrar","quiero regresar al vip","como renuevo","ya no estoy en el vip"]
KW_QUEJA = ["no me has agregado","no me agregas","no me agregaste","no me has metido","no me metes","ya paso 1 hora","ya paso mas de 1 hora","ya paso una hora","ya pasaron 2 horas","ya paso mucho tiempo","ya paso mucho rato","cuanto tardas","cuanto tardas en agregar","cuanto falta","cuanto falta para que me agregues","cuando me agregas","cuando me agregas al vip","cuando me metes al vip","a que hora me agregas","a que hora me metes","ya pague hace rato","ya pague hace mucho","llevo esperando","estoy esperando","sigo esperando","aun no me agregas","ya casi","ya casi me agregas","falta mucho","ya mero","ya mero me agregas","me estafaste","no me agregas al vip","cuando me metes","ya pague y no me agregas","cuanto tiempo mas"]
KW_ENCUENTROS = ["encuentro","videollamada","video llamada","haces privado","cuanto por encuentro"]
KW_PRUEBA = ["prueba gratis","muestra gratis","me mandas prueba"]
variantes_vip_info = [
    "vip", "vips", "viip", "vipp", "vippp", "v i p", "el vip", "lo vip", "del vip", "pack vip", "grupo vip", "acceso vip", "quiero vip", "quiero ser vip", "ser vip", "entrar vip", "info vip", "vip info",
    "contenido", "contenidos", "contenido vip", "contenido exclusivo", "contenido completo", "contenido privado", "q contenido", "que contenido", "que trae", "que tiene", "que incluye", "que incluye el vip", "que trae el vip",
    "info", "informacion", "informasion", "informes", "me das info", "dame info", "mas info", "me das informacion", "dame informacion"
]

async def handle_business_connection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Business connection: {update.business_connection}")

async def handle_business_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.business_message
    if not msg:
        return
    if msg.from_user.is_bot:
        return
    if str(msg.from_user.id) == str(ADMIN_ID):
        return
    try:
        if msg.from_user.id == context.bot.id:
            return
    except:
        pass
    user_id = str(msg.from_user.id)
    full_name = msg.from_user.full_name or msg.from_user.first_name or "Cliente"
    username = f"@{msg.from_user.username}" if msg.from_user.username else "Sin username"
    chat_id = msg.chat.id
    b_conn_id = msg.business_connection_id
    data = load_data()
    if user_id not in data:
        data[user_id] = {"counters": {}, "last_topic": "vip", "history": [], "username": username}
    data[user_id]["username"] = username
    counters = data[user_id]["counters"]
    text = msg.text or msg.caption or ""
    norm = normalize(text)
    texto_norm = normalizar(text)
    has_photo = bool(msg.photo)
    append_conversation_message(
        user_id,
        full_name,
        username,
        describe_message(msg),
        "cliente",
        foto_id=msg.photo[-1].file_id if has_photo else None,
    )
    history_entry = {"fecha": datetime.now().strftime("%d/%m %H:%M"), "texto": text, "foto_id": msg.photo[-1].file_id if has_photo else None}
    if "history" not in data[user_id]:
        data[user_id]["history"] = []
    data[user_id]["history"].append(history_entry)
    if len(data[user_id]["history"]) > 50:
        data[user_id]["history"] = data[user_id]["history"][-50:]
    save_data(data)
    async def reply_bot(t):
        try:
            await context.bot.send_message(chat_id=chat_id, text=t, business_connection_id=b_conn_id)
        except:
            await context.bot.send_message(chat_id=chat_id, text=t, business_connection_id=b_conn_id)
        append_conversation_message(user_id, full_name, username, t, "bot")
        # Si es mensaje de métodos de pago, mandar CLABE en azul copiable aparte
        if "MÉTODOS DE PAGO" in t:
            try:
                azul = (
                    "🔹 <b>CLABE para copiar con 1 toque:</b>\n"
                    "<code>014470140190434923</code>\n\n"
                    "🔹 <b>Tarjeta OXXO para copiar:</b>\n"
                    "<code>4915669550533218</code>"
                )
                await context.bot.send_message(chat_id=chat_id, text=azul, business_connection_id=b_conn_id, parse_mode="HTML")
            except Exception as e:
                print(f"Error enviando azul: {e}")

    async def notify_admin(admin_text, forward_photo=False):
        try:
            contact_link = build_admin_contact_link(user_id, full_name)
            admin_message = (
                f"{html_escape(admin_text)}\n"
                f"De: {html_escape(full_name)}\n"
                f"Username: {html_escape(username)}\n"
                f"ID: <code>{user_id}</code>\n"
                f"Texto: {html_escape(text[:300])}\n\n"
                f"{contact_link}"
            )
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_message,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            if forward_photo and has_photo and msg.photo:
                await context.bot.send_photo(
                    chat_id=ADMIN_ID,
                    photo=msg.photo[-1].file_id,
                    caption=f"Comprobante de {html_escape(username)}\n\n{contact_link}",
                    parse_mode="HTML",
                )
        except Exception as e:
            print(f"Notify error: {e}")

    telegram_message = msg

    async def notify_vip_receipt(veces, forward_photo=False):
        try:
            user = telegram_message.from_user
            nombre = user.full_name or user.first_name or "Cliente"
            username_raw = user.username
            user_id_int = user.id
            texto_mensaje = telegram_message.caption or telegram_message.text or "Ya pagué"
            username_text = f"@{username_raw}" if username_raw else "Sin username"
            # 1. Mandar FOTO primero si hay
            if forward_photo and telegram_message.photo:
                caption_foto = (
                    f"Comprobante de {html_escape(username_text)}\n\n"
                    f"👉 <a href=\"tg://user?id={user_id_int}\">ENTRAR A LA CONVERSACIÓN "
                    f"CON {html_escape(str(nombre))}</a>"
                )
                await context.bot.send_photo(
                    chat_id=ADMIN_ID,
                    photo=telegram_message.photo[-1].file_id,
                    caption=caption_foto,
                    parse_mode="HTML",
                )
            # 2. Mandar TEXTO con ID azul copiable
            texto_vip = mensaje_comprobante(nombre, username_raw, user_id_int, texto_mensaje, veces)
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=texto_vip,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            print(f"Notify error VIP: {e}")

    if msg.voice or msg.video_note:
        await reply_bot(MSG_AUDIO)
        await notify_admin("🔔 NOTA DE VOZ RECIBIDA")
        return
    if msg.sticker or (text and len(text) <= 4 and not any(c.isalnum() for c in text)):
        await reply_bot(MSG_STICKER)
        return
    if contains_any(norm, KW_ENCUENTROS):
        await reply_bot(MSG_ENCUENTROS)
        return
    if contains_any(norm, KW_PRUEBA):
        await reply_bot(MSG_PRUEBA)
        return
    if contains_any(norm, KW_QUEJA):
        key = "queja"
        count = counters.get(key, 0) + 1
        counters[key] = count
        data[user_id]["counters"] = counters
        save_data(data)
        if count == 1:
            await reply_bot(MSG_QUEJA_1)
            await notify_admin(f"🔔 SE QUEJA - NO AGREGADO (1 vez)", forward_photo=has_photo)
        else:
            await reply_bot(MSG_QUEJA_2)
            await notify_admin(f"🔔 SE QUEJA - NO AGREGADO ({count} veces)", forward_photo=has_photo)
        return
    if contains_any(norm, KW_REMITLY):
        key = "remitly"
        count = counters.get(key, 0) + 1
        counters[key] = count
        data[user_id]["counters"] = counters
        save_data(data)
        if count == 1:
            await reply_bot(MSG_REMITLY_1)
            await notify_admin(f"🔔 QUIERE PAGAR POR REMITLY (1 vez)")
        else:
            await reply_bot(MSG_REMITLY_2)
            await notify_admin(f"🔔 QUIERE PAGAR POR REMITLY ({count} veces)")
        return
    is_yapague = contains_any(norm, KW_YAPAGUE) or (has_photo and not norm)
    if is_yapague:
        last_topic = data[user_id].get("last_topic", "vip")
        if "tanga" in norm:
            last_topic = "tanga"
        if last_topic == "tanga":
            key = "tanga"
            count = counters.get(key, 0) + 1
            counters[key] = count
            data[user_id]["counters"] = counters
            save_data(data)
            if count == 1:
                await reply_bot(MSG_YAPAGUE_TANGA_1)
                await notify_admin(f"🔔 NUEVO COMPROBANTE TANGA (1 vez)", forward_photo=True)
            else:
                await reply_bot(MSG_YAPAGUE_TANGA_2)
                await notify_admin(f"🔔 NUEVO COMPROBANTE TANGA ({count} veces)", forward_photo=True)
        else:
            key = "vip"
            count = counters.get(key, 0) + 1
            counters[key] = count
            data[user_id]["counters"] = counters
            save_data(data)
            if count == 1:
                await reply_bot(MSG_YAPAGUE_VIP_1)
                await notify_vip_receipt(count, forward_photo=True)
            else:
                await reply_bot(MSG_YAPAGUE_VIP_2)
                await notify_vip_receipt(count, forward_photo=True)
        return
    if contains_any(norm, KW_CONFIANZA):
        await reply_bot(MSG_CONFIANZA)
        await notify_admin(f"🔔 DUDA DE CONFIANZA\nPreguntó: \"{text}\"")
        return
    if contains_any(norm, KW_RENOVACION):
        data[user_id]["counters"]["renovacion_solicitada"] = True
        data[user_id]["last_topic"] = "vip"
        save_data(data)
        await reply_bot(MSG_RENOVACION)
        return
    if contains_any(norm, KW_PAGAR):
        data[user_id]["last_topic"] = "vip"
        save_data(data)
        await reply_bot(metodos_pago_texto)
        return
    if contains_any(norm, KW_TANGAS):
        data[user_id]["last_topic"] = "tanga"
        save_data(data)
        await reply_bot(MSG_TANGAS)
        return
    if (
        any(variante in texto_norm for variante in variantes_vip_info)
        or contains_any(norm, KW_VIP)
        or "🔥" in text
    ):
        data[user_id]["last_topic"] = "vip"
        save_data(data)
        await reply_bot(vip_info_texto)
        return
    await reply_bot(MSG_NO_CONTEMPLADA)
    pregunta_texto_html = html_escape(msg.text or text)
    full_name_html = html_escape(full_name)
    username_for_question = msg.from_user.username if msg.from_user.username else "Sin username"
    texto_pregunta = f"""
🔔 PREGUNTA NO CONTEMPLADA
Preguntó: "{pregunta_texto_html}"
De: {full_name_html}
Username: @{html_escape(username_for_question)}
ID: <code>{msg.from_user.id}</code>
Texto: {pregunta_texto_html}

👉 <a href='tg://user?id={msg.from_user.id}'>ENTRAR A LA CONVERSACIÓN CON {full_name_html}</a>
"""
    await context.bot.send_message(chat_id=ADMIN_ID, text=texto_pregunta, parse_mode="HTML")

async def handle_historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    command_message = update.effective_message
    if not command_message:
        return
    history = load_conversation_history()
    args = context.args
    if not args:
        msg = "📋 Últimos clientes con historial:\n\n"
        for uid, entries in list(history.items())[-10:]:
            if not isinstance(entries, list) or not entries:
                continue
            latest = entries[-1]
            msg += (
                f"{latest.get('username', 'Sin username')} "
                f"ID:{uid} - {len(entries)} mensajes\n"
            )
        msg += "\nUsa: /historial ID"
        for chunk in split_long_text(msg):
            await command_message.reply_text(chunk)
        return
    target_id = args[0].strip()
    if not target_id.isdigit():
        await command_message.reply_text("Uso: /historial ID (ejemplo: /historial 8864303511)")
        return
    entries = history.get(target_id, [])
    if not isinstance(entries, list) or not entries:
        await command_message.reply_text(f"No hay historial para el ID {target_id}.")
        return
    recent_entries = entries[-20:]
    latest = recent_entries[-1]
    username = latest.get("username", "Sin username")
    full_name = latest.get("nombre", "Cliente")
    lines = [
        f"📜 Últimos {len(recent_entries)} mensajes de {full_name} ({username})",
        f"ID: {target_id}",
    ]
    for entry in recent_entries:
        sender = "CLIENTE" if entry.get("emisor") == "cliente" else "BOT"
        timestamp = entry.get("fecha_hora", "Fecha desconocida")
        message_text = entry.get("mensaje", "[mensaje sin texto]")
        lines.append(f"\n[{timestamp}] {sender}\n{message_text}")
    for chunk in split_long_text("\n".join(lines)):
        await command_message.reply_text(chunk)

async def handle_agregar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    command_message = update.effective_message
    if not command_message:
        return
    if len(context.args) not in (1, 2):
        await reply_admin(context.bot, "Uso: /agregar ID [días]. Ejemplos: /agregar 8864303511 o /agregar 8864303511 60")
        return
    target_id = context.args[0].strip()
    if not target_id.isdigit() or int(target_id) <= 0:
        await reply_admin(context.bot, "El ID debe ser un número positivo.")
        return
    days = 30
    if len(context.args) == 2:
        try:
            days = int(context.args[1])
        except ValueError:
            await reply_admin(context.bot, "Los días deben ser un número entero positivo.")
            return
        if days <= 0:
            await reply_admin(context.bot, "Los días deben ser un número entero positivo.")
            return
    full_name = await get_user_display_name(context.bot, target_id)
    now = datetime.now(MEXICO_CITY)
    expiration = now + timedelta(days=days)
    subscribers = load_subscribers()
    subscribers[target_id] = {
        "user_id": int(target_id),
        "nombre": full_name,
        "fecha_inicio": now.isoformat(timespec="seconds"),
        "fecha_vencimiento": expiration.isoformat(timespec="seconds"),
    }
    save_subscribers(subscribers)
    client_message = f"Tu acceso VIP activado hasta {expiration:%d/%m/%Y}"
    try:
        await context.bot.send_message(chat_id=int(target_id), text=client_message)
        confirmation = (
            f"✅ Acceso VIP activado para {html_escape(full_name)} "
            f"hasta {expiration:%d/%m/%Y} ({days} días)."
        )
    except Exception as error:
        confirmation = (
            f"⚠️ Guardé la suscripción de {html_escape(full_name)} hasta "
            f"{expiration:%d/%m/%Y}, pero no pude enviarle el mensaje: "
            f"{html_escape(str(error)[:300])}"
        )
    await reply_admin(context.bot, confirmation, target_id, full_name)

async def handle_ver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    command_message = update.effective_message
    if not command_message:
        return
    if len(context.args) != 1:
        await reply_admin(context.bot, "Uso: /ver ID")
        return
    target_id = context.args[0].strip()
    if not target_id.isdigit() or int(target_id) <= 0:
        await reply_admin(context.bot, "El ID debe ser un número positivo.")
        return
    subscribers = load_subscribers()
    subscriber = subscribers.get(target_id)
    full_name = (
        str(subscriber.get("nombre") or f"Usuario {target_id}")
        if isinstance(subscriber, dict)
        else await get_user_display_name(context.bot, target_id)
    )
    if not isinstance(subscriber, dict):
        await reply_admin(
            context.bot,
            f"No encontré una suscripción activa para ID {target_id}.",
            target_id,
            full_name,
        )
        return
    try:
        expiration = datetime.fromisoformat(subscriber["fecha_vencimiento"])
        due_date = expiration.strftime("%d/%m/%Y")
    except (KeyError, TypeError, ValueError):
        await reply_admin(
            context.bot,
            f"El registro de vencimiento para ID {target_id} no es válido.",
            target_id,
            full_name,
        )
        return
    await reply_admin(
        context.bot,
        f"📅 {html_escape(full_name)} (ID {target_id}) vence el {due_date}.",
        target_id,
        full_name,
    )

async def handle_quitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    command_message = update.effective_message
    if not command_message:
        return
    if len(context.args) != 1:
        await reply_admin(context.bot, "Uso: /quitar ID")
        return
    target_id = context.args[0].strip()
    if not target_id.isdigit() or int(target_id) <= 0:
        await reply_admin(context.bot, "El ID debe ser un número positivo.")
        return
    subscribers = load_subscribers()
    subscriber = subscribers.get(target_id)
    full_name = (
        str(subscriber.get("nombre") or f"Usuario {target_id}")
        if isinstance(subscriber, dict)
        else await get_user_display_name(context.bot, target_id)
    )
    try:
        await remove_user_from_vip_group(context.bot, int(target_id))
    except Exception as error:
        await reply_admin(
            context.bot,
            f"⚠️ No pude sacar a {html_escape(full_name)} ID {target_id} "
            f"del grupo VIP: {html_escape(str(error)[:300])}",
            target_id,
            full_name,
        )
        return
    subscribers.pop(target_id, None)
    save_subscribers(subscribers)
    await reply_admin(
        context.bot,
        f"✅ Saqué a {html_escape(full_name)} ID {target_id} del grupo VIP "
        "y eliminé su suscripción.",
        target_id,
        full_name,
    )

def main():
    migrate_legacy_history()
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(start_subscription_expiration_monitor)
        .post_shutdown(stop_subscription_expiration_monitor)
        .build()
    )
    app.add_handler(BusinessConnectionHandler(handle_business_connection))
    app.add_handler(CommandHandler("historial", handle_historial))
    app.add_handler(CommandHandler("agregar", handle_agregar))
    app.add_handler(CommandHandler("ver", handle_ver))
    app.add_handler(CommandHandler("quitar", handle_quitar))
    app.add_handler(MessageHandler(filters.ALL, handle_business_message))
    print("Bot VIP Asistente con HISTORIAL, VENCIMIENTOS y ANTI-BUCLE iniciado")
    app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    keep_alive()
    main()
