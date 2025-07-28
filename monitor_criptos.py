import os
import requests
from flask import Flask
from datetime import datetime
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np

# Configuración
app = Flask(__name__)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]

# Obtener datos desde CoinMarketCap

def obtener_datos_mercado():
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    params = {"symbol": ",".join(MONEDAS), "convert": "EUR"}
    r = requests.get(url, headers=headers, params=params)
    data = r.json()["data"]

    resultados = {}
    for m in MONEDAS:
        quote = data[m]["quote"]["EUR"]
        resultados[m] = {
            "precio": round(quote["price"], 8),
            "cambio_24h": round(quote["percent_change_24h"], 2),
            "volumen_24h": round(quote["volume_24h"], 2)
        }
    return resultados

# Calcular RSI real desde CoinGecko

def obtener_rsi(moneda, intervalo="1h", periodo=14):
    mapping = {"BTC": "bitcoin", "ETH": "ethereum", "ADA": "cardano", "SHIB": "shiba-inu", "SOL": "solana"}
    if moneda not in mapping:
        return None
    coingecko_id = mapping[moneda]
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{coingecko_id}/market_chart?vs_currency=eur&days=2&interval=hourly"
        response = requests.get(url)
        datos = response.json()["prices"][-(periodo+1):]
        cierres = [precio[1] for precio in datos]
        serie = pd.Series(cierres)
        delta = serie.diff().dropna()
        ganancia = delta.where(delta > 0, 0.0)
        perdida = -delta.where(delta < 0, 0.0)
        media_gan = ganancia.rolling(window=periodo).mean()
        media_per = perdida.rolling(window=periodo).mean()
        rs = media_gan / media_per
        rsi = 100 - (100 / (1 + rs))
        return round(rsi.iloc[-1], 2) if not rsi.empty else None
    except Exception as e:
        print(f"Error al obtener RSI para {moneda}: {str(e)}")
        return None

# Generar consejo según RSI

def consejo_rsi(rsi):
    if rsi is None:
        return "❓ RSI no disponible"
    elif rsi > 70:
        return "🔴 RSI alto, quizá vender\n⚠️ Podría haber una bajada."
    elif rsi < 30:
        return "🟢 RSI bajo, quizá comprar\n📈 Podría rebotar."
    else:
        return "🟡 RSI neutro, espera."

# Recomendación de precio objetivo

def recomendacion_precio(nombre, precio, rsi):
    if rsi is None:
        return "❓ Sin recomendación por falta de datos."
    elif rsi < 30:
        objetivo = round(precio * 1.06, 8)
        return f"💡 Podrías poner una orden de <b>venta</b> si el precio sube a {objetivo:.8f} €."
    elif rsi > 70:
        objetivo = round(precio * 0.94, 8)
        return f"💡 Podrías poner una orden de <b>compra</b> si el precio baja a {objetivo:.8f} €."
    else:
        return "ℹ️ No se recomienda colocar orden especulativa ahora."

# Lógica automatizada de alerta

def alerta_estrategica(nombre, rsi, precio):
    if rsi is None:
        return None
    if rsi < 30:
        return f"🟢 <b>Señal de COMPRA detectada en {nombre}</b>\nPrecio: {precio} € | RSI: {rsi}"
    elif rsi > 70:
        return f"🔴 <b>Señal de VENTA detectada en {nombre}</b>\nPrecio: {precio} € | RSI: {rsi}"
    return None

# Enviar mensaje a Telegram

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
    requests.post(url, data=data)

# Guardar en Supabase

def insertar_en_supabase(nombre, precio, rsi, fecha):
    try:
        hora_madrid = fecha.astimezone(ZoneInfo("Europe/Madrid")) if fecha.tzinfo else fecha.replace(tzinfo=ZoneInfo("Europe/Madrid"))
        fecha_formateada = hora_madrid.strftime('%Y-%m-%d %H:%M:%S.%f')
        response = supabase.table("precios").insert({
            "nombre": nombre,
            "precio": precio,
            "rsi": rsi,
            "fecha": fecha_formateada
        }).execute()
        if hasattr(response, 'error') and response.error:
            print(f"Error insertando en Supabase: {response.error}")
    except Exception as e:
        print(f"Excepción al insertar en Supabase: {str(e)}")
        raise

# Generar y enviar resumen

def generar_y_enviar_resumen():
    datos = obtener_datos_mercado()
    ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    resumen = "<b>📊 Resumen Cripto Diario</b>\n"

    for m in MONEDAS:
        precio = datos[m]["precio"]
        cambio = datos[m]["cambio_24h"]
        volumen = datos[m]["volumen_24h"]
        rsi = obtener_rsi(m)
        insertar_en_supabase(m, precio, rsi, ahora)
        consejo = consejo_rsi(rsi)
        recomendacion = recomendacion_precio(m, precio, rsi)

        resumen += (
            f"\n<b>{m}</b>: {precio:,.8f} €\n"
            f"🔄 Cambio 24h: {cambio}%\n"
            f"📊 Volumen: {volumen:,.0f} €\n"
            f"📈 RSI: {rsi} → {consejo}\n"
            f"{recomendacion}\n"
        )

        # Enviar alerta automatizada si aplica
        alerta = alerta_estrategica(m, rsi, precio)
        if alerta:
            enviar_telegram(alerta)

    resumen += f"\n🕒 Actualizado: {ahora.strftime('%d/%m %H:%M')} (Hora Europa)"
    enviar_telegram(resumen)

# Rutas
@app.route("/")
def home():
    return "OK"

@app.route("/resumen")
def resumen():
    generar_y_enviar_resumen()
    return "<h1>Resumen enviado a Telegram 📢</h1><p>También guardado en Supabase.</p>"

# Ejecutar
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
