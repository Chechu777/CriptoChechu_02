import os
import requests
from flask import Flask
from datetime import datetime, timedelta
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import numpy as np
import re
from dateutil.parser import isoparse  # Mejor parser de fechas

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

# --- Funciones Mejoradas ---
def ahora_madrid():
    return datetime.now(ZoneInfo("Europe/Madrid"))

def formatear_fecha(fecha):
    return fecha.strftime("%d/%m/%Y %H:%M")

def parsear_fecha_supabase(fecha_str):
    """Conversión ultra-robusta de fechas"""
    try:
        # Eliminar microsegundos si existen
        if '.' in fecha_str:
            partes = fecha_str.split('.')
            fecha_str = partes[0] + ('.' + partes[1][:6] if len(partes) > 1 else '')
        
        # Parsear con dateutil que es más tolerante
        dt = isoparse(fecha_str)
        return dt.astimezone(ZoneInfo("Europe/Madrid"))
    except Exception as e:
        print(f"⚠️ No se pudo parsear fecha {fecha_str}, usando hora actual. Error: {e}")
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
        ).limit(INTERVALO_RSI * 3).execute()  # Limitar para eficiencia
        
        datos = response.data
        if not datos:
            return None
            
        # Filtrar por intervalo y parsear fechas
        precios_filtrados = []
        ultima_hora = None
        
        for registro in sorted(datos, key=lambda x: x["fecha"]):  # Orden ascendente
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

# [Resto de funciones permanecen igual...]

# --- Endpoints Mejorados ---
@app.route("/")
def home():
    return "Bot de Monitoreo Cripto - Operativo", 200

@app.route("/health")
def health_check():
    try:
        # Verificar conexiones esenciales
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
