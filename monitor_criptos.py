import os
import time
import threading
import datetime
import requests
from flask import Flask
from pytz import timezone

# Flask app
app = Flask(__name__)

# Configuración
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")

# ZONA HORARIA
ZONA_HORARIA = timezone("Europe/Madrid")

# Lista de criptos a monitorear
CRIPTOS = ['BTC', 'ETH', 'ADA', 'SHIB', 'SOL']

# URL base de Binance para precios
URL_BASE = "https://api.binance.com/api/v3/ticker/price?symbol="

def obtener_precio_eur(cripto):
    symbol = cripto + "EUR"  # Ejemplo: BTCEUR
    try:
        response = requests.get(URL_BASE + symbol)
        response.raise_for_status()
        precio = float(response.json()["price"])
        return precio
    except Exception as e:
        return f"Error: {e}"

def calcular_rsi_dummy():
    # RSI de ejemplo fijo, para que lo ajustes luego con tu lógica
    return 52

def obtener_resumen_diario():
    resumen = "📊 *Resumen diario de criptomonedas* 📊\n\n"
    for cripto in CRIPTOS:
        precio = obtener_precio_eur(cripto)
        if isinstance(precio, float):
            resumen += f"💰 {cripto}: {precio:,.2f} €\n"
        else:
            resumen += f"⚠️ {cripto}: {precio}\n"
    resumen += f"\nRSI promedio: {calcular_rsi_dummy()}\n"
    resumen += f"\n_Actualizado: {datetime.datetime.now(ZONA_HORARIA).strftime('%Y-%m-%d %H:%M:%S')}_\n"
    return resumen

def enviar_mensaje(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, data=payload)
        r.raise_for_status()
        print("[INFO] Mensaje enviado correctamente")
    except Exception as e:
        print(f"[ERROR] Al enviar mensaje: {e}")

def tarea_programada():
    print("[INFO] Hilo de resumen diario iniciado.")
    while True:
        if ENVIAR_RESUMEN_DIARIO:
            ahora = datetime.datetime.now(ZONA_HORARIA).strftime("%H:%M")
            if ahora == RESUMEN_HORA:
                resumen = obtener_resumen_diario()
                enviar_mensaje(resumen)
                print(f"[INFO] Resumen enviado a las {ahora}")
                time.sleep(60)  # evitar duplicados en el mismo minuto
        time.sleep(20)

@app.route("/")
def home():
    return "Bot monitor_criptos activo ✅"

@app.route("/resumen")
def resumen_manual():
    try:
        resumen = obtener_resumen_diario()
        enviar_mensaje(f"[PRUEBA MANUAL]\n{resumen}")
        return "Resumen enviado manualmente"
    except Exception as e:
        return f"Error al generar resumen: {e}"

if ENVIAR_RESUMEN_DIARIO:
    threading.Thread(target=tarea_programada, daemon=True).start()
