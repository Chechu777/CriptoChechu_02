import os
import requests
from flask import Flask
from datetime import datetime, timezone
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import random

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
        precio = round(raw, 8)
        precios[m] = precio
    return precios

def obtener_rsi(moneda):
    return round(random.uniform(30, 70), 2)

def consejo_rsi(rsi):
    if rsi > 70:
        return "🔴 RSI alto, quizá vender\n⚠️ Podría haber una bajada en el precio."
    elif rsi < 30:
        return "🟢 RSI bajo, quizá comprar\n📈 Podría rebotar pronto al alza."
    else:
        return "🟡 Quieto chato, no hagas huevadas"

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

def obtener_trades_trader(trader_uid, moneda):
    if not trader_uid:
        return None
        
    endpoint = "https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherPosition"
    params = {
        "encryptedUid": trader_uid,
        "tradeType": "PERPETUAL"
    }
    
    try:
        response = requests.post(endpoint, json=params)
        data = response.json()
        
        if data and "data" in data and data["data"]:
            ultima_posicion = data["data"][0]
            return {
                "moneda": moneda,
                "precio": float(ultima_posicion["entryPrice"]),
                "direccion": "LONG (Compra)" if float(ultima_posicion["amount"]) > 0 else "SHORT (Venta)",
                "fecha": datetime.fromtimestamp(ultima_posicion["updateTime"] / 1000)
            }
    except Exception as e:
        print(f"Error al obtener trades: {e}")
    return None

def generar_y_enviar_resumen():
    precios = obtener_precios()
    ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    resumen = "<b>📊 Resumen de Criptomonedas</b>\n"

    for m in MONEDAS:
        precio = precios[m]
        rsi = obtener_rsi(m)
        insertar_en_supabase(m, precio, rsi, ahora)
        consejo = consejo_rsi(rsi)
        resumen += f"\n<b>{m}</b>: {precio:,.8f} €\nRSI: {rsi} → {consejo}\n"

    resumen += f"\n🗱️ Actualizado: {ahora.strftime('%d/%m %H:%M')} (Hora Europa)"
    enviar_telegram(resumen)

def generar_resumen_traders():
    mensaje = "<b>🔍 Movimientos de Traders</b>\n\n"
    
    for moneda, trader_uid in TRADERS.items():
        if not trader_uid:
            continue
            
        trade = obtener_trades_trader(trader_uid, moneda)
        if trade:
            mensaje += (
                f"📢 <b>TRADER_{moneda}</b>\n"
                f"💵 {trade['direccion']}: {trade['precio']:.2f} €\n"
                f"📅 {trade['fecha'].strftime('%d/%m %H:%M')}\n\n"
            )
            
            supabase.table("trades_historico").insert({
                "trader_uid": trader_uid,
                "moneda": moneda,
                "direccion": trade["direccion"].split(" ")[0],
                "precio_entrada": trade["precio"],
                "fecha_apertura": trade["fecha"].isoformat(),
                "estado": "ACTIVO"
            }).execute()
        else:
            mensaje += f"❌ TRADER_{moneda}: Sin movimientos recientes\n\n"
    
    if mensaje.count("📢") == 0:
        mensaje = "⚠️ No hay movimientos de traders para mostrar"
    
    enviar_telegram(mensaje)

# Rutas
@app.route("/")
def home():
    return "OK"

@app.route("/resumen")
def resumen():
    generar_y_enviar_resumen()
    return "<h1>Resumen enviado a Telegram 📢</h1>"

@app.route("/traders")
def traders():
    generar_resumen_traders()
    return "<h1>Resumen de traders enviado 📊</h1>"

# Ejecutar
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
