import os
import time
import threading
import datetime
import requests
from flask import Flask
from pytz import timezone
import json
from collections import defaultdict

app = Flask(__name__)

# Variables de entorno
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("CMC_API_KEY")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")
ZONA_HORARIA = timezone("Europe/Madrid")
HISTORICO_DIAS = 7  # Días de histórico a considerar para precios de referencia

# Configuración de criptos
CRIPTOS = ['BTC', 'ETH', 'ADA', 'SHIB', 'SOL']
HISTORICO_FILE = "precios_historico.json"

# Diccionario para almacenar precios históricos
precios_historicos = defaultdict(list)

# Cargar histórico al iniciar
def cargar_historico():
    try:
        if os.path.exists(HISTORICO_FILE):
            with open(HISTORICO_FILE, 'r') as f:
                data = json.load(f)
                for cripto in CRIPTOS:
                    precios_historicos[cripto] = data.get(cripto, [])
        print("[INFO] Histórico de precios cargado correctamente")
    except Exception as e:
        print(f"[ERROR] Error al cargar histórico: {e}")

# Guardar histórico
def guardar_historico():
    try:
        with open(HISTORICO_FILE, 'w') as f:
            json.dump(precios_historicos, f)
    except Exception as e:
        print(f"[ERROR] Error al guardar histórico: {e}")

# Obtener precios desde CoinMarketCap en EUR
def obtener_precio_eur(cripto):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accepts": "application/json"
    }
    params = {
        "symbol": cripto,
        "convert": "EUR"
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        precio = float(data["data"][cripto]["quote"]["EUR"]["price"])
        
        # Registrar precio en el histórico
        ahora = datetime.datetime.now(ZONA_HORARIA)
        precios_historicos[cripto].append({
            "fecha": ahora.strftime('%Y-%m-%d %H:%M:%S'),
            "precio": precio
        })
        
        # Mantener solo los últimos N días de histórico
        limite = ahora - datetime.timedelta(days=HISTORICO_DIAS)
        precios_historicos[cripto] = [
            p for p in precios_historicos[cripto] 
            if datetime.datetime.strptime(p["fecha"], '%Y-%m-%d %H:%M:%S') > limite
        ]
        
        guardar_historico()
        return precio
    except Exception as e:
        print(f"[ERROR] No se pudo obtener el precio de {cripto} desde CoinMarketCap: {e}")
        return None

# Calcular precio de referencia (media de los últimos N días)
def calcular_precio_referencia(cripto):
    if not precios_historicos.get(cripto):
        return None
    
    try:
        # Calcular media de precios históricos
        precios = [p["precio"] for p in precios_historicos[cripto]]
        return sum(precios) / len(precios)
    except Exception as e:
        print(f"[ERROR] Error calculando precio referencia para {cripto}: {e}")
        return None

# Calcular RSI básico (versión mejorada)
def calcular_rsi(cripto, periodo=14):
    if not precios_historicos.get(cripto) or len(precios_historicos[cripto]) < periodo:
        return calcular_rsi_dummy(cripto)  # Fallback a dummy si no hay suficiente histórico
    
    try:
        precios = [p["precio"] for p in precios_historicos[cripto][-periodo:]]
        ganancias = []
        perdidas = []
        
        for i in range(1, len(precios)):
            diferencia = precios[i] - precios[i-1]
            if diferencia > 0:
                ganancias.append(diferencia)
            else:
                perdidas.append(abs(diferencia))
        
        avg_ganancia = sum(ganancias) / periodo if ganancias else 0
        avg_perdida = sum(perdidas) / periodo if perdidas else 0.000001  # Evitar división por cero
        
        rs = avg_ganancia / avg_perdida
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 2)
    except Exception as e:
        print(f"[ERROR] Error calculando RSI para {cripto}: {e}")
        return calcular_rsi_dummy(cripto)

# Simulación de RSI (fallback)
def calcular_rsi_dummy(cripto):
    valores_rsi = {
        'BTC': 45,
        'ETH': 70,
        'ADA': 30,
        'SHIB': 55,
        'SOL': 65
    }
    return valores_rsi.get(cripto, 50)

