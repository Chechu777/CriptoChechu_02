import os
import requests
import telegram
from flask import Flask
from datetime import datetime
import pytz
import time

app = Flask(__name__)

# Variables de entorno
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")

criptos = {
    'bitcoin': 'BTC',
    'cardano': 'ADA',
    'shiba-inu': 'SHIB',
    'solana': 'SOL'
}

bot = telegram.Bot(token=TOKEN)

def obtener_precio(cripto_id):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={cripto_id}&vs_currencies=usd"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()[cripto_id]['usd']
    except Exception as e:
        return f"Error: {str(e)}"

def generar_resumen():
    ahora = datetime.now(pytz.timezone("Europe/Madrid")).strftime("%Y-%m-%d %H:%M:%S")
    resumen = f"📊 *Resumen Diario - {ahora}* 📊\n\n"
    for cripto_id, simbolo in criptos.items():
        precio = obtener_precio(cripto_id)
        resumen += f"💰 {simbolo}: {precio} USDT\n"
    return resumen

@app.route("/")
def home():
    return "✅ Bot Criptos activo."

@app.route("/resumen")
def resumen():
    if ENVIAR_RESUMEN_DIARIO:
        hora_actual = datetime.now(pytz.timezone("Europe/Madrid")).strftime("%H:%M")
        if hora_actual == RESUMEN_HORA:
            time.sleep(10)  # Delay para evitar errores por múltiples llamadas simultáneas
            mensaje = generar_resumen()
            bot.send_message(chat_id=CHAT_ID, text=mensaje, parse_mode="Markdown")
            return "Resumen enviado por Telegram ✅"
        else:
            return f"No es la hora del resumen ({hora_actual} ≠ {RESUMEN_HORA}) ⏰"
    else:
        return "ENVIAR_RESUMEN_DIARIO está desactivado ❌"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
