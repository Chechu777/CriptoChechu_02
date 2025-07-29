import os
import requests
from flask import Flask
from datetime import datetime
from supabase import create_client, Client
import numpy as np
from telegram import Bot
import pytz
from zoneinfo import ZoneInfo

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

def obtener_precios_historicos(moneda, dias=15):
    try:
        response = (
            supabase
            .table("precios")
            .select("precio")
            .eq("moneda", moneda)
            .order("fecha", desc=True)
            .limit(dias)
            .execute()
        )
        if response.error or not response.data:
            print(f"No se encontraron datos históricos para {moneda}: {response.error}")
            return None

        # Obtener precios en orden ascendente (del más antiguo al más reciente)
        precios = [entry["precio"] for entry in reversed(response.data)]
        if len(precios) < dias:
            print(f"Datos insuficientes para RSI de {moneda}: solo {len(precios)} días")
            return None
        return precios

    except Exception as e:
        print(f"Error al obtener precios históricos para {moneda}: {e}")
        return None

def obtener_datos_completos(simbolo):
    try:
        id_cmc = monedas[simbolo]

        url_simple = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        headers = {
            "X-CMC_PRO_API_KEY": CMC_API_KEY,
            "Accepts": "application/json"
        }
        params = {
            "id": id_cmc,
            "convert": "EUR"
        }
        r = requests.get(url_simple, headers=headers, params=params)
        data = r.json()
        print(f"Respuesta CMC para {simbolo}:", data)

        info = data["data"][str(id_cmc)]["quote"]["EUR"]
        precio = info.get("price")
        cambio_24h = info.get("percent_change_24h")
        volumen_24h = info.get("volume_24h")

        precios = obtener_precios_historicos(simbolo)

        return precio, cambio_24h, volumen_24h, precios

    except Exception as e:
        print(f"Error al obtener datos para {simbolo}: {e}")
        return None, None, None, None

def generar_y_enviar_resumen():
    resumen = []
    ahora = datetime.now(pytz.timezone("Europe/Madrid"))

    for simbolo in monedas:
        precio, cambio_24h, volumen_24h, _ = obtener_datos_completos(simbolo)
        precios = obtener_precios_historicos(simbolo)
        if precios is not None:
            rsi = calcular_rsi(np.array(precios))
        else:
            rsi = None

        if precio is not None:
            insertar_en_supabase(simbolo, precio, rsi, cambio_24h, volumen_24h, ahora)
            resumen.append(
                f"{simbolo}: {formato_numero(precio)} €\n"
                f"🔄 Cambio 24h: {formato_numero(cambio_24h)} %\n"
                f"📊 Volumen: {formato_numero(volumen_24h)} €\n"
                f"📈 RSI: {rsi} → {mensaje_rsi(rsi)}"
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