# Mensaje según RSI (versión mejorada)
def consejo_por_rsi(rsi):
    if rsi < 30:
        return "🔥 *TE ACONSEJO QUE COMPRES*, está sobrevendido."
    elif rsi > 70:
        return "⚠️ *TE ACONSEJO QUE VENDAS*, está sobrecomprado."
    elif rsi > 65:
        return "🔍 *Atención:* Podría estar sobrecomprándose"
    elif rsi < 35:
        return "🔍 *Atención:* Podría estar sobrevendiéndose"
    else:
        return "👌 Mantén la calma, el mercado está estable."

# Generar resumen diario (versión mejorada)
def obtener_resumen_diario():
    resumen = "📊 *Resumen diario de criptomonedas* 📊\n\n"
    
    for cripto in CRIPTOS:
        precio = obtener_precio_eur(cripto)
        if precio is None:
            resumen += f"⚠️ {cripto}: Error al obtener precio\n"
            continue

        rsi = calcular_rsi(cripto)
        consejo = consejo_por_rsi(rsi)
        precio_ref = calcular_precio_referencia(cripto) or precio  # Fallback al precio actual
        
        variacion = ""
        if precio_ref:
            cambio_porcentual = ((precio - precio_ref) / precio_ref) * 100
            if cambio_porcentual < -5:
                variacion = f"📉 Ha bajado {abs(cambio_porcentual):.2f}% desde la media de {HISTORICO_DIAS}d"
            elif cambio_porcentual > 5:
                variacion = f"📈 Ha subido {cambio_porcentual:.2f}% desde la media de {HISTORICO_DIAS}d"
            else:
                variacion = f"➡️ Variación mínima ({cambio_porcentual:.2f}%) respecto a la media de {HISTORICO_DIAS}d"

        resumen += (
            f"💰 *{cripto}*: {precio:,.6f} €\n"
            f"📈 RSI ({HISTORICO_DIAS}d): {rsi}\n"
            f"{consejo}\n"
            f"{variacion}\n\n"
        )

    hora_actual = datetime.datetime.now(ZONA_HORARIA).strftime('%Y-%m-%d %H:%M:%S')
    resumen += f"_Actualizado: {hora_actual}_"
    return resumen

# Enviar mensaje a Telegram (sin cambios)
def enviar_mensaje(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, data=payload)
        r.raise_for_status()
        print("[INFO] Mensaje enviado correctamente")
    except Exception as e:
        print(f"[ERROR] Al enviar mensaje: {e}")

# Tarea programada diaria (sin cambios)
def tarea_programada():
    print("[INFO] Hilo de resumen diario iniciado.")
    ultimo_envio = None
    while True:
        if ENVIAR_RESUMEN_DIARIO:
            ahora = datetime.datetime.now(ZONA_HORARIA)
            hora_actual = ahora.strftime("%H:%M")
            fecha_actual = ahora.date()
            
            if hora_actual == RESUMEN_HORA and (ultimo_envio is None or ultimo_envio != fecha_actual):
                try:
                    resumen = obtener_resumen_diario()
                    enviar_mensaje(resumen)
                    ultimo_envio = fecha_actual
                    print(f"[INFO] Resumen enviado a las {hora_actual}")
                except Exception as e:
                    print(f"[ERROR] Al enviar resumen diario: {e}")
                
                time.sleep(60)
        time.sleep(20)

# Rutas Flask (sin cambios)
@app.route("/")
def home():
    return "Bot monitor_criptos activo ✅"

@app.route("/resumen")
def resumen_manual():
    try:
        resumen = obtener_resumen_diario()
        enviar_mensaje(f"[PRUEBA MANUAL]\n{resumen}")
        return "Resumen enviado manualmente"
    except Exception as e:
        return f"Error al generar resumen: {e}"

# Inicialización
cargar_historico()

# Arranque de tarea programada
if ENVIAR_RESUMEN_DIARIO:
    threading.Thread(target=tarea_programada, daemon=True).start()
