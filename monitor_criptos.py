import os
import requests
import hmac
import hashlib
import time

from flask import Flask
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client

# Configuración
app = Flask(__name__)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]

# Funciones auxiliares
def obtener_precios():
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    params = {"symbol": ",".join(MONEDAS), "convert": "EUR"}
    r = requests.get(url, headers=headers, params=params)
    data = r.json()["data"]
    precios = {}
    for m in MONEDAS:
        raw = data[m]["quote"]["EUR"]["price"]
        precio = round(raw, 8)  # Guardar hasta 8 decimales
        precios[m] = precio
    return precios

def obtener_rsi(moneda):
    # Mock RSI entre 30 y 70
    import random
    return round(random.uniform(30, 70), 2)

def consejo_rsi(rsi):
    if rsi > 70:
        return "🔴 RSI alto, quizá vender\n⚠️ Podría haber una bajada en el precio."
    elif rsi < 30:
        return "🟢 RSI bajo, quizá comprar\n📈 Podría rebotar pronto al alza."
    else:
        return "🟡 Estate quieto por ahora chato, no hagas huevadas"

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
    requests.post(url, data=data)


def insertar_en_supabase(nombre, precio, rsi, fecha):
    supabase.table("precios").insert({
        "nombre": nombre,
        "precio": precio,
        "rsi": rsi,
        "fecha": fecha.isoformat()
    }).execute()

def generar_y_enviar_resumen():
    precios = obtener_precios()
    from zoneinfo import ZoneInfo
    ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    resumen = "<b>📊 Resumen Manual de Criptomonedas</b>\n"

    for m in MONEDAS:
        precio = precios[m]
        rsi = obtener_rsi(m)
        insertar_en_supabase(m, precio, rsi, ahora)
        consejo = consejo_rsi(rsi)
        resumen += f"\n<b>{m}</b>: {precio:,.8f} €\nRSI: {rsi} → {consejo}\n"

    resumen += f"\n🗱️ Actualizado: {ahora.strftime('%d/%m %H:%M')} (Hora Europa)"
    enviar_telegram(resumen)

def obtener_ultimo_trade_real(trader_uid, moneda):
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    endpoint = "https://fapi.binance.com/fapi/v1/userTrades"
    
    timestamp = int(time.time() * 1000)
    params = {
        "symbol": f"{moneda}USDT",  # Ej: SOLUSDT
        "limit": 1,  # Solo el último trade
        "startTime": timestamp - 2592000000,  # Últimos 30 días
    }
    
    # Firma y llamada a la API
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    signature = hmac.new(api_secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    url = f"{endpoint}?{query_string}&signature={signature}"
    headers = {"X-MBX-APIKEY": api_key}
    
    try:
        response = requests.get(url, headers=headers)
        trades = response.json()
        if trades:
            ultimo_trade = trades[0]
            return {
                "moneda": moneda,
                "precio": float(ultimo_trade["price"]),
                "direccion": "LONG (Compra)" if ultimo_trade["isBuyer"] else "SHORT (Venta)",
                "comision": float(ultimo_trade["commission"]),
                "fecha": datetime.fromtimestamp(ultimo_trade["time"] / 1000)
            }
    except Exception as e:
        print(f"Error al obtener trades: {e}")
    return None

@app.route("/seguir_trader")
def seguir_trader():
    mensaje_telegram = "🔍 <b>Resumen de Movimientos Recientes</b>\n\n"
    
    for moneda in ["BTC", "SOL", "SHIB", "ADA"]:
        trader_uid = os.getenv(f"TRADER_{moneda}")
        if not trader_uid:
            continue
            
        trade = obtener_ultimo_trade_real(trader_uid, moneda)
        if trade:
            mensaje_telegram += (
                f"📢 <b>Última operación de TRADER_{moneda}</b>\n"
                f"💵 <b>Precio de {trade['direccion']}</b>: {trade['precio']:.2f} €\n"
                f"📅 <b>Fecha</b>: {trade['fecha'].strftime('%d/%m a las %H:%M')}\n"
                f"📊 <b>Comisión pagada</b>: {trade['comision']:.4f} {moneda}\n\n"
            )
            # Guardar en Supabase (sin TP/SL ya que no está en userTrades)
            supabase.table("trades_historico").insert({
                "trader_uid": trader_uid,
                "moneda": moneda,
                "direccion": trade["direccion"].split(" ")[0],  # LONG o SHORT
                "precio_entrada": trade["precio"],
                "fecha_apertura": trade["fecha"].isoformat(),
                "estado": "ACTIVO"
            }).execute()
        else:
            mensaje_telegram += f"❌ <b>TRADER_{moneda}</b>: Sin operaciones en los últimos 30 días\n\n"
    
    enviar_telegram(mensaje_telegram)
    return "Resumen enviado a Telegram"

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
