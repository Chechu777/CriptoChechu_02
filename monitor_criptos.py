from flask import Flask
import requests
import os
import datetime
import schedule
import time
import threading

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("CMC_API_KEY")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")

CRIPTO_IDS = {
    "bitcoin": "BTC",
    "solana": "SOL",
    "cardano": "ADA",
    "shiba-inu": "SHIBA"
}

def obtener_datos_criptos():
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    params = {
        "symbol": ",".join(CRIPTO_IDS.values()),
        "convert": "EUR"
    }
    url_precio = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    url_rsi = "https://api.taapi.io/rsi"

    respuesta_precio = requests.get(url_precio, headers=headers, params=params)
    datos_precio = respuesta_precio.json()

    datos = {}
    for nombre, simbolo in CRIPTO_IDS.items():
        info = datos_precio["data"][simbolo]
        precio = info["quote"]["EUR"]["price"]

        rsi_respuesta = requests.get(url_rsi, params={
            "secret": os.getenv("TAAPI_KEY"),
            "exchange": "binance",
            "symbol": f"{simbolo}/USDT",
            "interval": "1h"
        })

        rsi_valor = rsi_respuesta.json().get("value", None)

        datos[nombre] = {
            "simbolo": simbolo,
            "precio": precio,
            "rsi": rsi_valor
        }

    return datos

def crear_mensaje(datos):
    mensaje = "📊 *Resumen de criptomonedas:*\n\n"
    for nombre, info in datos.items():
        precio = info["precio"]
        rsi = info["rsi"]
        consejo = ""
        if rsi is not None:
            if rsi < 30:
                consejo = "💸 (RSI bajo)\n*Te aconsejo que compres* 🟢"
            elif rsi > 70:
                consejo = "📈 (RSI alto)\n*Te aconsejo que vendas* 🔴"
            else:
                consejo = "📉 (RSI medio)\n*Te aconsejo que te estés quieto por ahora* 🟡"
        else:
            consejo = "RSI no disponible"

        mensaje += (
            f"*{nombre.upper()}*:\n"
            f"Precio: `{precio:.8f}` €\n"
            f"RSI: `{rsi:.1f}` → {consejo}\n\n"
        )

    return mensaje

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    requests.post(url, data=payload)

@app.route("/")
def home():
    return "🟢 Bot monitor_criptos activo"

@app.route("/resumen")
def resumen():
    ahora = datetime.datetime.now().strftime("%H:%M")
    if ahora != RESUMEN_HORA:
        return f"No es la hora del resumen ({ahora} ≠ {RESUMEN_HORA}) ⏰"
    datos = obtener_datos_criptos()
    mensaje = crear_mensaje(datos)
    enviar_telegram(mensaje)
    return "Resumen diario enviado ✅"

@app.route("/resumen_manual")
def resumen_manual():
    datos = obtener_datos_criptos()
    mensaje = crear_mensaje(datos)
    enviar_telegram(mensaje)
    return "Resumen manual enviado ✅"

def tarea_programada():
    if ENVIAR_RESUMEN_DIARIO:
        schedule.every().day.at(RESUMEN_HORA).do(lambda: enviar_telegram(
            crear_mensaje(obtener_datos_criptos())))
        while True:
            schedule.run_pending()
            time.sleep(1)

if __name__ == "__main__":
    threading.Thread(target=tarea_programada).start()
    app.run(host="0.0.0.0", port=10000)
