import os
import requests
from flask import Flask
from datetime import datetime
import pytz

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.environ.get("CMC_API_KEY")
ZONA_HORARIA = pytz.timezone("Europe/Madrid")

CRIPTOS = ['BTC', 'ETH', 'ADA', 'SHIB', 'SOL']
PRECIOS_REFERENCIA = {
    'BTC': 37000,
    'ETH': 2100,
    'ADA': 0.30,
    'SHIB': 0.0000075,
    'SOL': 26.5
}

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
        print(f"[ERROR] No se pudo obtener el precio de {cripto}: {e}")
        return None

def calcular_rsi_dummy(cripto):
    valores_rsi = {
        'BTC': 45,
        'ETH': 70,
        'ADA': 30,
        'SHIB': 28,
        'SOL': 65
    }
    return valores_rsi.get(cripto, 50)

def consejo_por_rsi(rsi):
    if rsi < 30:
        return "💸 RSI: *Bajo*\n📢 _Te aconsejo que compres_ 🛒"
    elif rsi > 70:
        return "🤑 RSI: *Alto*\n⚠️ _Te aconsejo que vendas_ 📤"
    else:
        return "😐 RSI: *Neutro*\n🤓 _Te aconsejo que te estés quieto por ahora_"

def obtener_resumen_diario():
    resumen = "📊 *Resumen de criptomonedas* 📊\n\n"
    for cripto in CRIPTOS:
        precio = obtener_precio_eur(cripto)
        if precio is None:
            resumen += f"⚠️ *{cripto}*: Error al obtener precio\n\n"
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
            f"*{cripto}*: {precio:,.8f} €\n"
            f"{consejo}\n"
            f"{variacion}\n\n"
        )

    hora_actual = datetime.now(ZONA_HORARIA).strftime('%Y-%m-%d %H:%M:%S')
    resumen += f"_Actualizado: {hora_actual}_"
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

@app.route("/")
def home():
    return "Bot monitor_criptos activo ✅"

@app.route("/resumen")
def resumen_manual():
    try:
        resumen = obtener_resumen_diario()
        enviar_mensaje(resumen)
        return "✅ Resumen enviado a Telegram manualmente"
    except Exception as e:
        return f"❌ Error al generar resumen: {e}"
