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
ZONA_HORARIA = timezone("Europe/Madrid")  # Ajusta si usas otra

# Función para enviar mensaje a Telegram
def enviar_mensaje(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}
    try:
        r = requests.post(url, data=payload)
        r.raise_for_status()
    except Exception as e:
        print(f"Error al enviar mensaje: {e}")

# Función que genera el resumen (puedes personalizar esto)
def obtener_resumen_diario():
    return "Resumen diario:\nBTC: 37.000€\nETH: 2.100€\nRSI: 52\n(Esto es un ejemplo)"

# Envío automático a la hora configurada
def tarea_programada():
    print("[INFO] Hilo de resumen diario iniciado.")
    while True:
        if ENVIAR_RESUMEN_DIARIO:
            ahora = datetime.datetime.now(ZONA_HORARIA).strftime("%H:%M")
            if ahora == RESUMEN_HORA:
                resumen = obtener_resumen_diario()
                enviar_mensaje(resumen)
                print(f"[INFO] Resumen enviado a las {ahora}")
                time.sleep(60)  # Espera 1 minuto para evitar duplicados
        time.sleep(20)  # Verifica cada 20 segundos

# Endpoint de prueba manual
@app.route("/resumen")
def resumen_manual():
    try:
        resumen = obtener_resumen_diario()
        enviar_mensaje(f"[PRUEBA MANUAL]\n{resumen}")
        return "Resumen enviado manualmente"
    except Exception as e:
        return f"Error al generar resumen: {e}"

# Arrancar el hilo al iniciar el servidor
if ENVIAR_RESUMEN_DIARIO:
    threading.Thread(target=tarea_programada, daemon=True).start()

# Endpoint base
@app.route("/")
def home():
    return "Bot monitor_criptos activo ✅"
