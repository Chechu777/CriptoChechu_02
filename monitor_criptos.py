import os
import requests
from flask import Flask
from datetime import datetime
from supabase import create_client, Client
from zoneinfo import ZoneInfo
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

# --- Funciones RSI ---
def calcular_rsi(cierres: np.ndarray, periodo: int = 14) -> float:
    deltas = np.diff(cierres)
    ganancia = np.where(deltas > 0, deltas, 0)
    perdida = np.where(deltas < 0, -deltas, 0)
    media_ganancia = np.mean(ganancia[:periodo])
    media_perdida = np.mean(perdida[:periodo])
    if media_perdida == 0:
        return 100.0
    rs = media_ganancia / media_perdida
    return round(100 - (100 / (1 + rs)), 2)

def obtener_precios_historicos(nombre: str, dias: int = 15):
    try:
        response = supabase.table("precios")\
            .select("precio, fecha")\
            .eq("nombre", nombre)\
            .order("fecha", desc=True)\
            .limit(dias)\
            .execute()
        datos = response.data
        if not datos or len(datos) < dias:
            return None
        # Ordenar cronológicamente para RSI
        precios = [item["precio"] for item in reversed(datos)]
        return np.array(precios)
    except Exception as e:
        print(f"Error al obtener histórico {nombre}: {e}")
        return None

# --- Precios desde CoinMarketCap ---
def obtener_precios_actuales():
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    params = {"symbol": ",".join(MONEDAS), "convert": "EUR"}
    try:
        r = requests.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()["data"]
        precios = {}
        for m in MONEDAS:
            precios[m] = round(data[m]["quote"]["EUR"]["price"], 8)
        return precios
    except Exception as e:
        print(f"Error al obtener precios: {e}")
        return None

# --- Mensajes ---
def consejo_rsi(rsi):
    if rsi > 70:
        return "🔴 RSI alto, quizá vender\n⚠️ Podría bajar el precio."
    elif rsi < 30:
        return "🟢 RSI bajo, quizá comprar\n📈 Podría rebotar al alza."
    else:
        return "🟡 Quieto chato, no hagas huevadas"

def enviar_telegram(mensaje):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
        response = requests.post(url, data=data)
        response.raise_for_status()
    except Exception as e:
        print(f"Error al enviar Telegram: {e}")

def insertar_precio(nombre, precio, fecha, rsi=None):
    try:
        # Asegurar que la fecha tenga zona horaria Europe/Madrid
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=ZoneInfo("Europe/Madrid"))
        else:
            fecha = fecha.astimezone(ZoneInfo("Europe/Madrid"))

        # Formatear sin zona horaria, con microsegundos
        fecha_str = fecha.strftime("%Y-%m-%d %H:%M:%S.%f")

        supabase.table("precios").insert({
            "nombre": nombre,
            "precio": precio,
            "rsi": rsi,
            "fecha": fecha_str
        }).execute()
    except Exception as e:
        print(f"Error al insertar precio en Supabase: {e}")

# --- Generar resumen ---
def generar_resumen():
    precios_actuales = obtener_precios_actuales()
    if not precios_actuales:
        enviar_telegram("⚠️ No se pudieron obtener los precios actuales.")
        return False

    ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    mensaje = "<b>📊 Resumen Cripto Diario</b>\n\n"

    for moneda in MONEDAS:
        precio = precios_actuales[moneda]

        precios_historicos = obtener_precios_historicos(moneda)
        if precios_historicos is None or len(precios_historicos) < 15:
            rsi = None
            mensaje += f"{moneda}: {precio:,.8f} €\nℹ️ Calculando RSI... (más datos necesarios)\n\n"
        else:
            rsi = calcular_rsi(precios_historicos)
            mensaje += f"{moneda}: {precio:,.8f} €\n📈 RSI: {rsi} → {consejo_rsi(rsi)}\n\n"

        insertar_precio(moneda, precio, ahora, rsi)

    mensaje += f"🗓️ Actualizado: {ahora.strftime('%d/%m %H:%M')} (Hora Europa)"
    enviar_telegram(mensaje)
    return True

# --- Flask routes ---
@app.route("/")
def home():
    return "OK"

@app.route("/resumen")
def resumen():
    if generar_resumen():
        return "<h1>Resumen enviado a Telegram 📢</h1><p>Precios y RSI actualizados.</p>"
    else:
        return "<h1>Error al generar resumen</h1><p>Verifica logs.</p>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
