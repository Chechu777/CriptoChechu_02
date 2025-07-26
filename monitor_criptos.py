import os
import time
import threading
import datetime
import requests
from flask import Flask
from pytz import timezone

app = Flask(__name__)

# Configuración desde variables de entorno
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")
ZONA_HORARIA = timezone("Europe/Madrid")

# Criptos a seguir y precios de referencia
CRIPTOS = ['BTC', 'ETH', 'ADA', 'SHIB', 'SOL']
COINGECKO_IDS = {
    'BTC': 'bitcoin',
    'ETH': 'ethereum',
    'ADA': 'cardano',
    'SHIB': 'shiba-inu',
    'SOL': 'solana'
}
PRECIOS_REFERENCIA = {
    'BTC': 37000,
    'ETH': 2100,
    'ADA': 0.30,
    'SHIB': 0.0000075,
    'SOL': 26.5
}

# Obtener todos los precios de Coingecko en una sola llamada
def obtener_precios_eur():
    ids = ','.join(COINGECKO_IDS[c] for c in CRIPTOS)
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=eur"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[ERROR] No se pudieron obtener precios: {e}")
        return {}

# RSI ficticio para ejemplo
def calcular_rsi_dummy(cripto):
    valores_rsi = {
        'BTC': 45,
        'ETH': 70,
        'ADA': 30,
        'SHIB': 55,
        'SOL': 65
    }
    return valores_rsi.get(cripto, 50)

def consejo_por_rsi(rsi):
    if rsi < 30:
        return "🔥 *TE ACONSEJO QUE COMPRES*, está sobrevendido."
    elif rsi > 70:
        return "⚠️ *TE ACONSEJO QUE VENDAS*, está sobrecomprado."
    else:
        return "👌 *Mantén la calma*, el mercado está estable."

# Crear resumen
def obtener_resumen_diario():
    precios = obtener_precios_eur()
    resumen = "📊 *Resumen diario de criptomonedas* 📊\n\n"

    for cripto in CRIPOS:
        cripto_id = COINGECKO_IDS[cripto]
        precio = precios.get(cripto_id, {}).get("eur")
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

# Enviar a Telegram
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

# Hilo programado
def tarea_programada():
    print("[INFO] Hilo de resumen diario iniciado.")
    while True:
        if ENVIAR_RESUMEN_DIARIO:
            ahora = datetime.datetime.now(ZONA_HORARIA).strftime("%H:%M")
            if ahora == RESUMEN_HORA:
                resumen = obtener_resumen_diario()
                enviar_mensaje(resumen)
                print(f"[INFO] Resumen enviado a las {ahora}")
                time.sleep(60)
        time.sleep(20)

# Rutas web
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

# Lanzar hilo
if ENVIAR_RESUMEN_DIARIO:
    threading.Thread(target=tarea_programada, daemon=True).start()
