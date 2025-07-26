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
HISTORICO_DIAS = 14
CRIPTOS = ['BTC', 'ETH', 'ADA', 'SHIB', 'SOL']
HISTORICO_FILE = "/tmp/precios_historico.json"

# Datos
precios_historicos = defaultdict(list)
precios_actuales = {}

# Inicialización de datos dummy para RSI
valores_rsi_iniciales = {
    'BTC': ("⚡ 45", "Moderado"),
    'ETH': ("⚡ 50", "Neutral"), 
    'ADA': ("⚡ 40", "Bajo"),
    'SHIB': ("⚡ 55", "Moderado"),
    'SOL': ("⚡ 60", "Alto")
}

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

# Obtener precios con reintentos
def obtener_precios(max_reintentos=3):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    params = {"symbol": ",".join(CRIPTOS), "convert": "EUR"}
    
    for intento in range(max_reintentos):
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
                
                # Mantener máximo 24 horas * días de histórico
                if len(precios_historicos[cripto]) > HISTORICO_DIAS * 24:
                    precios_historicos[cripto] = precios_historicos[cripto][-HISTORICO_DIAS*24:]
            
            guardar_historico()
            return True
            
        except Exception as e:
            print(f"[ERROR] Intento {intento+1}: {e}")
            if intento < max_reintentos - 1:
                time.sleep(5)
    
    return False

# Análisis técnico mejorado
def calcular_media(cripto, dias=7):
    historico = precios_historicos.get(cripto, [])
    if len(historico) < dias * 4:  # Requiere al menos 4 datos por día
        return None
    return sum(p["precio"] for p in historico[-dias*24:]) / len(historico[-dias*24:])

def calcular_rsi(cripto, periodo=14):
    historico = precios_historicos.get(cripto, [])
    if len(historico) < periodo + 1:
        return valores_rsi_iniciales.get(cripto, ("N/A", "Sin datos"))
    
    precios = [p["precio"] for p in historico[-periodo-1:]]
    cambios = [precios[i] - precios[i-1] for i in range(1, len(precios))]
    
    avg_ganancia = sum(max(c, 0) for c in cambios) / periodo
    avg_perdida = abs(sum(min(c, 0) for c in cambios)) / periodo
    
    rs = avg_ganancia / (avg_perdida or 0.0001)
    rsi_value = min(100, max(0, 100 - (100 / (1 + rs))))
    
    if rsi_value < 30:
        estado = "🔥 COMPRAR (sobrevendido)"
    elif rsi_value > 70:
        estado = "⚠️ VENDER (sobrecomprado)"
    elif rsi_value > 65:
        estado = "🔼 RSI alto"
    elif rsi_value < 35:
        estado = "🔽 RSI bajo"
    else:
        estado = "🟢 Neutral"
    
    return (f"{rsi_value:.1f}", estado)

# Generación de mensajes mejorada
def generar_mensaje_cripto(cripto):
    precio = precios_actuales.get(cripto)
    media_7d = calcular_media(cripto, 7)
    rsi_valor, rsi_estado = calcular_rsi(cripto)
    
    # Formateo de precio
    if precio is None:
        precio_str = "N/A"
        variacion = "⚠️ Sin datos recientes"
    else:
        precio_str = f"{precio:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        
        # Cálculo de variación
        if media_7d:
            cambio = ((precio - media_7d) / media_7d) * 100
            if abs(cambio) > 10:
                direccion = "🚀" if cambio > 0 else "⚠️📉"
                variacion = f"{direccion} {abs(cambio):.1f}% (7d)"
            elif abs(cambio) > 5:
                direccion = "📈" if cambio > 0 else "📉"
                variacion = f"{direccion} {abs(cambio):.1f}% (7d)"
            else:
                variacion = "➡️ Estable"
        else:
            variacion = "🔍 Sin histórico suficiente"
    
    return (
        f"💰 *{cripto}*: {precio_str}\n"
        f"📊 RSI: {rsi_valor} | {rsi_estado}\n"
        f"{variacion}\n"
    )

def obtener_resumen():
    if not obtener_precios():
        return "⚠️ Error obteniendo datos. Por favor intenta más tarde."
    
    mensaje = "📊 *Resumen Criptomonedas* 📊\n\n"
    for cripto in CRIPTOS:
        mensaje += generar_mensaje_cripto(cripto) + "\n"
    
    # Información de estado
    datos_disponibles = min(len(precios_historicos.get(c, [])) for c in CRIPTOS)
    mensaje += f"📅 Datos acumulados: {datos_disponibles}/{HISTORICO_DIAS*24}\n"
    mensaje += f"🔄 Actualizado: {ahora().strftime('%d/%m %H:%M')}"
    
    return mensaje

# Telegram y Flask (sin cambios)
def enviar_mensaje(texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
        print("[INFO] Mensaje enviado")
    except Exception as e:
        print(f"[ERROR] Enviando mensaje: {e}")

@app.route("/")
def home():
    return "Bot Cripto Activo ✅"

@app.route("/resumen")
def resumen():
    try:
        mensaje = obtener_resumen()
        enviar_mensaje(f"🔔 *Actualización Manual*\n\n{mensaje}")
        return "Resumen enviado"
    except Exception as e:
        return f"Error: {e}"

# Inicialización
cargar_historico()
atexit.register(guardar_historico)

if ENVIAR_RESUMEN_DIARIO:
    threading.Thread(target=tarea_monitor, daemon=True).start()
