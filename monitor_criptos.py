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
def obtener_datos_trader(trader_uid, moneda):
    if not trader_uid:
        return None
    
    # Primero intentamos con el endpoint de posiciones actuales
    try:
        endpoint = "https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherPosition"
        params = {"encryptedUid": trader_uid, "tradeType": "PERPETUAL"}
        response = requests.post(endpoint, json=params)
        data = response.json()
        
        if data.get("data"):
            for posicion in data["data"]:
                if posicion["symbol"] == f"{moneda}USDT":
                    return {
                        "moneda": moneda,
                        "precio": float(posicion["entryPrice"]),
                        "direccion": "LONG (Compra)" if float(posicion["amount"]) > 0 else "SHORT (Venta)",
                        "fecha": datetime.fromtimestamp(posicion["updateTime"]/1000),
                        "origen": "posicion_actual"
                    }
    except Exception as e:
        print(f"Error en endpoint posiciones: {str(e)}")

    # Si no hay datos, intentamos con el endpoint de performance
    try:
        endpoint = "https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherPerformance"
        params = {"encryptedUid": trader_uid, "tradeType": "PERPETUAL"}
        response = requests.post(endpoint, json=params)
        data = response.json()
        
        if data.get("data"):
            for trade in data["data"]:
                if trade["symbol"] == f"{moneda}USDT":
                    return {
                        "moneda": moneda,
                        "precio": float(trade["entryPrice"]),
                        "direccion": "LONG (Compra)" if trade["amount"] > 0 else "SHORT (Venta)",
                        "fecha": datetime.fromtimestamp(trade["updateTime"]/1000),
                        "origen": "performance"
                    }
    except Exception as e:
        print(f"Error en endpoint performance: {str(e)}")

    # Último intento con endpoint de estadísticas
    try:
        endpoint = f"https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherLeaderboardBaseInfo?encryptedUid={trader_uid}"
        response = requests.get(endpoint)
        data = response.json()
        
        if data.get("data"):
            return {
                "moneda": moneda,
                "precio": None,
                "direccion": "Última operación",
                "fecha": datetime.fromtimestamp(data["data"]["lastTradeTime"]/1000) if data["data"]["lastTradeTime"] else None,
                "origen": "estadisticas"
            }
    except Exception as e:
        print(f"Error en endpoint estadísticas: {str(e)}")
    
    return None
# ==================
def generar_resumen_traders():
    mensaje = "<b>🔍 Resumen de Actividad de Traders</b>\n\n"
    traders_con_datos = False
    
    for moneda, trader_uid in TRADERS.items():
        if not trader_uid:
            continue
            
        datos = obtener_datos_trader(trader_uid, moneda)
        if datos:
            traders_con_datos = True
            mensaje += f"📊 <b>TRADER_{moneda}</b>\n"
            
            if datos["origen"] == "estadisticas" and datos["fecha"]:
                mensaje += f"⏰ Última operación: {datos['fecha'].strftime('%d/%m %H:%M')}\n"
            elif datos["precio"]:
                mensaje += f"💵 {datos['direccion']} a {datos['precio']:.2f} €\n"
                mensaje += f"⏰ {datos['fecha'].strftime('%d/%m %H:%M')}\n"
            
            mensaje += f"🔗 <a href='https://www.binance.com/es/copy-trading/lead-details/{trader_uid}'>Ver en Binance</a>\n\n"
            
            # Guardar en Supabase solo si tenemos datos completos
            if datos["precio"]:
                supabase.table("trades_historico").insert({
                    "trader_uid": trader_uid,
                    "moneda": moneda,
                    "direccion": datos["direccion"].split(" ")[0],
                    "precio_entrada": datos["precio"],
                    "fecha_apertura": datos["fecha"].isoformat(),
                    "estado": "ACTIVO"
                }).execute()
        else:
            mensaje += f"❌ TRADER_{moneda}: No se pudieron obtener datos\n\n"
    
    if not traders_con_datos:
        mensaje = "⚠️ No se encontraron datos recientes de los traders\n\n"
        mensaje += "Posibles razones:\n"
        mensaje += "- El trader no ha operado recientemente\n"
        mensaje += "- El perfil es privado\n"
        mensaje += "- Binance limita los datos públicos\n"
    
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
