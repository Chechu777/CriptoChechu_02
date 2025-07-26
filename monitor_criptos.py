import os
import requests
from flask import Flask, request
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("CMC_API_KEY")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")

CRIPTOS = ["BTC", "ETH", "ADA", "SHIBA", "SOL"]
RSI_DATOS = {
    "BTC": 45.0,
    "ETH": 60.5,
    "ADA": 52.1,
    "SHIBA": 28.0,
    "SOL": 67.2
}

def obtener_precios():
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    parametros = {
        "symbol": ",".join(CRIPTOS),
        "convert": "EUR"
    }

    respuesta = requests.get(url, headers=headers, params=parametros)
    data = respuesta.json()
    precios = {}

    for simbolo in CRIPTOS:
        try:
            precio = data["data"][simbolo]["quote"]["EUR"]["price"]
            precios[simbolo] = round(precio, 8 if precio < 0.01 else 2)
        except KeyError:
            precios[simbolo] = None

    return precios

def analizar_rsi_y_recomendar(rsi):
    if rsi is None:
        return "RSI no disponible ❓", "🤷‍♂️ Te aconsejo que te informes primero"
    elif rsi < 30:
        return f"RSI: {rsi} → 💸 (RSI bajo)", "💰 Te aconsejo que compres"
    elif rsi > 70:
        return f"RSI: {rsi} → 🚀 (RSI alto)", "⚠️ Te aconsejo que vendas"
    else:
        return f"RSI: {rsi} → 🤏 (RSI neutral)", "😌 Te aconsejo que te estés quieto por ahora"

def enviar_mensaje_telegram(texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": texto}
    requests.post(url, data=payload)

def construir_mensaje():
    precios = obtener_precios()
    mensaje = "📈 *Resumen Cripto Diario* 📊\n\n"

    for cripto in CRIPTOS:
        precio = precios.get(cripto)
        rsi = RSI_DATOS.get(cripto)
        rsi_texto, consejo = analizar_rsi_y_recomendar(rsi)
        precio_texto = f"{precio}€" if precio is not None else "No disponible"
        mensaje += f"*{cripto}*: {precio_texto}\n{rsi_texto}\n{consejo}\n\n"

    return mensaje.strip()

@app.route("/")
def home():
    return "Bot monitor_criptos activo 🚀"

@app.route("/resumen", methods=["GET"])
def resumen_manual():
    mensaje = construir_mensaje()
    enviar_mensaje_telegram(mensaje)
    return "✅ Resumen enviado manualmente al Telegram 💬"

@app.route("/resumen_diario", methods=["GET"])
def resumen_diario():
    if not ENVIAR_RESUMEN_DIARIO:
        return "Resumen diario desactivado ❌"

    ahora = datetime.now(timezone.utc).astimezone()
    hora_actual = ahora.strftime("%H:%M")

    if hora_actual == RESUMEN_HORA:
        mensaje = construir_mensaje()
        enviar_mensaje_telegram(mensaje)
        return f"✅ Resumen enviado a las {hora_actual} 🕒"
    else:
        return f"No es la hora del resumen ({hora_actual} ≠ {RESUMEN_HORA}) ⏰"

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
