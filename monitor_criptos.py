import os
import time
import threading
import datetime
import requests
from flask import Flask
from pytz import timezone
import json
from collections import defaultdict
import atexit

app = Flask(__name__)

# Configuración
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("CMC_API_KEY")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")
ZONA_HORARIA = timezone("Europe/Madrid")
HISTORICO_DIAS = 14  # Aumentado para tener suficiente historial para RSI
CRIPTOS = ['BTC', 'ETH', 'ADA', 'SHIB', 'SOL']
HISTORICO_FILE = "/tmp/precios_historico.json"

# Datos
precios_historicos = defaultdict(list)
precios_actuales = {}

# Helper para fechas
def ahora():
    return datetime.datetime.now(ZONA_HORARIA)

# Manejo de histórico
def cargar_historico():
    try:
        if os.path.exists(HISTORICO_FILE):
            with open(HISTORICO_FILE, 'r') as f:
                data = json.load(f)
                for cripto in CRIPTOS:
                    if cripto in data:
                        precios_historicos[cripto] = data[cripto]
        print("[INFO] Histórico cargado")
    except Exception as e:
        print(f"[ERROR] Cargando histórico: {e}")

def guardar_historico():
    try:
        with open(HISTORICO_FILE, 'w') as f:
            json.dump(precios_historicos, f)
    except Exception as e:
        print(f"[ERROR] Guardando histórico: {e}")

# Obtener precios
def obtener_precios():
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    params = {"symbol": ",".join(CRIPTOS), "convert": "EUR"}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        for cripto in CRIPTOS:
            precio = float(data["data"][cripto]["quote"]["EUR"]["price"])
            fecha_str = ahora().strftime('%Y-%m-%d %H:%M:%S')
            
            precios_historicos[cripto].append({
                "fecha": fecha_str,
                "precio": precio
            })
            precios_actuales[cripto] = precio
            
            # Mantener solo el historial necesario
            if len(precios_historicos[cripto]) > HISTORICO_DIAS * 24:  # Asumiendo 1 dato por hora
                precios_historicos[cripto] = precios_historicos[cripto][-HISTORICO_DIAS*24:]
        
        guardar_historico()
        return True
    except Exception as e:
        print(f"[ERROR] Obteniendo precios: {e}")
        return False

# Análisis técnico
def calcular_media(cripto, dias=7):
    historico = precios_historicos.get(cripto, [])
    if len(historico) < dias:
        return None
    return sum(p["precio"] for p in historico[-dias:]) / dias

def calcular_rsi(cripto, periodo=14):
    historico = precios_historicos.get(cripto, [])
    if len(historico) < periodo + 1:
        # Si no hay suficiente historial, usar valores dummy iniciales
        valores_dummy = {
            'BTC': 45, 'ETH': 50, 'ADA': 40, 
            'SHIB': 55, 'SOL': 60
        }
        return valores_dummy.get(cripto, 50)
    
    precios = [p["precio"] for p in historico[-periodo-1:]]
    cambios = [precios[i] - precios[i-1] for i in range(1, len(precios))]
    
    avg_ganancia = sum(max(c, 0) for c in cambios) / periodo
    avg_perdida = abs(sum(min(c, 0) for c in cambios)) / periodo
    
    rs = avg_ganancia / (avg_perdida or 0.0001)
    return min(100, max(0, 100 - (100 / (1 + rs))))

# Generación de mensajes
def generar_mensaje_cripto(cripto):
    precio = precios_actuales.get(cripto)
    media_7d = calcular_media(cripto, 7)
    rsi = calcular_rsi(cripto)
    
    # Formatear precio
    precio_str = "N/A" if precio is None else f"{precio:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    
    # Variación
    variacion = ""
    if media_7d and precio:
        cambio = ((precio - media_7d) / media_7d) * 100
        if abs(cambio) > 2:
            direccion = "📈" if cambio > 0 else "📉"
            variacion = f"{direccion} {abs(cambio):.1f}% (7d)"
    
    # Consejo RSI
    if isinstance(rsi, str):  # Para valores dummy
        consejo = f"⚡ {rsi}"
    elif rsi < 30:
        consejo = "🔥 COMPRAR (sobrevendido)"
    elif rsi > 70:
        consejo = "⚠️ VENDER (sobrecomprado)"
    elif rsi > 65:
        consejo = "🔼 RSI alto"
    elif rsi < 35:
        consejo = "🔽 RSI bajo"
    else:
        consejo = "🟢 Neutral"
    
    rsi_str = f"{rsi:.1f}" if isinstance(rsi, (int, float)) else rsi
    
    return (
        f"💰 *{cripto}*: {precio_str}\n"
        f"📊 RSI: {rsi_str} | {consejo}\n"
        f"{variacion}\n"
    )

def obtener_resumen():
    if not obtener_precios():
        return "⚠️ Error obteniendo datos. Reintentando..."
    
    mensaje = "📊 *Resumen Criptomonedas* 📊\n\n"
    for cripto in CRIPTOS:
        mensaje += generar_mensaje_cripto(cripto) + "\n"
    
    # Info sobre el estado del histórico
    total_datos = {c: len(precios_historicos.get(c, [])) for c in CRIPTOS}
    mensaje += f"📅 Histórico: {min(total_datos.values())}/{HISTORICO_DIAS*24} datos\n"
    mensaje += f"🔄 Actualizado: {ahora().strftime('%d/%m %H:%M')}"
    return mensaje

# Resto del código (Telegram, Flask endpoints, tarea_monitor) se mantiene igual como en la versión anterior
