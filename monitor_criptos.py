import os
import requests
from flask import Flask
from datetime import datetime
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import hashlib

# Configuración
app = Flask(__name__)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]

# ======================== FUNCIONES GENERALES ========================

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
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
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

# ======================== FUNCIONES DE TRADERS ========================

def obtener_posicion_trader(lead_id):
    url = "https://www.binance.com/bapi/copy-trade/europe/v1/friendly/lead-copy-trade/lead-position"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    r = requests.post(url, headers=headers, json={"leadId": lead_id})
    if r.status_code != 200:
        return None
    return r.json()

def generar_hash_trade(data):
    cadena = f"{data['direction']}-{data['entryPrice']}-{data['symbol']}"
    return hashlib.sha256(cadena.encode()).hexdigest()

def obtener_ultimo_trade(moneda):
    res = supabase.table("trades_copytrading").select("*").eq("moneda", moneda).order("fecha", desc=True).limit(1).execute()
    if res.data:
        return res.data[0]
    return None

def insertar_trade_supabase(moneda, trader_id, datos, fecha, hash_trade):
    supabase.table("trades_copytrading").insert({
        "moneda": moneda,
        "trader_id": trader_id,
        "direccion": datos["direction"],
        "precio_entrada": datos["entryPrice"],
        "take_profit": datos.get("takeProfit"),
        "stop_loss": datos.get("stopLoss"),
        "fecha": fecha.isoformat(),
        "hash_trade": hash_trade
    }).execute()

def notificar_trade(moneda, trader_id, datos, fecha):
    mensaje = f"📢 <b>Movimiento detectado en TRADER_{moneda}</b>\n"
    mensaje += f"🔺 Dirección: <b>{datos['direction']}</b>\n"
    mensaje += f"💰 Precio entrada: <b>{datos['entryPrice']} €</b>\n"
    mensaje += f"🕒 Fecha: {fecha.strftime('%d/%m %H:%M')}\n"
    if datos.get("takeProfit"):
        mensaje += f"📈 Take Profit: {datos['takeProfit']} €\n"
    if datos.get("stopLoss"):
        mensaje += f"📉 Stop Loss: {datos['stopLoss']} €\n"
    enviar_telegram(mensaje)

# ======================== ENDPOINT NUEVO ========================

@app.route("/seguir_trader")
def seguir_trader():
    monedas_traders = {
        "BTC": os.getenv("TRADER_BTC"),
        "SOL": os.getenv("TRADER_SOL"),
        "ADA": os.getenv("TRADER_ADA"),
        "SHIB": os.getenv("TRADER_SHIB")
    }

    ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    movimientos_detectados = []

    for moneda, trader_id in monedas_traders.items():
        if not trader_id:
            continue

        datos = obtener_posicion_trader(trader_id)
        if not datos or not datos.get("data"):
            continue

        posiciones = datos["data"].get("positionVos", [])
        if not posiciones:
            continue

        for pos in posiciones:
            if moneda not in pos["symbol"]:
                continue

            hash_actual = generar_hash_trade(pos)
            ultimo = obtener_ultimo_trade(moneda)

            if not ultimo or hash_actual != ultimo.get("hash_trade"):
                insertar_trade_supabase(moneda, trader_id, pos, ahora, hash_actual)
                notificar_trade(moneda, trader_id, pos, ahora)
                movimientos_detectados.append(moneda)

    return f"<h1>✔ Seguimiento completado</h1><p>Movimientos detectados en: {', '.join(movimientos_detectados) if movimientos_detectados else 'ninguno'}.</p>"

# ======================== ENDPOINTS EXISTENTES ========================

@app.route("/")
def home():
    return "OK"

@app.route("/resumen")
def resumen():
    generar_y_enviar_resumen()
    return "<h1>Resumen enviado a Telegram 📢</h1><p>También guardado en Supabase.</p>"

# ======================== MAIN ========================

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
