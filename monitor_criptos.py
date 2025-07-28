import os
import requests
from flask import Flask
from datetime import datetime
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

COINGECKO_URL = "https://api.coingecko.com/api/v3"

def obtener_datos_completos(simbolo):
    """
    Obtiene precio actual, cambio 24h, volumen 24h y lista de precios para RSI.
    """
    try:
        moneda_id = monedas[simbolo]
        url_market = f"{COINGECKO_URL}/coins/{moneda_id}"
        r = requests.get(url_market)
        data = r.json()

        market_data = data.get("market_data", {})
        if not market_data:
            print(f"Quieto chato, no hay datos de mercado para {simbolo}")
            return None, None, None, None

        precio = market_data.get("current_price", {}).get("eur")
        cambio_24h = market_data.get("price_change_percentage_24h")
        volumen_24h = market_data.get("total_volume", {}).get("eur")

        # Obtener precios para RSI (últimos 15 días, diario)
        url_chart = f"{COINGECKO_URL}/coins/{moneda_id}/market_chart?vs_currency=eur&days=15&interval=daily"
        r_chart = requests.get(url_chart)
        data_chart = r_chart.json()

        if "prices" not in data_chart:
            print(f"Quieto chato, no hay 'prices' para {simbolo}")
            return precio, cambio_24h, volumen_24h, None

        precios = [p[1] for p in data_chart["prices"]]
        if len(precios) < 15:
            print(f"No hay suficientes datos para RSI de {simbolo}")
            return precio, cambio_24h, volumen_24h, None

        return precio, cambio_24h, volumen_24h, precios

    except Exception as e:
        print(f"Error al obtener datos para {simbolo}: {e}")
        return None, None, None, None

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

def mensaje_rsi(rsi):
    if rsi is None:
        return "❓ Sin RSI"
    if rsi < 30:
        return "🟢 Señal de COMPRA"
    elif rsi > 70:
        return "🔴 Señal de VENTA"
    else:
        return "🟡 Quieto chato, no hagas huevadas"

def formato_numero(n):
    # Formatea números con separador de miles y 2 decimales, o más si es menor que 1
    if n is None:
        return "N/A"
    if n < 1:
        return f"{n:.8f}"
    else:
        return f"{n:,.2f}"

def enviar_alerta(moneda, precio, cambio_24h, volumen_24h, rsi):
    if precio is None or rsi is None:
        return
    texto = (
        f"\n*{moneda}*: {formato_numero(precio)} €\n"
        f"🔄 Cambio 24h: {formato_numero(cambio_24h)} %\n"
        f"📊 Volumen 24h: {formato_numero(volumen_24h)} €\n"
        f"📈 RSI: {rsi} → {mensaje_rsi(rsi)}"
    )
    Bot(token=TELEGRAM_TOKEN).send_message(chat_id=TELEGRAM_CHAT_ID, text=texto, parse_mode="Markdown")

def generar_y_enviar_resumen():
    resumen = []
    ahora = datetime.utcnow()

    for simbolo in monedas:
        precio, cambio_24h, volumen_24h, precios = obtener_datos_completos(simbolo)
        if precios is not None:
            rsi = calcular_rsi(np.array(precios))
        else:
            rsi = None

        if precio is not None:
            insertar_en_supabase(simbolo, precio, rsi, ahora)
            enviar_alerta(simbolo, precio, cambio_24h, volumen_24h, rsi)
            resumen.append(f"{simbolo}: Precio={formato_numero(precio)} €, RSI={rsi}")

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
