import os
import requests
from flask import Flask
from datetime import datetime, timezone
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import random
import numpy as np
from cryptocompare import get_coin_ohlcv_historical

# Configuración
app = Flask(__name__)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]
TRADERS = {
    "BTC": os.getenv("TRADER_BTC"),
    "SOL": os.getenv("TRADER_SOL"),
    "SHIB": os.getenv("TRADER_SHIB"),
    "ADA": os.getenv("TRADER_ADA")
}

# Configuración de headers para evitar bloqueos
BINANCE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.binance.com/"
}

# --- Cálculo RSI ---
def calcular_rsi(cierres: np.ndarray, periodo: int = 14) -> float:
    delta = np.diff(cierres)
    ganancia = np.where(delta > 0, delta, 0)
    perdida = np.where(delta < 0, -delta, 0)
    media_ganancia = np.mean(ganancia[:periodo])
    media_perdida = np.mean(perdida[:periodo])
    if media_perdida == 0:
        return 100.0
    rs = media_ganancia / media_perdida
    return round(100 - (100 / (1 + rs)), 2)

def obtener_rsi(simbolo: str, dias: int = 15) -> float | None:
    try:
        respuesta = get_coin_ohlcv_historical(
            simbolo,
            currency="EUR",
            exchange="CCCAGG",
            limit=dias - 1
        )

        if not respuesta or not hasattr(respuesta, 'data') or not isinstance(respuesta.data, list):
            print(f"⚠️ Respuesta inválida de CryptoCompare para {simbolo}")
            return None

        cierres = [dia["close"] for dia in respuesta.data if "close" in dia]
        if len(cierres) < dias:
            print(f"⚠️ Datos insuficientes para RSI de {simbolo}")
            return None

        return calcular_rsi(np.array(cierres))

    except Exception as e:
        print(f"❌ Error al obtener RSI para {simbolo}: {e}")
        return None

# --- Precios desde CoinMarketCap ---
def obtener_precios():
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    params = {"symbol": ",".join(MONEDAS), "convert": "EUR"}

    try:
        r = requests.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()["data"]
        precios = {}
        for m in MONEDAS:
            raw = data[m]["quote"]["EUR"]["price"]
            precio = round(raw, 8)
            precios[m] = precio
        return precios
    except Exception as e:
        print(f"Error al obtener precios: {str(e)}")
        return None

# --- Auxiliares ---
def consejo_rsi(rsi):
    if rsi > 70:
        return "🔴 RSI alto, quizá vender\n⚠️ Podría haber una bajada en el precio."
    elif rsi < 30:
        return "🟢 RSI bajo, quizá comprar\n📈 Podría rebotar pronto al alza."
    else:
        return "🟡 Quieto chato, no hagas huevadas"

def enviar_telegram(mensaje):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
        response = requests.post(url, data=data)
        response.raise_for_status()
    except Exception as e:
        print(f"Error al enviar mensaje a Telegram: {str(e)}")

def insertar_en_supabase(nombre, precio, rsi, fecha):
    try:
        supabase.table("precios").insert({
            "nombre": nombre,
            "precio": precio,
            "rsi": rsi,
            "fecha": fecha.isoformat()
        }).execute()
    except Exception as e:
        print(f"Error al insertar en Supabase: {str(e)}")

def generar_resumen_criptos():
    precios = obtener_precios()
    if not precios:
        enviar_telegram("⚠️ No se pudieron obtener los precios de las criptomonedas")
        return False

    ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    resumen = "<b>📊 Resumen de Criptomonedas</b>\n"

    for m in MONEDAS:
        precio = precios[m]
        rsi = obtener_rsi(m)
        if rsi is None:
            print(f"RSI nulo para {m}, no se insertará en Supabase.")
            continue
        insertar_en_supabase(m, precio, rsi, ahora)
        consejo = consejo_rsi(rsi)
        resumen += f"\n<b>{m}</b>: {precio:,.8f} €\nRSI: {rsi} → {consejo}\n"

    resumen += f"\n🗱️ Actualizado: {ahora.strftime('%d/%m %H:%M')} (Hora Europa)"
    enviar_telegram(resumen)
    return True

def obtener_datos_trader_web(trader_uid, moneda):
    try:
        url = f"https://www.binance.com/es/copy-trading/lead-details/{trader_uid}?timeRange=7D"
        response = requests.get(url, headers=BINANCE_HEADERS)
        response.raise_for_status()
        if "Última operación" in response.text:
            return {
                "moneda": moneda,
                "precio": None,
                "direccion": "Datos en página web",
                "fecha": datetime.now(),
                "origen": "web_scraping"
            }
    except Exception as e:
        print(f"Error en scraping web: {str(e)}")
    return None

def generar_resumen_traders():
    mensaje = "<b>📊 Actividad Reciente de Traders</b>\n\n"
    traders_con_datos = False

    for moneda, trader_uid in TRADERS.items():
        if not trader_uid:
            continue

        datos = obtener_datos_trader(trader_uid, moneda)
        if not datos:
            datos = obtener_datos_trader_web(trader_uid, moneda)

        if datos:
            traders_con_datos = True
            mensaje += f"📊 <b>TRADER_{moneda}</b>\n"
            mensaje += f"🔗 <a href='https://www.binance.com/es/copy-trading/lead-details/{trader_uid}'>Ver en Binance</a>\n\n"
        else:
            mensaje += f"❌ TRADER_{moneda}: No se pudieron obtener datos\n\n"

    if not traders_con_datos:
        mensaje += "ℹ️ <i>Los datos de traders solo están disponibles consultando manualmente los enlaces</i>"

    enviar_telegram(mensaje)

@app.route("/")
def home():
    return "OK"

@app.route("/resumen")
def resumen():
    if generar_resumen_criptos():
        return "<h1>Resumen enviado a Telegram 📢</h1><p>Precios y RSI actualizados</p>"
    else:
        return "<h1>Error al generar resumen</h1><p>Verifica los logs para más información</p>"

@app.route("/traders")
def traders():
    generar_resumen_traders()
    return "<h1>Resumen de traders enviado 📊</h1><p>Consulta Telegram para los detalles</p>"

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
