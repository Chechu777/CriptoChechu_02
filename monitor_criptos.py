import os
import asyncio
import threading
import time
import requests
from telegram import Bot
from telegram.constants import ParseMode  # Si da error, usa 'Markdown' directo como string
from flask import Flask

# Config
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CRYPTO_IDS = ["bitcoin", "cardano", "solana", "shiba-inu"]
API_URL = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(CRYPTO_IDS)}&vs_currencies=eur"

if not TOKEN or not CHAT_ID:
    raise Exception("Faltan variables de entorno TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")

bot = Bot(token=TOKEN)

# Precio anterior para comparación
precios_anteriores = {}

# App Flask para mantener vivo en Render
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot activo ✅"

def obtener_precios():
    try:
        response = requests.get(API_URL)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print("Error al obtener precios:", e)
        return {}

def detectar_cambios(precios_actuales):
    mensajes = []
    for crypto, datos in precios_actuales.items():
        actual = datos["eur"]
        anterior = precios_anteriores.get(crypto)

        if anterior:
            cambio = ((actual - anterior) / anterior) * 100
            if abs(cambio) >= 3:
                emoji = "📈" if cambio > 0 else "📉"
                mensajes.append(f"{emoji} *{crypto.upper()}*: {actual:.2f} EUR ({cambio:+.2f}%)")

        precios_anteriores[crypto] = actual
    return mensajes

async def enviar_resumen_diario():
    while True:
        precios = obtener_precios()
        if precios:
            resumen = "*Resumen diario de criptos 🕗*\n\n"
            for crypto, datos in precios.items():
                precio = datos["eur"]
                resumen += f"• *{crypto.upper()}*: {precio:.2f} EUR\n"

            await bot.send_message(chat_id=CHAT_ID, text=resumen, parse_mode=ParseMode.MARKDOWN)
        await asyncio.sleep(86400)  # 24h

async def monitorear_cambios():
    while True:
        precios = obtener_precios()
        cambios = detectar_cambios(precios)
        for mensaje in cambios:
            await bot.send_message(chat_id=CHAT_ID, text=mensaje, parse_mode=ParseMode.MARKDOWN)
        await asyncio.sleep(300)  # cada 5 min

def start_bot_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(asyncio.gather(
        enviar_resumen_diario(),
        monitorear_cambios()
    ))

if __name__ == "__main__":
    threading.Thread(target=start_bot_loop).start()
    app.run(host="0.0.0.0", port=10000)
