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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.8,en-US;q=0.5,en;q=0.3",
    "Referer": "https://www.binance.com/",
    "DNT": "1"
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
def obtener_info_trader(trader_uid, moneda):
    """Obtiene información básica del trader usando múltiples métodos"""
    if not trader_uid:
        return None
    
    # 1. Intento con API alternativa de Binance
    try:
        endpoint = "https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherLeaderboardBaseInfo"
        params = {"encryptedUid": trader_uid}
        response = requests.get(endpoint, params=params, headers=BINANCE_HEADERS, timeout=10)
        data = response.json()
        
        if data.get("data"):
            return {
                "moneda": moneda,
                "nombre": data["data"].get("nickName", "Trader"),
                "pnl_7d": data["data"].get("pnl7Day", 0),
                "ultima_operacion": datetime.fromtimestamp(data["data"]["lastTradeTime"]/1000) if data["data"]["lastTradeTime"] else None,
                "origen": "api_alternativa"
            }
    except Exception as e:
        print(f"Error API alternativa: {str(e)}")

    # 2. Web scraping mejorado
    try:
        url = f"https://www.binance.com/es/copy-trading/lead-details/{trader_uid}"
        response = requests.get(url, headers=BINANCE_HEADERS, timeout=10)
        
        # Extraemos datos básicos del HTML
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        info = {
            "moneda": moneda,
            "origen": "web_scraping"
        }
        
        # Extraer nombre del trader
        nombre_tag = soup.find('h1', {'class': 'name'})
        if nombre_tag:
            info["nombre"] = nombre_tag.get_text(strip=True)
        
        # Extraer PNL
        pnl_tag = soup.find('div', {'class': 'profit-rate'})
        if pnl_tag:
            info["pnl_7d"] = pnl_tag.get_text(strip=True)
        
        return info
    except Exception as e:
        print(f"Error scraping: {str(e)}")
    
    return None

def generar_resumen_traders():
    mensaje = "<b>📊 Información de Traders</b>\n\n"
    
    for moneda, trader_uid in TRADERS.items():
        if not trader_uid:
            continue
            
        datos = obtener_info_trader(trader_uid, moneda)
        if datos:
            mensaje += f"<b>➡️ TRADER_{moneda}</b>\n"
            mensaje += f"👤 Nombre: {datos.get('nombre', 'No disponible')}\n"
            
            if datos.get('ultima_operacion'):
                mensaje += f"⏰ Última operación: {datos['ultima_operacion'].strftime('%d/%m %H:%M')}\n"
            
            if datos.get('pnl_7d'):
                pnl = float(datos['pnl_7d']) if isinstance(datos['pnl_7d'], (int, float)) else datos['pnl_7d']
                mensaje += f"📈 PNL (7 días): {pnl}\n"
            
            mensaje += f"🔗 <a href='https://www.binance.com/es/copy-trading/lead-details/{trader_uid}'>Ver perfil completo</a>\n\n"
        else:
            mensaje += f"⚠️ <b>TRADER_{moneda}</b>: Información limitada\n"
            mensaje += f"🔗 <a href='https://www.binance.com/es/copy-trading/lead-details/{trader_uid}'>Ver en Binance</a>\n\n"
    
    mensaje += "ℹ️ <i>Para ver operaciones detalladas, consulta los enlaces directamente en Binance</i>"
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
