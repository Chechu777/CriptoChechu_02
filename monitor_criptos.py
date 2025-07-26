import os
import requests
import datetime
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")
CMC_API_KEY = os.getenv("CMC_API_KEY")

CRYPTO_IDS = {
    "bitcoin": "BTC",
    "cardano": "ADA",
    "shiba-inu": "SHIB",
    "solana": "SOL"
}


def obtener_precios_y_rsi():
    headers = {
        "Accepts": "application/json",
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
    }

    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    symbol_list = ",".join(CRYPTO_IDS.values())

    params = {
        "symbol": symbol_list,
        "convert": "EUR"
    }

    response = requests.get(url, headers=headers, params=params)
    data = response.json()["data"]

    resultados = []

    for nombre, simbolo in CRYPTO_IDS.items():
        info = data[simbolo]
        precio = info["quote"]["EUR"]["price"]
        rsi = calcular_rsi_dummy(precio)  # Usa una función dummy por ahora
        resultados.append({"nombre": nombre.upper(), "precio": precio, "rsi": rsi})

    return resultados


def calcular_rsi_dummy(precio):
    # Simulación básica solo para demo. Sustituye por cálculo real si deseas.
    from random import randint
    return randint(10, 90)


def generar_mensaje_resumen(data):
    mensaje = "📰 *Resumen diario de criptos* 📊\n\n"
    for moneda in data:
        nombre = moneda["nombre"]
        precio = moneda["precio"]
        rsi = moneda["rsi"]
        consejo = ""

        if rsi is not None:
            if rsi < 30:
                consejo = "💸 *Te aconsejo que compres* (RSI bajo)"
            elif rsi > 70:
                consejo = "📈 *Te aconsejo que vendas* (RSI alto)"
            else:
                consejo = "🧘 *Te aconsejo que te estés quieto por ahora* (RSI estable)"
            mensaje += f"*{nombre}*: {precio:.2f}€ | RSI: {rsi:.1f} → {consejo}\n"
        else:
            mensaje += f"*{nombre}*: {precio:.2f}€ | RSI: No disponible 😕\n"

    mensaje += "\n🤖 Este mensaje es generado automáticamente cada día. ¡Bendiciones!"
    return mensaje


def enviar_mensaje_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    return response.json()


def enviar_resumen_diario():
    if ENVIAR_RESUMEN_DIARIO:
        print("[INFO] Generando resumen diario...")
        data = obtener_precios_y_rsi()
        mensaje = generar_mensaje_resumen(data)
        enviar_mensaje_telegram(mensaje)


# ────── ⏰ SCHEDULER ──────
def configurar_scheduler():
    hora, minuto = map(int, RESUMEN_HORA.split(":"))
    scheduler = BackgroundScheduler(timezone="Europe/Madrid")
    scheduler.add_job(enviar_resumen_diario, "cron", hour=hora, minute=minuto)
    scheduler.start()
    print(f"[INFO] Scheduler activado para las {RESUMEN_HORA}.")


# ────── 🌐 ENDPOINTS ──────
@app.route("/")
def home():
    return "Bot de criptomonedas activo ✅"


@app.route("/resumen_manual", methods=["GET"])
def resumen_manual():
    print("[INFO] Envío manual del resumen")
    data = obtener_precios_y_rsi()
    mensaje = generar_mensaje_resumen(data)
    enviar_mensaje_telegram(mensaje)
    return "Resumen enviado manualmente ✅"


# ────── 🚀 INICIO ──────
if __name__ == "__main__":
    configurar_scheduler()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
