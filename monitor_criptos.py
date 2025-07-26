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
HISTORICO_DIAS = 7
CRIPTOS = ['BTC', 'ETH', 'ADA', 'SHIB', 'SOL']
HISTORICO_FILE = "/tmp/precios_historico.json"

# Datos
precios_historicos = defaultdict(list)
precios_actuales = {}

# Helper para fechas (todas las operaciones con zona horaria)
def ahora():
    return datetime.datetime.now(ZONA_HORARIA)

def str_a_datetime(fecha_str):
    dt = datetime.datetime.strptime(fecha_str, '%Y-%m-%d %H:%M:%S')
    return ZONA_HORARIA.localize(dt)

# Manejo de histórico
def cargar_historico():
    try:
        if os.path.exists(HISTORICO_FILE):
            with open(HISTORICO_FILE, 'r') as f:
                data = json.load(f)
                for cripto, historico in data.items():
                    precios_historicos[cripto] = [
                        {"fecha": item["fecha"], "precio": item["precio"]}  # Guardamos como string
                        for item in historico
                    ]
        print("[INFO] Histórico cargado correctamente")
    except Exception as e:
        print(f"[ERROR] Cargando histórico: {e}")

def guardar_historico():
    try:
        with open(HISTORICO_FILE, 'w') as f:
            json.dump({
                cripto: [
                    {"fecha": item["fecha"], "precio": item["precio"]}
                    for item in historico
                ]
                for cripto, historico in precios_historicos.items()
            }, f)
    except Exception as e:
        print(f"[ERROR] Guardando histórico: {e}")

def limpiar_historico():
    try:
        limite = (ahora() - datetime.timedelta(days=HISTORICO_DIAS)).strftime('%Y-%m-%d %H:%M:%S')
        for cripto in CRIPTOS:
            precios_historicos[cripto] = [
                p for p in precios_historicos[cripto]
                if p["fecha"] > limite
            ]
    except Exception as e:
        print(f"[ERROR] Limpiando histórico: {e}")

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
        
        limpiar_historico()
        guardar_historico()
        return True
    except Exception as e:
        print(f"[ERROR] Obteniendo precios: {e}")
        return False

# Análisis técnico
def calcular_media(cripto):
    historico = precios_historicos.get(cripto, [])
    if len(historico) < 1:
        return None
    return sum(p["precio"] for p in historico) / len(historico)

def calcular_rsi(cripto, periodo=14):
    historico = precios_historicos.get(cripto, [])
    if len(historico) < periodo + 1:
        return None
        
    precios = [p["precio"] for p in historico[-periodo-1:]]
    cambios = [precios[i] - precios[i-1] for i in range(1, len(precios))]
    
    avg_ganancia = sum(max(c, 0) for c in cambios) / periodo
    avg_perdida = abs(sum(min(c, 0) for c in cambios)) / periodo
    
    rs = avg_ganancia / (avg_perdida or 0.0001)
    return min(100, max(0, 100 - (100 / (1 + rs))))

# Generación de mensajes
def generar_mensaje_cripto(cripto):
    precio = precios_actuales.get(cripto)
    media = calcular_media(cripto)
    rsi = calcular_rsi(cripto)
    
    # Formatear precio
    precio_str = "N/A"
    if precio is not None:
        precio_str = f"{precio:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    
    # Variación
    variacion = ""
    if media and precio:
        cambio = ((precio - media) / media) * 100
        if abs(cambio) > 5:
            direccion = "📈" if cambio > 0 else "📉"
            variacion = f"{direccion} {abs(cambio):.1f}% (media {HISTORICO_DIAS}d)"
    
    # Consejo RSI
    consejo = "🔍 Sin datos"
    if rsi is not None:
        if rsi < 30:
            consejo = "🔥 COMPRAR (sobrevendido)"
        elif rsi > 70:
            consejo = "⚠️ VENDER (sobrecomprado)"
        elif rsi > 65:
            consejo = "🔼 RSI alto"
        elif rsi < 35:
            consejo = "🔽 RSI bajo"
        else:
            consejo = "🟢 Neutral"
    
    rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
    
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

# Tareas programadas
def tarea_monitor():
    print("[INFO] Monitor iniciado")
    while True:
        ahora_local = ahora()
        
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
