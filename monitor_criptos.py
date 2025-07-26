import os
import requests
from flask import Flask, request
from datetime import datetime
import pytz

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ENVIAR_RESUMEN_DIARIO = os.environ.get("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.environ.get("RESUMEN_HORA", "09:30")
API_KEY = os.environ.get("COINMARKETCAP_API_KEY")

cryptos = ["ADA", "SHIBA", "SOL", "BTC"]

def obtener_datos_crypto(nombre):
    url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    params = {"symbol": nombre, "convert": "EUR"}
    headers = {"X-CMC_PRO_API_KEY": API_KEY}
    r = requests.get(url, params=params, headers=headers)
    data = r.json()["data"][nombre]["quote"]["EUR"]
    return round(data["price"], 8), round(data["rsi"] if "rsi" in data else 50.0, 1)

def emoji_rsi(rsi):
    if rsi < 30:
        return "💸 (RSI bajo)"
    elif rsi > 70:
        return "🤑 (RSI alto)"
    else:
        return "😐 (RSI neutro)"

def consejo_rsi(rsi):
    if rsi < 30:
        return "Te aconsejo que compres 📈"
    elif rsi > 70:
        return "Te aconsejo que vendas 📉"
    else:
        return "Te aconsejo que te estés quieto por ahora 🤓"

def enviar_mensaje_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    requests.post(url, data=payload)

@app.route("/resumen", methods=["GET"])
def resumen():
    now = datetime.now(pytz.timezone("Europe/Madrid"))
    mensaje = f"🕒 *Resumen diario - {now.strftime('%Y-%m-%d %H:%M')}*\n\n"

    for cripto in cryptos:
        precio, rsi = obtener_datos_crypto(cripto)
        mensaje += (
            f"*{cripto}*: {precio:.8f}€\n"
            f"RSI: {rsi} → {emoji_rsi(rsi)}\n"
            f"{consejo_rsi(rsi)}\n\n"
        )

    enviar_mensaje_telegram(mensaje)
    return "✅ Resumen enviado manualmente a Telegram"

if __name__ == "__main__":
    app.run(debug=True)
