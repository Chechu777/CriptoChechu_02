import os
import requests
from flask import Flask
from datetime import datetime, timezone
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import random

# ================ CONFIGURACIÓN ================ 
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

# ================ Funciones auxiliares ================
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

# ==============VER_TRADERS=================
def obtener_trades_trader(trader_uid, moneda):
    if not trader_uid:
        return None
        
    # Endpoint alternativo para datos públicos
    endpoint = "https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherPosition"
    params = {
        "encryptedUid": trader_uid,
        "tradeType": "PERPETUAL"
    }
    
    try:
        response = requests.post(endpoint, json=params)
        data = response.json()
        
        if data and "data" in data and data["data"]:
            # Obtener posición más reciente
            ultima_posicion = data["data"][0]
            return {
                "moneda": ultima_posicion["symbol"].replace("USDT", ""),
                "precio": float(ultima_posicion["entryPrice"]),
                "direccion": "LONG (Compra)" if float(ultima_posicion["amount"]) > 0 else "SHORT (Venta)",
                "fecha": datetime.fromtimestamp(ultima_posicion["updateTime"] / 1000)
            }
    except Exception as e:
        print(f"Error al consultar trader {trader_uid}: {str(e)}")
    
    # Si falla, intentar con endpoint alternativo
    try:
        endpoint_alt = "https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherPerformance"
        response = requests.post(endpoint_alt, json={"encryptedUid": trader_uid})
        data = response.json()
        
        if data and "data" in data and data["data"]:
            ultimo_trade = data["data"][0]
            return {
                "moneda": moneda,
                "precio": float(ultimo_trade["entryPrice"]),
                "direccion": "LONG (Compra)" if ultimo_trade["amount"] > 0 else "SHORT (Venta)",
                "fecha": datetime.fromtimestamp(ultimo_trade["updateTime"] / 1000)
            }
    except Exception as e:
        print(f"Error en endpoint alternativo: {str(e)}")
    
    return None
# ==================
def generar_resumen_traders():
    mensaje = "<b>🔍 Últimos Movimientos de Traders</b>\n\n"
    traders_con_datos = False
    
    for moneda, trader_uid in TRADERS.items():
        if not trader_uid:
            continue
            
        trade = obtener_trades_trader(trader_uid, moneda)
        if trade:
            traders_con_datos = True
            mensaje += (
                f"📊 <b>TRADER_{moneda}</b>\n"
                f"💵 {trade['direccion']} a {trade['precio']:.2f} €\n"
                f"⏰ {trade['fecha'].strftime('%d/%m %H:%M')}\n"
            )
            
            # Solo mostrar si es el trader de SOL (BTC es privado)
            if moneda == "SOL":
                mensaje += f"🔗 <a href='https://www.binance.com/es/copy-trading/lead-details/{trader_uid}'>Ver en Binance</a>\n"
            
            mensaje += "\n"
            
            # Guardar en Supabase
            supabase.table("trades_historico").insert({
                "trader_uid": trader_uid,
                "moneda": moneda,
                "direccion": trade["direccion"].split(" ")[0],
                "precio_entrada": trade["precio"],
                "fecha_apertura": trade["fecha"].isoformat(),
                "estado": "ACTIVO"
            }).execute()
        else:
            mensaje += f"❌ TRADER_{moneda}: Datos no disponibles (puede ser privado)\n\n"
    
    if not traders_con_datos:
        mensaje = "⚠️ No se pudieron obtener datos de ningún trader (pueden ser perfiles privados)"
    
    enviar_telegram(mensaje)
# ===============================
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
