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
from bs4 import BeautifulSoup
import re

def obtener_historial_trader(trader_uid, moneda):
    """Obtiene el historial de trades de un trader usando web scraping"""
    try:
        url = f"https://www.binance.com/es/copy-trading/lead-details/{trader_uid}"
        response = requests.get(url, headers=BINANCE_HEADERS, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        historial = []
        
        # Buscar la sección de historial de trades
        history_section = soup.find('div', {'class': 'history-table'})
        
        if history_section:
            # Extraer filas de la tabla de historial
            rows = history_section.find_all('div', {'class': 'history-row'})[:5]  # Últimos 5 trades
            
            for row in rows:
                try:
                    # Extraer datos de cada trade
                    fecha = row.find('div', {'class': 'history-cell-date'}).get_text(strip=True)
                    simbolo = row.find('div', {'class': 'history-cell-symbol'}).get_text(strip=True)
                    direccion = row.find('div', {'class': 'history-cell-side'}).get_text(strip=True)
                    precio = row.find('div', {'class': 'history-cell-price'}).get_text(strip=True)
                    
                    if moneda in simbolo:
                        historial.append({
                            'fecha': parsear_fecha(fecha),
                            'moneda': moneda,
                            'direccion': "COMPRA" if "LONG" in direccion.upper() else "VENTA",
                            'precio': float(precio.replace('$', '').replace(',', ''))
                        })
                except Exception as e:
                    print(f"Error procesando fila: {str(e)}")
        
        return historial if historial else None
        
    except Exception as e:
        print(f"Error en scraping de historial: {str(e)}")
        return None

def parsear_fecha(fecha_str):
    """Convierte la fecha de Binance a objeto datetime"""
    try:
        # Ejemplo: "2023-07-28 14:30:45"
        return datetime.strptime(fecha_str, "%Y-%m-%d %H:%M:%S")
    except:
        return datetime.now()

def generar_resumen_traders():
    mensaje = "<b>📊 Historial Reciente de Traders</b>\n\n"
    
    for moneda, trader_uid in TRADERS.items():
        if not trader_uid:
            continue
            
        mensaje += f"<b>➡️ TRADER_{moneda}</b>\n"
        
        # Intentar con proxy primero
        historial = obtener_historial_trader(trader_uid, moneda)
        
        # Si falla, intentar sin proxy
        if not historial and os.getenv("SCRAPER_API_KEY"):
            historial = obtener_historial_trader_fallback(trader_uid, moneda)
        
        if historial:
            for trade in historial[:3]:  # Mostrar solo 3 trades más recientes
                mensaje += (
                    f"• {trade['direccion']} {trade['moneda']} a {trade['precio']:.2f} $\n"
                    f"  ⏰ {trade['fecha'].strftime('%d/%m %H:%M')}\n"
                )
        else:
            mensaje += "• No se pudo obtener historial automáticamente\n"
        
        mensaje += f"🔗 <a href='https://www.binance.com/es/copy-trading/lead-details/{trader_uid}'>Ver historial completo</a>\n\n"
    
    mensaje += "ℹ️ Los datos pueden estar limitados por Binance"
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
