import os
import requests
from flask import Flask
from datetime import datetime
from supabase import create_client, Client
import numpy as np
from telegram import Bot
import pytz
from cryptocompare import get_coin_ohlcv_historical

# Configuración
app = Flask(__name__)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

monedas = {
    "BTC": 1,
    "ETH": 1027,
    "ADA": 2010,
    "SHIB": 5994,
    "SOL": 5426
}

def calcular_rsi(precios: np.ndarray, periodo: int = 14) -> float | None:
    if len(precios) < periodo + 1:
        return None
    delta = np.diff(precios)
    ganancia = np.where(delta > 0, delta, 0)
    perdida = np.where(delta < 0, -delta, 0)

    media_ganancia = np.mean(ganancia[:periodo])
    media_perdida = np.mean(perdida[:periodo])

    if media_perdida == 0:
        return 100.0

    rs = media_ganancia / media_perdida
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

def obtener_rsi(simbolo: str, dias: int = 15) -> float | None:
    try:
        respuesta = get_coin_ohlcv_historical(
            simbolo,
            currency="EUR",
            exchange="CCCAGG",
            limit=dias - 1  # Devuelve `limit+1` datos
        )
        if not respuesta or not respuesta.data:
            print(f"⚠️ No se encontraron datos históricos para {simbolo}")
            return None
        cierres = [dia["close"] for dia in respuesta.data if "close" in dia]
        if len(cierres) < dias:
            print(f"⚠️ Datos insuficientes para RSI de {simbolo}")
            return None
        return calcular_rsi(np.array(cierres))
    except Exception as e:
        print(f"❌ Error al obtener RSI para {simbolo}: {e}")
        return None

def insertar_en_supabase(moneda, precio, rsi, cambio_24h, volumen_24h, fecha):
    try:
        data = {
            "moneda": moneda,
            "precio": precio,
            "rsi": rsi,
            "cambio_24h": cambio_24h,
            "volumen_24h": volumen_24h,
            "fecha": fecha.isoformat()
        }
        supabase.table("precios").insert(data).execute()
    except Exception as e:
        print(f"Error al insertar en Supabase para {moneda}: {e}")

def formato_numero(valor):
    if valor is None:
        return "None"
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def mensaje_rsi(rsi):
    if rsi is None:
        return "❓ Sin RSI"
    elif rsi < 30:
        return "🟢 Posible compra"
    elif rsi > 70:
        return "🔴 Posible venta"
    else:
        return "🟡 Quieto chato, no hagas huevadas"

def obtener_datos_completos(simbolo):
    try:
        id_cmc = monedas[simbolo]
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        headers = {
            "X-CMC_PRO_API_KEY": CMC_API_KEY,
            "Accepts": "application/json"
        }
        params = {
            "id": id_cmc,
            "convert": "EUR"
        }
        r = requests.get(url, headers=headers, params=params)
        data = r.json()

        info = data["data"][str(id_cmc)]["quote"]["EUR"]
        precio = info.get("price")
        cambio_24h = info.get("percent_change_24h")
        volumen_24h = info.get("volume_24h")

        return precio, cambio_24h, volumen_24h
    except Exception as e:
        print(f"Error al obtener datos para {simbolo}: {e}")
        return None, None, None

def generar_y_enviar_resumen():
    resumen = []
    ahora = datetime.now(pytz.timezone("Europe/Madrid"))

    for simbolo in monedas:
        precio, cambio_24h, volumen_24h = obtener_datos_completos(simbolo)
        rsi = obtener_rsi(simbolo)

        if precio is not None:
            insertar_en_supabase(simbolo, precio, rsi, cambio_24h, volumen_24h, ahora)
            resumen.append(
                f"{simbolo}: {formato_numero(precio)} €\n"
                f"🔄 Cambio 24h: {formato_numero(cambio_24h)} %\n"
                f"📊 Volumen: {formato_numero(volumen_24h)} €\n"
                f"📈 RSI: {rsi if rsi is not None else 'None'} → {mensaje_rsi(rsi)}"
            )

    if resumen:
        mensaje = "📊 Resumen Cripto Diario\n\n" + "\n\n".join(resumen)
        Bot(token=TELEGRAM_TOKEN).send_message(chat_id=TELEGRAM_CHAT_ID, text=mensaje)

@app.route("/")
def inicio():
    return "Bot Monitor Cripto Activo"

@app.route("/resumen")
def resumen():
    generar_y_enviar_resumen()
    return "Resumen generado y enviado"

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=10000)
