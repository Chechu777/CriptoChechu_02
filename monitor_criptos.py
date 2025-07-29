import os
import requests
from flask import Flask
from datetime import datetime, timedelta
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import numpy as np
import re  # Nueva importación para manejo de fechas

# Configuración
app = Flask(__name__)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]
INTERVALO_RSI = 14
HORAS_HISTORICO = 24

# --- Funciones Auxiliares Mejoradas ---
def ahora_madrid():
    return datetime.now(ZoneInfo("Europe/Madrid"))

def formatear_fecha(fecha):
    return fecha.strftime("%d/%m/%Y %H:%M")

def parsear_fecha_supabase(fecha_str):
    """Conversión robusta de fecha desde Supabase"""
    try:
        # Eliminar microsegundos si son demasiado largos
        fecha_str = re.sub(r'\.(\d{1,6})\d*', r'.\1', fecha_str)
        
        # Manejar formato con o sin 'Z' al final
        if fecha_str.endswith('Z'):
            fecha_str = fecha_str[:-1] + '+00:00'
        elif '+' not in fecha_str and 'Z' not in fecha_str:
            fecha_str += '+00:00'
            
        dt = datetime.fromisoformat(fecha_str)
        return dt.astimezone(ZoneInfo("Europe/Madrid"))
    except Exception as e:
        print(f"Error al parsear fecha {fecha_str}: {e}")
        return None

# [Resto del código permanece igual hasta obtener_precios_historicos]

def obtener_precios_historicos(nombre: str):
    try:
        fecha_minima = ahora_madrid() - timedelta(hours=HORAS_HISTORICO)
        response = supabase.table("precios").select(
            "precio, fecha"
        ).eq(
            "nombre", nombre
        ).gte(
            "fecha", fecha_minima.isoformat()
        ).order(
            "fecha", desc=True  # Orden descendente para obtener los más recientes primero
        ).execute()
        
        datos = response.data
        if not datos:
            return None
            
        # Procesar registros desde el más reciente al más antiguo
        precios_filtrados = []
        ultima_hora = None
        
        for registro in datos:
            fecha_registro = parsear_fecha_supabase(registro["fecha"])
            if not fecha_registro:
                continue
                
            if ultima_hora is None or (ultima_hora - fecha_registro) >= timedelta(minutes=55):
                precios_filtrados.append(registro["precio"])
                ultima_hora = fecha_registro
                
            if len(precios_filtrados) >= INTERVALO_RSI + 1:
                break  # Tenemos suficientes datos
        
        # Ordenar de más antiguo a más reciente para el cálculo RSI
        precios_filtrados.reverse()
        return np.array(precios_filtrados) if len(precios_filtrados) >= INTERVALO_RSI + 1 else None
        
    except Exception as e:
        print(f"Error al obtener histórico {nombre}: {e}")
        return None

# [Resto del código permanece igual]
