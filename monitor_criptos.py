import os
import requests
from flask import Flask
from datetime import datetime, timedelta
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import numpy as np
import re
from dateutil.parser import isoparse

# Configuración Flask
app = Flask(__name__)
application = app  # Alias para Render

# Configuración de conexiones
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

# Constantes
MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]
INTERVALO_RSI = 14
HORAS_HISTORICO = 48  # Ventana más amplia para asegurar datos
MINUTOS_ENTRE_REGISTROS = 55  # Intervalo mínimo entre registros

# Conexión a Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Funciones Auxiliares ---
def ahora_madrid():
    return datetime.now(ZoneInfo("Europe/Madrid"))

def formatear_fecha(fecha):
    return fecha.strftime("%d/%m/%Y %H:%M")

def parsear_fecha_supabase(fecha_str):
    """Conversión robusta de fechas desde Supabase"""
    try:
        if '.' in fecha_str:
            partes = fecha_str.split('.')
            fecha_str = partes[0] + ('.' + partes[1][:6] if len(partes) > 1 else '')
        
        dt = isoparse(fecha_str)
        return dt.astimezone(ZoneInfo("Europe/Madrid"))
    except Exception as e:
        print(f"⚠️ Error parseando fecha {fecha_str}, usando hora actual. Error: {e}")
        return ahora_madrid()

def calcular_rsi(cierres: np.ndarray, periodo: int = INTERVALO_RSI) -> float:
    if len(cierres) < periodo + 1:
        return None
    
    deltas = np.diff(cierres)
    ganancia = np.where(deltas > 0, deltas, 0)
    perdida = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(ganancia[:periodo])
    avg_loss = np.mean(perdida[:periodo])
    
    for i in range(periodo, len(ganancia)):
        avg_gain = (avg_gain * (periodo - 1) + ganancia[i]) / periodo
        avg_loss = (avg_loss * (periodo - 1) + perdida[i]) / periodo
    
    return 100.0 if avg_loss == 0 else round(100 - (100 / (1 + (avg_gain / avg_loss))), 2)

def obtener_precios_historicos(nombre: str):
    try:
        fecha_minima = ahora_madrid() - timedelta(hours=HORAS_HISTORICO)
        response = supabase.table("precios").select(
            "precio, fecha"
        ).eq("nombre", nombre
        ).gte("fecha", fecha_minima.isoformat()
        ).order("fecha", desc=True
        ).limit(INTERVALO_RSI * 3).execute()
        
        datos = response.data
        if not datos:
            return None
            
        precios_filtrados = []
        ultima_hora = None
        
        for registro in sorted(datos, key=lambda x: x["fecha"]):
            fecha = parsear_fecha_supabase(registro["fecha"])
            precio = float(registro["precio"])
            
            if (ultima_hora is None or 
                (fecha - ultima_hora) >= timedelta(minutes=MINUTOS_ENTRE_REGISTROS)):
                precios_filtrados.append(precio)
                ultima_hora = fecha
                
            if len(precios_filtrados) >= INTERVALO_RSI + 1:
                break
        
        return np.array(precios_filtrados[-INTERVALO_RSI-1:]) if len(precios_filtrados) >= INTERVALO_RSI+1 else None
    except Exception as e:
        print(f"Error al obtener históricos {nombre}: {e}")
        return None

def obtener_precios_actuales():
    try:
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        parametros = {
            'symbol': ','.join(MONEDAS),
            'convert': 'EUR'
        }
        headers = {
            'Accepts': 'application/json',
            'X-CMC_PRO_API_KEY': CMC_API_KEY
        }

        respuesta = requests.get(url, headers=headers, params=parametros)
        datos = respuesta.json()
        
        precios = {}
        for moneda in MONEDAS:
            precio = datos['data'][moneda]['quote']['EUR']['price']
            precios[moneda] = precio
        
        return precios
    except Exception as e:
        print(f"⚠️ Error al obtener precios: {e}")
        return None

import logging
from datetime import datetime

def insertar_precio(nombre: str, precio: float, rsi: float = None):
    try:
        fecha_db = ahora_madrid().strftime("%Y-%m-%d %H:%M:%S.%f")
        datos = {
            "nombre": nombre,
            "precio": float(precio),
            "rsi": float(rsi) if rsi else None,
            "fecha": fecha_db
        }
        
        logging.info(f"Insertando {nombre}: Precio={precio:.8f} | RSI={rsi or 'NULL'} | Fecha={fecha_db}")
        
        response = supabase.table("precios").insert(datos).execute()
        
        if response.data:
            logging.info(f"✅ Éxito - ID: {response.data[0].get('id', 'N/A')}")
        else:
            logging.warning(f"⚠️ Respuesta inesperada: {response}")
            
        return True
    except Exception as e:
        logging.error(f"🔥 Error en {nombre}: {str(e)}", exc_info=True)
        return False

def consejo_rsi(rsi: float) -> str:
    if rsi is None:
        return "🔄 Calculando..."
    elif rsi < 30:
        return "🔥 📉 OVERSOLD - Buen momento para COMPRAR"
    elif rsi > 70:
        return "🚨 📈 OVERBOUGHT - Considera VENDER"
    else:
        return "⚖️ Quieto chato, no hagas huevadas"

def enviar_telegram(mensaje: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': mensaje,
            'parse_mode': 'HTML'
        }
        requests.post(url, json=payload)
    except Exception as e:
        print(f"⚠️ Error al enviar a Telegram: {e}")

# --- Endpoints ---
@app.route("/")
def home():
    return "Bot de Monitoreo Cripto - Operativo", 200

@app.route("/health")
def health_check():
    try:
        supabase.table("precios").select("count", count='exact').limit(1).execute()
        return {
            "status": "healthy",
            "supabase": "connected",
            "timestamp": ahora_madrid().isoformat()
        }, 200
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}, 500

@app.route("/resumen")
def resumen():
    precios = obtener_precios_actuales()
    if not precios:
        return "Error al obtener precios", 500
    
    mensaje = "<b>📊 Resumen Criptomonedas</b>\n\n"
    ahora = ahora_madrid()
    
    for moneda in MONEDAS:
        precio = precios[moneda]
        historicos = obtener_precios_historicos(moneda)
        rsi = calcular_rsi(historicos) if historicos is not None else None
        
        mensaje += (
            f"<b>{moneda}:</b> {precio:,.8f} €\n"
            f"📈 RSI: {rsi if rsi else 'N/A'} - {consejo_rsi(rsi)}\n\n"
        )
        insertar_precio(moneda, precio, rsi)
    
    mensaje += f"🔄 <i>Actualizado: {formatear_fecha(ahora)} (Hora Madrid)</i>"
    enviar_telegram(mensaje)
    return "Resumen enviado", 200

def limpiar_datos_antiguos(dias=30):
    fecha_limite = (ahora_madrid() - timedelta(days=dias)).strftime("%Y-%m-%d")
    supabase.table("precios").delete().lt("fecha", fecha_limite).execute()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
