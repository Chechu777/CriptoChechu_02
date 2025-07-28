import os
import requests
from flask import Flask
from datetime import datetime, timezone
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import random
from bs4 import BeautifulSoup

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
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": "https://www.binance.com/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
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
        # Asegurar que la fecha tenga la zona horaria correcta
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=ZoneInfo("Europe/Madrid"))
        elif fecha.tzinfo != ZoneInfo("Europe/Madrid"):
            fecha = fecha.astimezone(ZoneInfo("Europe/Madrid"))
            
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
    """Obtiene información básica del trader usando web scraping"""
    if not trader_uid:
        return None
    
    try:
        url = f"https://www.binance.com/es/copy-trading/lead-details/{trader_uid}"
        response = requests.get(url, headers=BINANCE_HEADERS, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        info = {
            "moneda": moneda,
            "origen": "web_scraping"
        }
        
        # Extraer nombre del trader
        nombre_tag = soup.find('h1', {'class': 'name'})
        if nombre_tag:
            info["nombre"] = nombre_tag.get_text(strip=True)
        
        # Extraer última operación
        ultima_op_tag = soup.find('div', {'class': 'last-trade-time'})
        if ultima_op_tag:
            info["ultima_operacion"] = ultima_op_tag.get_text(strip=True)
        
        return info
    except Exception as e:
        print(f"Error al obtener datos del trader: {str(e)}")
        return None

def generar_resumen_traders():
    mensaje = "<b>🔍 Información de Traders</b>\n\n"
    
    for moneda, trader_uid in TRADERS.items():
        if not trader_uid:
            continue
            
        datos = obtener_datos_trader(trader_uid, moneda)
        mensaje += f"<b>➡️ TRADER_{moneda}</b>\n"
        
        if datos:
            if datos.get("nombre"):
                mensaje += f"👤 Nombre: {datos['nombre']}\n"
            if datos.get("ultima_operacion"):
                mensaje += f"⏰ Última operación: {datos['ultima_operacion']}\n"
        else:
            mensaje += "⚠️ No se pudieron obtener datos automáticamente\n"
        
        mensaje += f"🔗 <a href='https://www.binance.com/es/copy-trading/lead-details/{trader_uid}'>Ver en Binance</a>\n\n"
    
    mensaje += "ℹ️ Para registrar movimientos manualmente, usa:\n"
    mensaje += "/registrar [MONEDA] [TIPO] [PRECIO] [NOTAS]"
    
    enviar_telegram(mensaje)

# ========== RUTAS PARA REGISTRO MANUAL ==========

@app.route('/registrar/<moneda>/<tipo>/<precio>/<notas>')
def registrar_movimiento(moneda, tipo, precio, notas):
    try:
        # Insertar en Supabase
        supabase.table("trades_observados").insert({
            "moneda": moneda.upper(),
            "tipo": tipo.upper(),
            "precio": float(precio),
            "notas": notas,
            "fecha": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
            "verificado_por": "usuario"
        }).execute()
        
        enviar_telegram(
            f"✅ Movimiento registrado:\n"
            f"• Moneda: {moneda.upper()}\n"
            f"• Tipo: {tipo.upper()}\n"
            f"• Precio: {precio}\n"
            f"• Notas: {notas}"
        )
        return "Movimiento registrado exitosamente"
    except Exception as e:
        return f"Error: {str(e)}"

# ========== RUTAS PRINCIPALES ==========

@app.route("/")
def home():
    return "Sistema de monitoreo de criptos y traders"

@app.route("/resumen")
def resumen():
    if generar_resumen_criptos():
        return "<h1>Resumen enviado a Telegram 📢</h1><p>Precios y RSI actualizados</p>"
    else:
        return "<h1>Error al generar resumen</h1><p>Verifica los logs para más información</p>"

@app.route("/traders")
def traders():
    generar_resumen_traders()
    return "<h1>Información de traders enviada 📊</h1><p>Consulta Telegram para los detalles</p>"

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
