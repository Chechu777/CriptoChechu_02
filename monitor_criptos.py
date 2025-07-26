import os
import time
import threading
import datetime
import requests
from flask import Flask
from pytz import timezone

app = Flask(__name__)

# Configuración
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")

ZONA_HORARIA = timezone("Europe/Madrid")

CRIPTOS = ['BTC', 'ETH', 'ADA', 'SHIB', 'SOL']
URL_BASE = "https://api.binance.com/api/v3/ticker/price?symbol="

# Precios de referencia para ejemplo (ajusta con valores reales o históricos)
PRECIOS_REFERENCIA = {
    'BTC': 37000,
    'ETH': 2100,
    'ADA': 0.30,
    'SHIB': 0.0000075,
    'SOL': 26.5
}

def obtener_precio_eur(cripto):
    symbol = (cripto + "eur").upper()
    try:
        response = requests.get(URL_BASE + symbol)
        response.raise_for_status()
        return float(response.json()["price"])
    except Exception as e:
        print(f"[ERROR] No se pudo obtener el precio de {cripto}: {e}")
        return None

def calcular_rsi_dummy(cripto):
    # Simulación simple: RSI aleatorio para ejemplo (en la práctica calcula real)
    # Aquí te pongo un valor fijo para que se entienda la lógica
    rsi_ejemplo = {
        'BTC': 45,
        'ETH': 70,
        'ADA': 30,
        'SHIB': 55,
        'SOL': 65
    }
    return rsi_ejemplo.get(cripto, 50)

def consejo_por_rsi(rsi):
    if rsi < 30:
        return "🔥 *TE ACONSEJO QUE COMPRES*, está sobrevendido."
    elif rsi > 70:
        return "⚠️ *TE ACONSEJO QUE VENDAS*, está sobrecomprado."
    else:
        return "👌 *Mantén la calma*, mercado estable."

def obtener_resumen_diario():
    resumen = "📊 *Resumen diario de criptomonedas* 📊\n\n"
    for cripto in CRIPTOS:
        precio = obtener_precio_eur(cripto)
        if precio is None:
            resumen += f"⚠️ {cripto}: Error al obtener precio\n"
            continue

        rsi = calcular_rsi_dummy(cripto)
        consejo = consejo_por_rsi(rsi)
        
        precio_ref = PRECIOS_REFERENCIA.get(cripto, precio)
        tendencia = ""
        if precio < precio_ref * 0.95:
            tendencia = "📉 Precio ha bajado un 5% respecto al referencia."
        elif precio > precio_ref * 1.05:
            tendencia = "📈 Precio ha subido un 5% respecto al referencia."
        
        resumen += f"💰 {cripto}: {precio:,.6f} €\nRSI: {rsi}\n{consejo}\n{tendencia}\n\n"

    resumen += f"_Actualizado: {datetime.datetime.now(ZONA_HORARIA).strftime('%Y-%m-%d %H:%M:%S')}_\n"
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
                time.sleep(60)  # evitar duplicados
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
