import os
import requests
import telegram
from flask import Flask
from datetime import datetime
import pytz

app = Flask(__name__)

# Variables de entorno
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"

criptos = ['BTC', 'ADA', 'SHIB', 'SOL']
url_base = "https://api.binance.com/api/v3/ticker/price?symbol="

bot = telegram.Bot(token=TOKEN)

def obtener_precio(cripto):
    try:
        response = requests.get(url_base + cripto + "USDT")
        response.raise_for_status()
        return float(response.json()["price"])
    except Exception as e:
        return f"Error: {str(e)}"

def generar_resumen():
    ahora = datetime.now(pytz.timezone("Europe/Madrid")).strftime("%Y-%m-%d %H:%M:%S")
    resumen = f"📊 *Resumen Diario - {ahora}* 📊\n\n"
    for cripto in criptos:
        precio = obtener_precio(cripto)
        resumen += f"💰 {cripto}: {precio} USDT\n"
    return resumen

@app.route("/")
def home():
    return "✅ Bot Criptos activo."

@app.route("/resumen")
def resumen():
    if ENVIAR_RESUMEN_DIARIO:
        mensaje = generar_resumen()
        bot.send_message(chat_id=CHAT_ID, text=mensaje, parse_mode="Markdown")
        return "Resumen enviado por Telegram ✅"
    else:
        return "ENVIAR_RESUMEN_DIARIO está desactivado ❌"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
