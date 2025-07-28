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
        insertar_en_supabase(m, precio, rsi, ahora)
        consejo = consejo_rsi(rsi)
        resumen += f"\n<b>{m}</b>: {precio:,.8f} €\nRSI: {rsi} → {consejo}\n"

    resumen += f"\n🗱️ Actualizado: {ahora.strftime('%d/%m %H:%M')} (Hora Europa)"
    enviar_telegram(resumen)
    return True

# ============== FUNCIONES DE TRADERS ==============
def obtener_datos_trader(trader_uid, moneda):
    if not trader_uid:
        return None
    
    # 1. Primero intentamos con la API de rendimiento
    try:
        endpoint = "https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherPerformance"
        params = {
            "encryptedUid": trader_uid,
            "tradeType": "PERPETUAL",
            "statisticsType": "ALL"
        }
        response = requests.post(endpoint, json=params)
        response.raise_for_status()
        data = response.json()
        
        if data and data.get("data"):
            for trade in data["data"]:
                if trade.get("symbol") == f"{moneda}USDT":
                    return {
                        "moneda": moneda,
                        "precio": float(trade["entryPrice"]),
                        "direccion": "LONG (Compra)" if float(trade["amount"]) > 0 else "SHORT (Venta)",
                        "fecha": datetime.fromtimestamp(trade["updateTime"]/1000),
                        "pnl": float(trade.get("pnl", 0)),
                        "origen": "performance"
                    }
    except Exception as e:
        print(f"Error API performance: {str(e)}")

    # 2. Si falla, intentamos con la API de información básica
    try:
        endpoint = f"https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherLeaderboardBaseInfo?encryptedUid={trader_uid}"
        response = requests.get(endpoint)
        response.raise_for_status()
        data = response.json()
        
        if data and data.get("data"):
            return {
                "moneda": moneda,
                "precio": None,
                "direccion": "Última operación",
                "fecha": datetime.fromtimestamp(data["data"]["lastTradeTime"]/1000) if data["data"]["lastTradeTime"] else None,
                "pnl": float(data["data"].get("totalPnl", 0)),
                "origen": "base_info"
            }
    except Exception as e:
        print(f"Error API base info: {str(e)}")
    
    return None

def generar_resumen_traders():
    mensaje = "<b>📊 Actividad Reciente de Traders</b>\n\n"
    resultados = []
    
    for moneda, trader_uid in TRADERS.items():
        if not trader_uid:
            continue
            
        datos = obtener_datos_trader(trader_uid, moneda)
        if datos:
            trade_msg = f"<b>➡️ TRADER_{moneda}</b>\n"
            
            if datos["origen"] == "performance":
                trade_msg += f"• Operación: {datos['direccion']}\n"
                trade_msg += f"• Precio: {datos['precio']:.2f} €\n"
                trade_msg += f"• Fecha: {datos['fecha'].strftime('%d/%m %H:%M')}\n"
                trade_msg += f"• PnL: {datos['pnl']:.2f} €\n"
            elif datos["fecha"]:
                trade_msg += f"• Última operación: {datos['fecha'].strftime('%d/%m %H:%M')}\n"
            
            trade_msg += f"• <a href='https://www.binance.com/es/copy-trading/lead-details/{trader_uid}'>Ver en Binance</a>\n"
            resultados.append((datos["fecha"] or datetime.min, trade_msg))
            
            # Guardar en Supabase solo si tenemos datos completos
            if datos["precio"]:
                try:
                    supabase.table("trades_historico").insert({
                        "trader_uid": trader_uid,
                        "moneda": moneda,
                        "direccion": datos["direccion"].split(" ")[0],
                        "precio_entrada": datos["precio"],
                        "fecha_apertura": datos["fecha"].isoformat(),
                        "estado": "ACTIVO"
                    }).execute()
                except Exception as e:
                    print(f"Error al guardar trade en Supabase: {str(e)}")
        else:
            resultados.append((datetime.min, f"<b>➡️ TRADER_{moneda}</b>\n• No se obtuvieron datos\n"))

    # Ordenar por fecha (más reciente primero)
    resultados.sort(key=lambda x: x[0], reverse=True)
    
    if any(datos[0] != datetime.min for datos in resultados):
        mensaje += "\n".join([msg for _, msg in resultados])
        mensaje += "\nℹ️ <i>Algunos datos pueden estar limitados por Binance</i>"
    else:
        mensaje += "No se pudo obtener información reciente de ningún trader.\n\n"
        mensaje += "<b>Posibles causas:</b>\n"
        mensaje += "1. Los traders no han operado recientemente\n"
        mensaje += "2. Perfiles configurados como privados\n"
        mensaje += "3. Limitaciones de la API de Binance\n\n"
        mensaje += "🔍 Verifica manualmente los enlaces en Binance"

    enviar_telegram(mensaje)

# ================ RUTAS ================
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
    return "<h1>Resumen de traders enviado 📊</h1>"

# ================ EJECUCIÓN ================
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
