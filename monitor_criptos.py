import os
import requests
from flask import Flask
from datetime import datetime, timedelta
from supabase import create_client, Client
import numpy as np
from telegram import Bot

# Configuración
app = Flask(__name__)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
monedas = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "ADA": "cardano",
    "SHIB": "shiba-inu",
    "SOL": "solana"
}

# CoinGecko API para RSI
COINGECKO_URL = "https://api.coingecko.com/api/v3"

# Utilidades

def obtener_precios_y_rsi(simbolo):
    try:
        moneda_id = monedas[simbolo]
        vs_currency = "eur"
        days = 15
        url = f"{COINGECKO_URL}/coins/{moneda_id}/market_chart?vs_currency={vs_currency}&days={days}&interval=daily"
        r = requests.get(url)
        data = r.json()

        if 'prices' not in data:
            print(f"Quieto chato, no hagas huevadas: CoinGecko no devolvió 'prices' para {simbolo}")
            return None, None

        precios = [precio[1] for precio in data['prices']]
        if len(precios) < 15:
            print(f"No hay suficientes datos para calcular RSI de {simbolo}")
            return None, None

        precio_actual = precios[-1]
        rsi = calcular_rsi(np.array(precios))
        return precio_actual, rsi

    except Exception as e:
        print(f"Error al obtener precios/RSI para {simbolo}: {e}")
        return None, None

def calcular_rsi(data, period=14):
    if len(data) < period:
        return None
    delta = np.diff(data)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = np.convolve(gain, np.ones((period,)) / period, mode='valid')
    avg_loss = np.convolve(loss, np.ones((period,)) / period, mode='valid')
    if avg_loss[-1] == 0:
        return 100
    rs = avg_gain[-1] / avg_loss[-1]
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

def insertar_en_supabase(moneda, precio, rsi, fecha):
    try:
        if rsi is None:
            print(f"RSI nulo para {moneda}, no se insertará en Supabase.")
            return
        data = {
            "moneda": moneda,
            "precio": precio,
            "rsi": rsi,
            "fecha": fecha.isoformat()
        }
        respuesta = supabase.table("precios").insert(data).execute()
        if respuesta.data is None:
            raise Exception(respuesta.error)
    except Exception as e:
        print(f"Excepción al insertar en Supabase: {e}")

def enviar_alerta(moneda, precio, rsi):
    if rsi is None:
        return
    mensaje = f"\n📈 *{moneda}*\nPrecio actual: {precio:.8f} €\nRSI: {rsi}"
    if rsi < 30:
        mensaje += "\n🟢 Señal de *COMPRA* (RSI < 30)"
    elif rsi > 70:
        mensaje += "\n🔴 Señal de *VENTA* (RSI > 70)"
    Bot(token=TELEGRAM_TOKEN).send_message(chat_id=TELEGRAM_CHAT_ID, text=mensaje, parse_mode="Markdown")

def generar_y_enviar_resumen():
    resumen = []
    ahora = datetime.utcnow()

    for simbolo in monedas:
    precio, rsi = obtener_precios_y_rsi(simbolo)
    if precio is not None:
        insertar_en_supabase(simbolo, precio, rsi, ahora)
        enviar_alerta(simbolo, precio, rsi)
        resumen.append(f"{simbolo}: Precio={precio:.8f}€, RSI={rsi}")
    if resumen:
        mensaje = "\n📊 *Resumen Diario Cripto*\n" + "\n".join(resumen)
        Bot(token=TELEGRAM_TOKEN).send_message(chat_id=TELEGRAM_CHAT_ID, text=mensaje, parse_mode="Markdown")

@app.route("/")
def inicio():
    return "Bot Monitor Cripto Activo"

@app.route("/resumen")
def resumen():
    generar_y_enviar_resumen()
    return "Resumen generado y enviado"

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=10000)
