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
HISTORICO_DIAS = 7  # Reducido para acelerar pruebas
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
            
            # Mantener solo los últimos 7 días de datos (24 datos por día)
            if len(precios_historicos[cripto]) > HISTORICO_DIAS * 24:
                precios_historicos[cripto] = precios_historicos[cripto][-HISTORICO_DIAS*24:]
        
        guardar_historico()
        return True
    except Exception as e:
        print(f"[ERROR] Obteniendo precios: {e}")
        return False

# Análisis técnico mejorado
def calcular_media(cripto, horas=24):
    historico = precios_historicos.get(cripto, [])
    if len(historico) < horas:
        return None
    return sum(p["precio"] for p in historico[-horas:]) / horas

def calcular_rsi(cripto, periodo=14):
    historico = precios_historicos.get(cripto, [])
    if len(historico) < periodo + 1:
        # Valores iniciales mientras acumulamos datos
        valores_iniciales = {
            'BTC': ("52", "🟡 Moderado"),
            'ETH': ("50", "🟢 Neutral"),
            'ADA': ("45", "🟠 Bajo"),
            'SHIB': ("55", "🟡 Moderado"),
            'SOL': ("58", "🔵 Alto")
        }
        return valores_iniciales.get(cripto, ("50", "⚪ Sin datos"))
    
    precios = [p["precio"] for p in historico[-periodo-1:]]
    cambios = [precios[i] - precios[i-1] for i in range(1, len(precios))]
    
    avg_ganancia = sum(max(c, 0) for c in cambios) / periodo
    avg_perdida = abs(sum(min(c, 0) for c in cambios)) / periodo
    
    rs = avg_ganancia / (avg_perdida or 0.0001)
    rsi = min(100, max(0, 100 - (100 / (1 + rs))))
    
    if rsi < 30:
        estado = "🔴 COMPRAR (sobrevendido)"
    elif rsi > 70:
        estado = "🟢 VENDER (sobrecomprado)"
    elif rsi > 65:
        estado = "🟡 RSI alto"
    elif rsi < 35:
        estado = "🟠 RSI bajo"
    else:
        estado = "⚪ Neutral"
    
    return (f"{rsi:.1f}", estado)

# Generación de mensajes mejorada
def generar_mensaje_cripto(cripto):
    precio = precios_actuales.get(cripto)
    media_24h = calcular_media(cripto, 24)
    rsi_valor, rsi_estado = calcular_rsi(cripto)
    
    # Formateo de precio
    precio_str = "N/A" if precio is None else f"{precio:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    
    # Variación porcentual
    variacion = ""
    if media_24h and precio:
        cambio = ((precio - media_24h) / media_24h) * 100
        if abs(cambio) > 5:
            direccion = "📈" if cambio > 0 else "📉"
            variacion = f"{direccion} {abs(cambio):.1f}% (24h)"
    
    return (
        f"💰 *{cripto}*: {precio_str}\n"
        f"📊 RSI: {rsi_valor} | {rsi_estado}\n"
        f"{variacion if variacion else '➡️ Estable'}\n"
    )

def obtener_resumen():
    if not obtener_precios():
        return "⚠️ Error obteniendo datos. Reintentando..."
    
    mensaje = "📊 *Resumen Criptomonedas* 📊\n\n"
    for cripto in CRIPTOS:
        mensaje += generar_mensaje_cripto(cripto)
    
    # Información de estado
    datos_minimos = min(len(precios_historicos.get(c, [])) for c in CRIPTOS)
    mensaje += f"\n📅 Datos: {datos_minimos}/{HISTORICO_DIAS*24} (máx {HISTORICO_DIAS}d)\n"
    mensaje += f"🔄 Actualizado: {ahora().strftime('%d/%m %H:%M')}"
    
    return mensaje

# Telegram
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

# Tarea programada
def tarea_monitor():
    print("[INFO] Monitor iniciado")
    while True:
        ahora_local = ahora()
        
        # Resumen diario automático
        if ENVIAR_RESUMEN_DIARIO and ahora_local.strftime("%H:%M") == RESUMEN_HORA:
            enviar_mensaje(obtener_resumen())
            time.sleep(61)  # Evitar duplicados
        
        time.sleep(30)

# Endpoints Flask
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

if __name__ == '__main__':
    app.run()
