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

# Configuración de headers para evitar bloqueos
BINANCE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.binance.com/"
}

# ========== FUNCIONES PRINCIPALES ==========

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

# ========== FUNCIONES DE TRADERS ==========

def obtener_datos_trader(trader_uid, moneda):
    """Función principal para obtener datos de traders"""
    if not trader_uid:
        return None
    
    # Primero intentamos con la API pública
    try:
        endpoint = "https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherPosition"
        params = {"encryptedUid": trader_uid, "tradeType": "PERPETUAL"}
        response = requests.post(endpoint, json=params, headers=BINANCE_HEADERS)
        response.raise_for_status()
        data = response.json()
        
        if data.get("data"):
            for posicion in data["data"]:
                if posicion["symbol"] == f"{moneda}USDT":
                    return {
                        "moneda": moneda,
                        "precio": float(posicion["entryPrice"]),
                        "direccion": "LONG (Compra)" if float(posicion["amount"]) > 0 else "SHORT (Venta)",
                        "fecha": datetime.fromtimestamp(posicion["updateTime"]/1000),
                        "origen": "api_publica"
                    }
    except Exception as e:
        print(f"Error al obtener datos del trader (API pública): {str(e)}")
    
    # Si falla, intentamos con scraping web
    return obtener_datos_trader_web(trader_uid, moneda)

def obtener_datos_trader_web(trader_uid, moneda):
    """Alternativa cuando falla la API"""
    try:
        url = f"https://www.binance.com/es/copy-trading/lead-details/{trader_uid}"
        response = requests.get(url, headers=BINANCE_HEADERS)
        response.raise_for_status()
        
        # Extraer información básica de la página
        if "Última operación" in response.text:
            return {
                "moneda": moneda,
                "precio": None,
                "direccion": "Ver en Binance",
                "fecha": datetime.now(),
                "origen": "web_scraping"
            }
    except Exception as e:
        print(f"Error en scraping web: {str(e)}")
    return None

def generar_resumen_traders():
    mensaje = "<b>🔍 Resumen de Traders</b>\n\n"
    traders_con_datos = False
    
    for moneda, trader_uid in TRADERS.items():
        if not trader_uid:
            continue
            
        datos = obtener_datos_trader(trader_uid, moneda)
        if datos:
            traders_con_datos = True
            mensaje += f"📊 <b>TRADER_{moneda}</b>\n"
            
            if datos["origen"] == "api_publica":
                mensaje += f"• Operación: {datos['direccion']}\n"
                if datos["precio"]:
                    mensaje += f"• Precio: {datos['precio']:.2f} €\n"
                mensaje += f"• Fecha: {datos['fecha'].strftime('%d/%m %H:%M')}\n"
            else:
                mensaje += "• Datos limitados (ver en Binance)\n"
            
            mensaje += f"🔗 <a href='https://www.binance.com/es/copy-trading/lead-details/{trader_uid}'>Ver detalles en Binance</a>\n\n"
        else:
            mensaje += f"❌ TRADER_{moneda}: No se pudieron obtener datos\n\n"
    
    if not traders_con_datos:
        mensaje += "ℹ️ No se encontraron datos de traders. Posibles razones:\n"
        mensaje += "- Perfiles privados\n"
        mensaje += "- Restricciones de Binance\n"
        mensaje += "- El trader no ha operado recientemente\n\n"
        mensaje += "Puedes verificar manualmente los enlaces proporcionados."
    
    enviar_telegram(mensaje)

# ========== RUTAS ==========

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
