import os
import time
import threading
import datetime
import requests
from flask import Flask
from pytz import timezone

app = Flask(__name__)

# Variables de entorno
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("CMC_API_KEY")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")
ZONA_HORARIA = timezone("Europe/Madrid")

# Configuración de criptos
CRIPTOS = ['BTC', 'ETH', 'ADA', 'SHIB', 'SOL']
PRECIOS_REFERENCIA = {
    'BTC': 37000,
    'ETH': 2100,
    'ADA': 0.30,
    'SHIB': 0.0000075,
    'SOL': 26.5
}

# Obtener precios desde CoinMarketCap en EUR
def obtener_precio_eur(cripto):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accepts": "application/json"
    }
    params = {
        "symbol": cripto,
        "convert": "EUR"
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        return float(data["data"][cripto]["quote"]["EUR"]["price"])
    except Exception as e:
        print(f"[ERROR] No se pudo obtener el precio de {cripto} desde CoinMarketCap: {e}")
        return None

# Simulación de RSI
def calcular_rsi_dummy(cripto):
    valores_rsi = {
        'BTC': 45,
        'ETH': 70,
        'ADA': 30,
        'SHIB': 55,
        'SOL': 65
    }
    return valores_rsi.get(cripto, 50)

# Mensaje según RSI
def consejo_por_rsi(rsi):
    if rsi < 30:
        return "🔥 *TE ACONSEJO QUE COMPRES*, está sobrevendido."
    elif rsi > 70:
        return "⚠️ *TE ACONSEJO QUE VENDAS*, está sobrecomprado."
    else:
        return "👌 Mantén la calma, el mercado está estable."

# Generar resumen diario
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

        variacion = ""
        if precio < precio_ref * 0.95:
            variacion = "📉 Ha bajado más del 5% desde el precio referencia."
        elif precio > precio_ref * 1.05:
            variacion = "📈 Ha subido más del 5% desde el precio referencia."

        resumen += (
            f"💰 *{cripto}*: {precio:,.6f} €\n"
            f"📈 RSI: {rsi}\n"
            f"{consejo}\n"
            f"{variacion}\n\n"
        )

    hora_actual = datetime.datetime.now(ZONA_HORARIA).strftime('%Y-%m-%d %H:%M:%S')
    resumen += f"_Actualizado: {hora_actual}_"
    return resumen

# Enviar mensaje a Telegram
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

# Tarea programada diaria
def tarea_programada():
    print("[INFO] Hilo de resumen diario iniciado.")
    while True:
        if ENVIAR_RESUMEN_DIARIO:
            ahora = datetime.datetime.now(ZONA_HORARIA).strftime("%H:%M")
            if ahora == RESUMEN_HORA:
                resumen = obtener_resumen_diario()
                enviar_mensaje(resumen)
                print(f"[INFO] Resumen enviado a las {ahora}")
                time.sleep(60)  # Espera 60 segundos para evitar repeticiones
        time.sleep(20)

# Rutas Flask
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

# Arranque de tarea programada
if ENVIAR_RESUMEN_DIARIO:
    threading.Thread(target=tarea_programada, daemon=True).start()
