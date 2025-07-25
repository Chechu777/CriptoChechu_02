import os
from flask import Flask, request
from datetime import datetime
import telegram
import logging
import threading
import time

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")

bot = telegram.Bot(token=TELEGRAM_TOKEN)

def obtener_resumen():
    # Aquí va tu lógica real de precios y RSI
    resumen = (
        "📊 *Resumen Diario Criptomonedas*\n\n"
        "🔹 BTC: $29,000 | RSI: 48\n"
        "🔹 ADA: $0.29 | RSI: 40\n"
        "🔹 SOL: $26.50 | RSI: 55\n"
        "🔹 SHIBA: $0.000007 | RSI: 60\n"
        "\n_Actualizado: " + datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC') + "_"
    )
    return resumen

def enviar_resumen_diario():
    while True:
        ahora = datetime.now().strftime("%H:%M")
        if ENVIAR_RESUMEN_DIARIO and ahora == RESUMEN_HORA:
            resumen = obtener_resumen()
            bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=resumen, parse_mode=telegram.ParseMode.MARKDOWN)
            time.sleep(60)  # Esperar 1 minuto para evitar reenvíos en el mismo minuto
        time.sleep(20)  # Espera antes de volver a comprobar

@app.route("/resumen", methods=["GET"])
def resumen():
    resumen = obtener_resumen()
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=resumen, parse_mode=telegram.ParseMode.MARKDOWN)
    return "Resumen enviado correctamente."

# Iniciar el hilo del resumen si está activado
if ENVIAR_RESUMEN_DIARIO:
    threading.Thread(target=enviar_resumen_diario, daemon=True).start()
