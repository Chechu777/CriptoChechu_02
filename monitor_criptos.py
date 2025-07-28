import os
import requests
from flask import Flask, request
from datetime import datetime, timezone
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import random
from bs4 import BeautifulSoup
import pytz

# Configuración
app = Flask(__name__)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]
TRADERS = {
    "BTC": os.getenv("TRADER_BTC"),
    "SOL": os.getenv("TRADER_SOL")
}

# ========== FUNCIONES AUXILIARES ==========

def obtener_precios():
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    params = {"symbol": ",".join(MONEDAS), "convert": "EUR"}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()["data"]
        return {m: round(data[m]["quote"]["EUR"]["price"], 8) for m in MONEDAS}
    except Exception as e:
        print(f"Error API CoinMarketCap: {str(e)}")
        return None


def obtener_fecha_actual():
    """Devuelve la fecha actual en la zona horaria correcta"""
    madrid_tz = pytz.timezone('Europe/Madrid')
    return datetime.now(madrid_tz)

def insertar_en_supabase(nombre, precio, rsi, fecha):
    try:
        # Convertir explícitamente a UTC antes de insertar
        fecha_utc = fecha.astimezone(pytz.utc)
        
        supabase.table("precios").insert({
            "nombre": nombre,
            "precio": precio,
            "rsi": rsi,
            "fecha": fecha_utc.isoformat()  # Guardar en UTC
        }).execute()
    except Exception as e:
        print(f"Error al insertar en Supabase: {str(e)}")

def generar_resumen_criptos():
    precios = obtener_precios()
    if not precios:
        enviar_telegram("⚠️ No se pudieron obtener los precios de las criptomonedas")
        return False
    
    ahora = obtener_fecha_actual()  # Usar nuestra función mejorada
    
    resumen = "<b>📊 Resumen de Criptomonedas</b>\n"
    
    for m in MONEDAS:
        precio = precios[m]
        rsi = obtener_rsi(m)
        insertar_en_supabase(m, precio, rsi, ahora)
        consejo = consejo_rsi(rsi)
        resumen += f"\n<b>{m}</b>: {precio:,.8f} €\nRSI: {rsi} → {consejo}\n"
    
    # Mostrar hora local al usuario
    resumen += f"\n🗱️ Actualizado: {ahora.strftime('%d/%m %H:%M')} (Hora Europa)"
    enviar_telegram(resumen)
    return True

# ========== SISTEMA DE TRADERS ==========

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    })

def obtener_info_trader(trader_uid, moneda):
    """Intenta obtener información del trader"""
    try:
        url = f"https://www.binance.com/es/copy-trading/lead-details/{trader_uid}"
        response = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }, timeout=10)
        
        soup = BeautifulSoup(response.text, 'html.parser')
        return {
            "nombre": soup.find('h1', class_='name').get_text(strip=True) if soup.find('h1', class_='name') else "Trader",
            "ultima_operacion": soup.find('div', class_='time').get_text(strip=True) if soup.find('div', class_='time') else "No disponible"
        }
    except Exception as e:
        print(f"Error scraping trader: {str(e)}")
        return None

def generar_resumen_traders():
    mensaje = "<b>🔔 Monitoreo de Traders</b>\n\n"
    
    for moneda, uid in TRADERS.items():
        if not uid:
            continue
            
        info = obtener_info_trader(uid, moneda) or {}
        mensaje += (
            f"<b>➡️ TRADER_{moneda}</b>\n"
            f"👤 {info.get('nombre', 'Trader')}\n"
            f"⏰ Última operación: {info.get('ultima_operacion', 'No disponible')}\n"
            f"🔗 <a href='https://www.binance.com/es/copy-trading/lead-details/{uid}'>Ver detalles</a>\n\n"
        )
    
    mensaje += (
        "<b>📌 Para registrar una operación:</b>\n"
        "Envia <code>/registrar SOL COMPRA 142.50 "Aumentó posición"</code>\n"
        "O usa el enlace:\n"
        f"https://monitor-criptos.onrender.com/registrar/SOL/COMPRA/142.50/Aumento%20posicion"
    )
    
    enviar_telegram(mensaje)

# ========== REGISTRO MANUAL ==========

@app.route('/registrar/<moneda>/<tipo>/<precio>/<notas>')
def registrar_operacion(moneda, tipo, precio, notas):
    try:
        # Validar moneda
        moneda = moneda.upper()
        if moneda not in MONEDAS:
            return f"Error: Moneda {moneda} no válida"
        
        # Insertar en Supabase
        supabase.table("trades_observados").insert({
            "moneda": moneda,
            "tipo": tipo.upper(),
            "precio": float(precio),
            "notas": notas.replace("_", " "),
            "fecha": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
            "fuente": "manual"
        }).execute()
        
        # Notificar por Telegram
        enviar_telegram(
            f"✅ <b>Operación registrada</b>\n\n"
            f"<b>Moneda:</b> {moneda}\n"
            f"<b>Tipo:</b> {tipo.upper()}\n"
            f"<b>Precio:</b> {precio} €\n"
            f"<b>Notas:</b> {notas.replace('_', ' ')}\n\n"
            f"🕒 {datetime.now(ZoneInfo('Europe/Madrid')).strftime('%d/%m %H:%M')}"
        )
        
        return "Operación registrada exitosamente"
    except Exception as e:
        return f"Error: {str(e)}"

# ========== RUTAS PRINCIPALES ==========

@app.route('/')
def home():
    return "Sistema de monitoreo activo"

@app.route('/resumen')
def resumen():
    if generar_resumen_criptos():
        return "Resumen enviado a Telegram"
    return "Error al generar resumen"

@app.route('/traders')
def traders():
    generar_resumen_traders()
    return "Información de traders enviada"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
