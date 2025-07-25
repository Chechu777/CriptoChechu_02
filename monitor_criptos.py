import asyncio
import threading
import logging
from flask import Flask
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler
import yfinance as yf
import datetime
import os

# --- Configuración ---
TOKEN = os.getenv("BOT_TOKEN")  # Usa variable de entorno segura en Render
CHAT_ID = os.getenv("CHAT_ID")
MONEDAS = ["ADA-USD", "SHIB-USD", "SOL-USD", "BTC-USD"]
INTERVALO_SEGUNDOS = 300  # 5 minutos

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)

# --- Flask para mantener servicio activo ---
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot Cripto en ejecución"

# --- Funciones principales ---
async def obtener_precio_actual(moneda):
    data = yf.download(tickers=moneda, period='1d', interval='1m')
    if data.empty:
        return None
    return round(data['Close'].iloc[-1], 6)

async def enviar_alerta(bot, moneda, precio):
    try:
        msg = f"🚨 <b>{moneda}</b> ha cambiado. Precio actual: <b>{precio}</b> USD"
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.HTML)
    except TelegramError as e:
        logging.error(f"Error al enviar mensaje: {e}")

async def monitorear(bot):
    precios_anteriores = {}
    while True:
        for moneda in MONEDAS:
            precio = await obtener_precio_actual(moneda)
            if precio:
                anterior = precios_anteriores.get(moneda)
                if anterior and abs(precio - anterior) > anterior * 0.01:
                    await enviar_alerta(bot, moneda, precio)
                precios_anteriores[moneda] = precio
        await asyncio.sleep(INTERVALO_SEGUNDOS)

async def enviar_resumen_diario(bot):
    while True:
        ahora = datetime.datetime.now()
        if ahora.hour == 21 and ahora.minute == 28:
            resumen = "📊 <b>Resumen Diario:</b>\n"
            for moneda in MONEDAS:
                precio = await obtener_precio_actual(moneda)
                if precio:
                    resumen += f"🔹 {moneda}: <b>{precio}</b> USD\n"
            try:
                await bot.send_message(chat_id=CHAT_ID, text=resumen, parse_mode=ParseMode.HTML)
            except TelegramError as e:
                logging.error(f"Error al enviar resumen: {e}")
            await asyncio.sleep(60)
        await asyncio.sleep(30)

# --- Bot y loop ---
async def main_async():
    bot = Bot(token=TOKEN)
    await asyncio.gather(
        monitorear(bot),
        enviar_resumen_diario(bot)
    )

def start_bot_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main_async())

# --- Lanzar bot en hilo paralelo ---
threading.Thread(target=start_bot_loop, daemon=True).start()

# --- Ejecutar Flask para mantener app viva en Render ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
