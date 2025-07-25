import os
import requests
import telegram
from flask import Flask
from datetime import datetime
import pytz
import asyncio

app = Flask(__name__)

# Variables de entorno
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "22:45")

# Render asigna dinámicamente el puerto
PORT = int(os.environ.get("PORT", 10000))

criptos = ['BTC', 'ADA', 'SHIB', 'SOL']
url_base = "https://api.binance.com/api/v3/ticker/price?symbol="

bot = telegram.Bot(token=TOKEN)

def obtener_precio(cripto):
    try:
        response = requests.get(url_base + cripto + "USDT")
        response.raise_for_status()
        precio = float(response.json()["price"])
        return precio
    except Exception as e:
        return f"Error obteniendo {cripto}: {str(e)}"

def generar_resumen():
    ahora = datetime.now(pytz.timezone("Europe/Madrid")).strftime("%Y-%m-%d %H:%M:%S")
    resumen = f"📊 *Resumen Diario - {ahora}* 📊\n\n"
    for cripto in criptos:
        precio = obtener_precio(cripto)
        resumen += f"💰 {cripto}: {precio} USDT\n"
    return resumen

@app.route("/")
def home():
    return "Monitor Criptos activo!"

async def enviar_resumen_diario():
    while True:
        if ENVIAR_RESUMEN_DIARIO:
            ahora = datetime.now(pytz.timezone("Europe/Madrid")).strftime("%H:%M")
            if ahora == RESUMEN_HORA:
                resumen = generar_resumen()
                await bot.send_message(chat_id=CHAT_ID, text=resumen, parse_mode="Markdown")
                await asyncio.sleep(60)  # Evita reenvíos múltiples en el mismo minuto
        await asyncio.sleep(10)

def iniciar_loop_async():
    loop = asyncio.get_event_loop()
    if not loop.is_running():
        loop.create_task(enviar_resumen_diario())

if __name__ == "__main__":
    iniciar_loop_async()
    app.run(host="0.0.0.0", port=PORT)
