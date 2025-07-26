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

# Helper para fechas
def ahora():
    return datetime.datetime.now(ZONA_HORARIA)

def str_a_datetime(fecha_str):
    naive = datetime.datetime.strptime(fecha_str, '%Y-%m-%d %H:%M:%S')
    return ZONA_HORARIA.localize(naive)

# Manejo de histórico
def cargar_historico():
    try:
        if os.path.exists(HISTORICO_FILE):
            with open(HISTORICO_FILE, 'r') as f:
                data = json.load(f)
                for cripto, historico in data.items():
                    precios_historicos[cripto] = [
                        {"fecha": str_a_datetime(item["fecha"]), "precio": item["precio"]}
                        for item in historico
                    ]
        print("[INFO] Histórico cargado")
    except Exception as e:
        print(f"[ERROR] Cargando histórico: {str(e)}")

def guardar_historico():
    try:
        # Convertir datetime a string antes de guardar
        to_save = {
            cripto: [
                {"fecha": item["fecha"].strftime('%Y-%m-%d %H:%M:%S'), "precio": item["precio"]}
                for item in historico
            ]
            for cripto, historico in precios_historicos.items()
        }
        with open(HISTORICO_FILE, 'w') as f:
            json.dump(to_save, f)
    except Exception as e:
        print(f"[ERROR] Guardando histórico: {str(e)}")

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
            fecha_actual = ahora()
            
            # Registrar precio
            precios_historicos[cripto].append({
                "fecha": fecha_actual,
                "precio": precio
            })
            precios_actuales[cripto] = precio
            
            # Limpiar histórico antiguo
            limite = fecha_actual - datetime.timedelta(days=HISTORICO_DIAS)
            precios_historicos[cripto] = [
                p for p in precios_historicos[cripto] 
                if p["fecha"] > limite
            ]
            
        guardar_historico()
        return True
    except Exception as e:
        print(f"[ERROR] Obteniendo precios: {str(e)}")
        return False

# Análisis técnico
def calcular_media(cripto):
    historico = precios_historicos.get(cripto, [])
    if not historico:
        return None
    return sum(p["precio"] for p in historico) / len(historico)

def calcular_rsi(cripto, periodo=14):
    historico = precios_historicos.get(cripto, [])
    if len(historico) < periodo + 1:
        return None
        
    precios = [p["precio"] for p in historico[-periodo-1:]]
    cambios = [precios[i] - precios[i-1] for i in range(1, len(precios))]
    
    ganancias = sum(c for c in cambios if c > 0) / periodo
    perdidas = abs(sum(c for c in cambios if c < 0)) / periodo
    
    rs = ganancias / (perdidas or 0.0001)
    return 100 - (100 / (1 + rs))

# Generación de mensajes
def generar_mensaje_variacion(precio, media):
    if media is None or precio is None:
        return ""
    
    cambio = ((precio - media) / media) * 100
    abs_cambio = abs(cambio)
    
    if abs_cambio < 2:
        return ""
    elif cambio > 5:
        return f"🚀 +{abs_cambio:.1f}% (7d)"
    elif cambio > 2:
        return f"📈 +{abs_cambio:.1f}% (7d)"
    elif cambio < -5:
        return f"⚠️ -{abs_cambio:.1f}% (7d)"
    elif cambio < -2:
        return f"📉 -{abs_cambio:.1f}% (7d)"
    else:
        return "➡️ Estable"

def generar_consejo_rsi(rsi):
    if rsi is None:
        return "🔍 Sin datos RSI"
    elif rsi < 30:
        return "🔥 COMPRAR (sobrevendido)"
    elif rsi > 70:
        return "⚠️ VENDER (sobrecomprado)"
    elif rsi > 65:
        return "🔍 Cuidado (RSI alto)"
    elif rsi < 35:
        return "🔍 Oportunidad (RSI bajo)"
    else:
        return "👌 Neutral"

def obtener_resumen():
    if not obtener_precios():
        return "⚠️ Error obteniendo precios. Intentando nuevamente..."
    
    mensaje = "📊 *Resumen Cripto* 📊\n\n"
    for cripto in CRIPTOS:
        precio = precios_actuales.get(cripto)
        media = calcular_media(cripto)
        rsi = calcular_rsi(cripto)
        
        # Formatear valores
        precio_str = f"{precio:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".") if precio else "N/A"
        rsi_str = f"{rsi:.1f}" if rsi else "N/A"
        variacion = generar_mensaje_variacion(precio, media)
        consejo = generar_consejo_rsi(rsi)
        
        mensaje += (
            f"💰 *{cripto}*: {precio_str}\n"
            f"📊 RSI: {rsi_str} | {consejo}\n"
            f"{variacion}\n\n"
        )

    mensaje += f"🔄 {ahora().strftime('%d/%m %H:%M')}"
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
        print(f"[ERROR] Enviando mensaje: {str(e)}")

# Tareas programadas
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
        return f"Error: {str(e)}"

# Inicialización
cargar_historico()
atexit.register(guardar_historico)

if ENVIAR_RESUMEN_DIARIO:
    threading.Thread(target=tarea_monitor, daemon=True).start()
