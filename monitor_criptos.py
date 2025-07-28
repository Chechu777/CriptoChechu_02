import os
import requests
from flask import Flask
from datetime import datetime
from supabase import create_client, Client

# Configuración
app = Flask(__name__)

# Conexión a Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Config Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ==============================================
# Funciones principales
# ==============================================

def enviar_telegram(mensaje):
    """Envía mensajes a Telegram con formato HTML"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "HTML"
    }
    requests.post(url, data=data)

def obtener_trades_publicos(trader_uid, moneda):
    """Consulta los trades públicos de un trader usando la API de Binance Copy Trading"""
    endpoint = "https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherPosition"
    params = {
        "encryptedUid": trader_uid,
        "tradeType": "PERPETUAL"  # Para contratos perpetuos
    }
    
    try:
        response = requests.post(endpoint, json=params)
        data = response.json()
        
        if data and "data" in data and data["data"]:
            # Procesamos la posición más reciente
            ultima_posicion = data["data"][0]
            return {
                "moneda": ultima_posicion["symbol"].replace("USDT", ""),
                "direccion": "LONG (Compra)" if float(ultima_posicion["amount"]) > 0 else "SHORT (Venta)",
                "precio": float(ultima_posicion["entryPrice"]),
                "tamaño": float(ultima_posicion["amount"]),
                "fecha": datetime.fromtimestamp(ultima_posicion["updateTime"] / 1000)
            }
    except Exception as e:
        print(f"Error al consultar trades: {e}")
    return None

# ==============================================
# Endpoints Flask
# ==============================================

@app.route("/")
def home():
    return "Bot de Monitoreo de Cripto - /seguir_trader para actualizar"

@app.route("/seguir_trader")
def seguir_trader():
    """Endpoint principal que consulta y notifica trades"""
    mensaje_telegram = "🔍 <b>Resumen de Movimientos de Traders</b>\n\n"
    
    # Lista de monedas a verificar (solo aquellas con traders definidos)
    monedas_a_verificar = []
    for moneda in ["BTC", "SOL", "SHIB", "ADA"]:
        trader_uid = os.getenv(f"TRADER_{moneda}")
        if trader_uid and trader_uid.strip():  # Filtra traders vacíos
            monedas_a_verificar.append((moneda, trader_uid))
    
    if not monedas_a_verificar:
        enviar_telegram("⚠️ No hay traders configurados en las variables de entorno.")
        return "No hay traders configurados"
    
    # Procesamos cada trader
    for moneda, trader_uid in monedas_a_verificar:
        try:
            trade = obtener_trades_publicos(trader_uid, moneda)
            if trade:
                mensaje_telegram += (
                    f"📢 <b>Última operación de TRADER_{moneda}</b>\n"
                    f"➡️ <b>Dirección</b>: {trade['direccion']}\n"
                    f"💰 <b>Precio entrada</b>: {trade['precio']:.4f} $\n"
                    f"📊 <b>Tamaño posición</b>: {abs(trade['tamaño']):.2f} {moneda}\n"
                    f"⏰ <b>Actualizado</b>: {trade['fecha'].strftime('%d/%m %H:%M')}\n\n"
                )
                
                # Guardamos en Supabase
                supabase.table("trades_historico").insert({
                    "trader_uid": trader_uid,
                    "moneda": moneda,
                    "direccion": trade["direccion"].split(" ")[0],
                    "precio_entrada": trade["precio"],
                    "tamaño_posicion": trade["tamaño"],
                    "fecha_apertura": trade["fecha"].isoformat(),
                    "estado": "ACTIVO"
                }).execute()
            else:
                mensaje_telegram += f"❌ <b>TRADER_{moneda}</b>: Sin operaciones activas\n\n"
        except Exception as e:
            mensaje_telegram += f"⚠️ <b>Error con TRADER_{moneda}</b>: {str(e)}\n\n"
    
    # Enviamos el resumen completo
    enviar_telegram(mensaje_telegram)
    return "Resumen enviado a Telegram"

# ==============================================
# Ejecución
# ==============================================

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
