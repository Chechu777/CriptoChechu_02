import os
import requests
from flask import Flask
from datetime import datetime, timedelta
import pytz
import json
from collections import defaultdict

app = Flask(__name__)

# Configuración
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.environ.get("CMC_API_KEY")
ZONA_HORARIA = pytz.timezone("Europe/Madrid")
HISTORY_FILE = "/tmp/precios_historico.json"
CRIPTOS = ['BTC', 'ETH', 'ADA', 'SHIB', 'SOL']
RSI_PERIOD = 14  # Periodo estándar para cálculo de RSI

# Almacenamiento de datos
price_history = defaultdict(list)

def load_history():
    """Carga el historial de precios desde el archivo JSON"""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                data = json.load(f)
                for crypto in CRIPTOS:
                    price_history[crypto] = data.get(crypto, [])
        print("[INFO] Historial de precios cargado")
    except Exception as e:
        print(f"[ERROR] Error cargando historial: {e}")

def save_history():
    """Guarda el historial de precios en el archivo JSON"""
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(price_history, f)
    except Exception as e:
        print(f"[ERROR] Error guardando historial: {e}")

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
        
        # Registrar el precio actual
        price_history[crypto].append({
            "timestamp": timestamp,
            "price": precio
        })
        
        # Mantener solo los datos necesarios para el RSI
        if len(price_history[crypto]) > RSI_PERIOD * 2:
            price_history[crypto] = price_history[crypto][-RSI_PERIOD*2:]
        
        save_history()
        return precio

    except Exception as e:
        print(f"[ERROR] No se pudo obtener el precio de {cripto}: {e}")
        return None

def calcular_rsi(cripto):
    """Calcula el RSI basado en el historial de precios"""
    historico = price_history.get(cripto, [])
    
    if len(historico) < RSI_PERIOD + 1:
        return None
    
    precios = [p["price"] for p in historico[-(RSI_PERIOD+1):]]
    cambios = [precios[i] - precios[i-1] for i in range(1, len(precios))]
    
    ganancias = [max(c, 0) for c in cambios]
    perdidas = [abs(min(c, 0)) for c in cambios]
    
    avg_ganancia = sum(ganancias) / RSI_PERIOD
    avg_perdida = sum(perdidas) / RSI_PERIOD or 0.0001  # Evitar división por cero
    
    rs = avg_ganancia / avg_perdida
    rsi = 100 - (100 / (1 + rs))
    
    return round(rsi, 2)

def generar_consejo(rsi):
    """Genera recomendación basada en el valor RSI"""
    if rsi is None:
        return "🔍 RSI: Sin datos suficientes\n🔄 Necesito más datos históricos (15+ registros)"
    elif rsi < 30:
        return f"💎 RSI: {rsi:.2f} (Sobrevendido)\n📢 Oportunidad de COMPRA"
    elif rsi > 70:
        return f"🔥 RSI: {rsi:.2f} (Sobrecomprado)\n⚠️ Considera VENDER"
    else:
        return f"⚖️ RSI: {rsi:.2f} (Neutral)\n🤔 Mantén tu posición"

def obtener_resumen_diario():
    """Genera el resumen completo de todas las criptomonedas"""
    resumen = "📊 *Resumen Criptomonedas* 📊\n\n"
    
    for cripto in CRIPTOS:
        precio_actual = obtener_precio_actual(cripto)
        if precio_actual is None:
            resumen += f"⚠️ *{cripto}*: Error al obtener precio\n\n"
            continue

        rsi = calcular_rsi(cripto)
        consejo = generar_consejo(rsi)

        # Calcular variación respecto al último precio
        variacion = ""
        if len(price_history[cripto]) > 1:
            precio_anterior = price_history[cripto][-2]["price"]
            cambio = ((precio_actual - precio_anterior) / precio_anterior) * 100
            if abs(cambio) > 0.5:  # Mostrar solo variaciones > 0.5%
                direccion = "📈" if cambio > 0 else "📉"
                variacion = f"{direccion} {abs(cambio):.2f}% desde último registro"

        resumen += (
            f"💰 *{cripto}*: {precio_actual:,.8f} €\n"
            f"{consejo}\n"
            f"{variacion if variacion else '➡️ Variación mínima (<0.5%)'}\n\n"
        )

    hora_actual = datetime.now(ZONA_HORARIA).strftime('%d/%m %H:%M')
    resumen += f"⏱️ Actualizado: {hora_actual} (Hora Europa)"
    
    # Mostrar progreso de datos históricos
    datos_disponibles = min(len(price_history.get(c, [])) for c in CRIPTOS)
    resumen += f"\n\n📊 Datos históricos: {datos_disponibles}/{RSI_PERIOD+1} (necesarios para RSI)"
    
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
    return "🤖 CryptoBot Activo ✅"

@app.route("/resumen")  # Endpoint corregido
def resumen_manual():
    try:
        resumen = obtener_resumen_diario()
        enviar_mensaje(resumen)
        return "✅ Resumen enviado a Telegram"
    except Exception as e:
        return f"❌ Error: {str(e)}"

# Cargar historial al iniciar
load_history()

if __name__ == '__main__':
    app.run()
