import os
import requests
from flask import Flask
from datetime import datetime, timedelta
import pytz
import json
from collections import defaultdict
import time

app = Flask(__name__)

# Configuración
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.environ.get("CMC_API_KEY")
ZONA_HORARIA = pytz.timezone("Europe/Madrid")
CRIPTOS = ['BTC', 'ETH', 'ADA', 'SHIB', 'SOL']
RSI_PERIOD = 14  # Periodo estándar para cálculo de RSI

# Almacenamiento en memoria
price_history = defaultdict(list)

def obtener_datos_historicos(cripto):
    """Obtiene datos históricos de la última hora desde CoinMarketCap"""
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/ohlcv/historical"
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accepts": "application/json"
    }
    
    # Obtener timestamp actual y de hace 1 hora
    end_time = datetime.now(ZONA_HORARIA)
    start_time = end_time - timedelta(hours=1)
    
    params = {
        "symbol": cripto,
        "convert": "EUR",
        "time_start": start_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "time_end": end_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "count": RSI_PERIOD + 1,  # Datos suficientes para RSI
        "interval": "5m"  # Intervalo de 5 minutos
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        
        if "data" not in data or not data["data"].get("quotes"):
            print(f"[ERROR] No se encontraron datos históricos para {cripto}")
            return None
            
        quotes = data["data"]["quotes"]
        
        # Procesar los datos históricos
        historical_prices = []
        for quote in quotes:
            timestamp = quote["quote"]["EUR"]["timestamp"]
            price = quote["quote"]["EUR"]["close"]  # Precio de cierre
            historical_prices.append({
                "timestamp": timestamp,
                "price": price
            })
        
        return historical_prices
        
    except Exception as e:
        print(f"[ERROR] Error obteniendo datos históricos para {cripto}: {e}")
        return None

def obtener_precio_actual(cripto):
    """Obtiene el precio actual desde la API de CoinMarketCap"""
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accepts": "application/json"
    }
    params = {"symbol": cripto, "convert": "EUR"}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        if "data" not in data or cripto not in data["data"]:
            print(f"[ERROR] Respuesta inesperada de CMC para {cripto}: {data}")
            return None

        precio = float(data["data"][cripto]["quote"]["EUR"]["price"])
        timestamp = datetime.now(ZONA_HORARIA).strftime('%Y-%m-%d %H:%M:%S')
        
        # Actualizar el historial de precios
        price_history[cripto].append({
            "timestamp": timestamp,
            "price": precio
        })
        
        # Mantener solo los últimos datos necesarios
        if len(price_history[cripto]) > RSI_PERIOD * 2:
            price_history[cripto] = price_history[cripto][-RSI_PERIOD*2:]
            
        return precio

    except Exception as e:
        print(f"[ERROR] No se pudo obtener el precio de {cripto}: {e}")
        return None

def calcular_rsi(cripto):
    """Calcula el RSI basado en datos históricos"""
    # Primero intentar con datos en memoria
    if len(price_history.get(cripto, [])) >= RSI_PERIOD + 1:
        precios = [p["price"] for p in price_history[cripto][-(RSI_PERIOD+1):]]
    else:
        # Si no hay suficientes datos en memoria, obtener históricos
        historical_data = obtener_datos_historicos(cripto)
        if not historical_data or len(historical_data) < RSI_PERIOD + 1:
            return None
            
        precios = [p["price"] for p in historical_data]
    
    # Calcular cambios
    cambios = [precios[i] - precios[i-1] for i in range(1, len(precios))]
    
    # Separar ganancias y pérdidas
    ganancias = [max(cambio, 0) for cambio in cambios]
    perdidas = [abs(min(cambio, 0)) for cambio in cambios]
    
    # Calcular medias móviles
    avg_ganancia = sum(ganancias) / RSI_PERIOD
    avg_perdida = sum(perdidas) / RSI_PERIOD
    
    # Evitar división por cero
    if avg_perdida == 0:
        return 100
    
    rs = avg_ganancia / avg_perdida
    rsi = 100 - (100 / (1 + rs))
    
    return round(rsi, 2)

def generar_consejo(rsi):
    """Genera recomendación basada en el valor RSI"""
    if rsi is None:
        return "🔍 RSI: Calculando...\n🔄 Obteniendo datos históricos"
    elif rsi < 30:
        return f"💎 RSI: {rsi:.2f} (Sobrevendido)\n📢 Oportunidad de COMPRA"
    elif rsi > 70:
        return f"🔥 RSI: {rsi:.2f} (Sobrecomprado)\n⚠️ Considera VENDER"
    elif rsi > 65:
        return f"📈 RSI: {rsi:.2f} (Alto)\n🤔 Podría sobrecomprarse"
    elif rsi < 35:
        return f"📉 RSI: {rsi:.2f} (Bajo)\n🤔 Podría sobrevenderse"
    else:
        return f"⚖️ RSI: {rsi:.2f} (Neutral)\n🔄 Mercado equilibrado"

def obtener_resumen_diario():
    """Genera el resumen completo de todas las criptomonedas"""
    resumen = "📈 *Análisis Cripto en Tiempo Real* 📉\n\n"
    
    for cripto in CRIPTOS:
        # Obtener precio actual
        precio_actual = obtener_precio_actual(cripto)
        if precio_actual is None:
            resumen += f"⚠️ *{cripto}*: Error al obtener precio\n\n"
            continue

        # Calcular RSI
        rsi = calcular_rsi(cripto)
        consejo = generar_consejo(rsi)

        # Obtener precio de referencia (hace 1 hora)
        precio_ref = None
        historical_data = obtener_datos_historicos(cripto)
        if historical_data and len(historical_data) > 0:
            precio_ref = historical_data[0]["price"]  # Primer dato (más antiguo)
        
        # Calcular variación porcentual
        variacion = ""
        if precio_ref and precio_ref > 0:
            cambio = ((precio_actual - precio_ref) / precio_ref) * 100
            if abs(cambio) > 0.5:  # Mostrar variaciones > 0.5%
                direccion = "🔼" if cambio > 0 else "🔽"
                variacion = f"{direccion} {abs(cambio):.2f}% (1h)"

        resumen += (
            f"🪙 *{cripto}*: {precio_actual:,.8f} €\n"
            f"{consejo}\n"
            f"{variacion if variacion else '↔️ Variación <0.5% (1h)'}\n\n"
        )

    hora_actual = datetime.now(ZONA_HORARIA).strftime('%d/%m %H:%M')
    resumen += f"⏱️ Actualizado: {hora_actual} (Hora Europa)"
    
    return resumen

def enviar_mensaje(mensaje):
    """Envía un mensaje a través del bot de Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("[INFO] Mensaje enviado correctamente")
    except Exception as e:
        print(f"[ERROR] Al enviar mensaje: {e}")

@app.route("/")
def home():
    return "🔮 CryptoAnalyst Bot - Activo ✅"

@app.route("/analisis")
def analisis_cripto():
    try:
        resumen = obtener_resumen_diario()
        enviar_mensaje(resumen)
        return "✅ Análisis enviado a Telegram"
    except Exception as e:
        return f"❌ Error: {str(e)}"

if __name__ == '__main__':
    app.run()
