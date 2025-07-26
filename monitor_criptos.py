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

# Variables de entorno
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("CMC_API_KEY")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")
ZONA_HORARIA = timezone("Europe/Madrid")
HISTORICO_DIAS = 7  # Días de histórico a considerar

# Configuración de criptos
CRIPTOS = ['BTC', 'ETH', 'ADA', 'SHIB', 'SOL']
HISTORICO_FILE = "/tmp/precios_historico.json"  # Usar /tmp en Render para permisos

# Diccionario para almacenar precios históricos
precios_historicos = defaultdict(list)
precios_actuales = {}

# Cargar histórico al iniciar
def cargar_historico():
    try:
        if os.path.exists(HISTORICO_FILE):
            with open(HISTORICO_FILE, 'r') as f:
                data = json.load(f)
                for cripto in CRIPTOS:
                    precios_historicos[cripto] = data.get(cripto, [])
        print("[INFO] Histórico de precios cargado")
    except Exception as e:
        print(f"[ERROR] Error al cargar histórico: {e}")

# Guardar histórico
def guardar_historico():
    try:
        with open(HISTORICO_FILE, 'w') as f:
            json.dump(precios_historicos, f)
    except Exception as e:
        print(f"[ERROR] Error al guardar histórico: {e}")

# Registrar precio en histórico
def registrar_precio(cripto, precio):
    try:
        ahora = datetime.datetime.now(ZONA_HORARIA)
        precios_historicos[cripto].append({
            "fecha": ahora.strftime('%Y-%m-%d %H:%M:%S'),
            "precio": precio
        })
        
        # Limitar histórico a los últimos N días
        limite = ahora - datetime.timedelta(days=HISTORICO_DIAS)
        precios_historicos[cripto] = [
            p for p in precios_historicos[cripto] 
            if datetime.datetime.strptime(p["fecha"], '%Y-%m-%d %H:%M:%S') > limite
        ]
        
        precios_actuales[cripto] = precio
        guardar_historico()
    except Exception as e:
        print(f"[ERROR] Error registrando precio: {e}")

# Obtener precios desde CoinMarketCap
def obtener_precios():
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    params = {"symbol": ",".join(CRIPTOS), "convert": "EUR"}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        
        for cripto in CRIPTOS:
            precio = float(data["data"][cripto]["quote"]["EUR"]["price"])
            registrar_precio(cripto, precio)
            
    except Exception as e:
        print(f"[ERROR] Error obteniendo precios: {e}")
        # Usar último precio conocido si hay error
        for cripto in CRIPTOS:
            if cripto not in precios_actuales:
                precios_actuales[cripto] = 0

# Calcular precio de referencia (media móvil)
def calcular_precio_referencia(cripto):
    if not precios_historicos.get(cripto):
        return None
    
    try:
        precios = [p["precio"] for p in precios_historicos[cripto]]
        return sum(precios) / len(precios)
    except:
        return None

# Calcular RSI mejorado
def calcular_rsi(cripto, periodo=14):
    if not precios_historicos.get(cripto) or len(precios_historicos[cripto]) < periodo:
        return None  # No hay suficientes datos
    
    try:
        precios = [p["precio"] for p in precios_historicos[cripto][-periodo:]]
        cambios = [precios[i] - precios[i-1] for i in range(1, len(precios))]
        
        ganancias = sum(cambio for cambio in cambios if cambio > 0) / periodo
        perdidas = abs(sum(cambio for cambio in cambios if cambio < 0)) / periodo
        
        rs = ganancias / (perdidas or 0.0001)  # Evitar división por cero
        return min(max(100 - (100 / (1 + rs)), 0), 100)  # Asegurar entre 0-100
    except:
        return None

# Generar mensaje de variación
def generar_variacion(precio, precio_ref):
    if not precio_ref:
        return ""
    
    cambio = ((precio - precio_ref) / precio_ref) * 100
    abs_cambio = abs(cambio)
    
    if abs_cambio < 2:
        return ""
    elif abs_cambio < 5:
        direccion = "📈" if cambio > 0 else "📉"
        return f"{direccion} Variación del {abs_cambio:.1f}% (media {HISTORICO_DIAS}d)"
    else:
        direccion = "🚀📈" if cambio > 0 else "⚠️📉"
        return f"{direccion} *Fuerte variación* del {abs_cambio:.1f}% (media {HISTORICO_DIAS}d)"

# Generar resumen diario
def obtener_resumen_diario():
    obtener_precios()  # Actualizar datos primero
    
    resumen = "📊 *Resumen Criptomonedas* 📊\n\n"
    for cripto in CRIPTOS:
        precio = precios_actuales.get(cripto, 0)
        precio_ref = calcular_precio_referencia(cripto)
        rsi = calcular_rsi(cripto)
        
        # Formatear valores
        precio_str = f"{precio:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        variacion = generar_variacion(precio, precio_ref) if precio_ref else ""
        
        # Consejo según RSI
        if rsi is None:
            consejo = "🔍 Datos insuficientes para RSI"
        elif rsi < 30:
            consejo = "🔥 *COMPRA* (RSI sobrevendido)"
        elif rsi > 70:
            consejo = "⚠️ *VENDE* (RSI sobrecomprado)"
        elif rsi > 65:
            consejo = "🔍 Posible sobrecompra (RSI alto)"
        elif rsi < 35:
            consejo = "🔍 Posible sobreventa (RSI bajo)"
        else:
            consejo = "👌 Mercado estable"
            
        rsi_str = f"{rsi:.1f}" if rsi else "N/A"
        
        resumen += (
            f"💰 *{cripto}*: {precio_str}\n"
            f"📊 RSI: {rsi_str} | {consejo}\n"
            f"{variacion}\n\n"
        )

    hora = datetime.datetime.now(ZONA_HORARIA).strftime('%d/%m %H:%M')
    resumen += f"🔄 Actualizado: {hora}"
    return resumen

# Enviar mensaje a Telegram
def enviar_mensaje(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("[INFO] Mensaje enviado")
    except Exception as e:
        print(f"[ERROR] Envío Telegram: {e}")

# Tarea programada
def tarea_programada():
    print("[INFO] Iniciando monitorización...")
    while True:
        ahora = datetime.datetime.now(ZONA_HORARIA)
        
        # Envío diario automático
        if ENVIAR_RESUMEN_DIARIO and ahora.strftime("%H:%M") == RESUMEN_HORA:
            try:
                enviar_mensaje(obtener_resumen_diario())
                time.sleep(61)  # Evitar duplicados
            except Exception as e:
                print(f"[ERROR] Envío automático: {e}")
        
        time.sleep(30)  # Revisar cada 30 segundos

# Endpoints Flask
@app.route("/")
def home():
    return "Bot Cripto Activo 🚀"

@app.route("/resumen")
def resumen_manual():
    try:
        resumen = obtener_resumen_diario()
        enviar_mensaje(f"🔔 *PRUEBA MANUAL*\n\n{resumen}")
        return "Resumen enviado"
    except Exception as e:
        return f"Error: {e}"

# Inicialización
cargar_historico()
atexit.register(guardar_historico)  # Guardar al salir

# Iniciar hilo de monitorización
if ENVIAR_RESUMEN_DIARIO:
    threading.Thread(target=tarea_programada, daemon=True).start()
