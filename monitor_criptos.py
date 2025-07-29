# monitor_criptos.py
import os
import requests
from flask import Flask
from datetime import datetime, timedelta
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import numpy as np
import re

# 1. Configuración explícita de la aplicación Flask
app = Flask(__name__)
application = app  # Alias crítico para Render

print("✅ Flask app configurada correctamente")

# [Resto del código permanece IGUAL...]

# 2. Asegurar el punto de entrada correcto
if __name__ == "__main__":
    print("🚀 Iniciando servidor de desarrollo...")
    app.run(host="0.0.0.0", port=10000)
else:
    print("⚡ Aplicación lista para producción con Gunicorn")

# Configuración de conexiones
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

print("🔍 Verificando variables de entorno...")
print(f"SUPABASE_URL: {'✅' if SUPABASE_URL else '❌'}")
print(f"SUPABASE_KEY: {'✅' if SUPABASE_KEY else '❌'}")
print(f"TELEGRAM_BOT_TOKEN: {'✅' if TELEGRAM_BOT_TOKEN else '❌'}")
print(f"TELEGRAM_CHAT_ID: {'✅' if TELEGRAM_CHAT_ID else '❌'}")
print(f"CMC_API_KEY: {'✅' if CMC_API_KEY else '❌'}")

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Conexión a Supabase establecida")
except Exception as e:
    print(f"❌ Error conectando a Supabase: {e}")
    supabase = None

# Constantes
MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]
INTERVALO_RSI = 14
HORAS_HISTORICO = 24

# --- Funciones Auxiliares ---
def ahora_madrid():
    return datetime.now(ZoneInfo("Europe/Madrid"))

def formatear_fecha(fecha):
    return fecha.strftime("%d/%m/%Y %H:%M")

def parsear_fecha_supabase(fecha_str):
    """Conversión robusta de fecha desde Supabase"""
    print(f"🔧 Parseando fecha: {fecha_str}")
    try:
        # Normalizar formato de fecha
        fecha_str = re.sub(r'\.(\d{1,6})\d*', r'.\1', fecha_str)
        
        # Manejar diferentes formatos de zona horaria
        if fecha_str.endswith('Z'):
            fecha_str = fecha_str[:-1] + '+00:00'
        elif '+' not in fecha_str and 'Z' not in fecha_str:
            fecha_str += '+00:00'
            
        dt = datetime.fromisoformat(fecha_str)
        print(f"📅 Fecha parseada: {dt}")
        return dt.astimezone(ZoneInfo("Europe/Madrid"))
    except Exception as e:
        print(f"❌ Error al parsear fecha {fecha_str}: {e}")
        return None

# --- Cálculo RSI ---
def calcular_rsi(cierres: np.ndarray, periodo: int = INTERVALO_RSI) -> float:
    print("🧮 Calculando RSI...")
    if len(cierres) < periodo + 1:
        print(f"⚠️ Datos insuficientes para RSI: {len(cierres)}/{periodo+1}")
        return None
    
    try:
        deltas = np.diff(cierres)
        ganancia = np.where(deltas > 0, deltas, 0)
        perdida = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(ganancia[:periodo])
        avg_loss = np.mean(perdida[:periodo])
        
        for i in range(periodo, len(ganancia)):
            avg_gain = (avg_gain * (periodo - 1) + ganancia[i]) / periodo
            avg_loss = (avg_loss * (periodo - 1) + perdida[i]) / periodo
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = round(100 - (100 / (1 + rs)), 2)
        print(f"📊 RSI calculado: {rsi}")
        return rsi
    except Exception as e:
        print(f"❌ Error en cálculo RSI: {e}")
        return None

# --- Manejo de Datos ---
def obtener_precios_historicos(nombre: str):
    print(f"\n📂 Obteniendo históricos para {nombre}")
    try:
        fecha_minima = ahora_madrid() - timedelta(hours=HORAS_HISTORICO)
        print(f"⏳ Fecha mínima: {fecha_minima}")
        
        query = supabase.table("precios").select(
            "precio, fecha"
        ).eq(
            "nombre", nombre
        ).gte(
            "fecha", fecha_minima.isoformat()
        ).order(
            "fecha", desc=True
        )
        
        print("🔍 Ejecutando query en Supabase...")
        response = query.execute()
        print("✅ Query ejecutada")
        
        datos = response.data
        print(f"📊 Registros obtenidos: {len(datos)}")
        
        if not datos:
            print("⚠️ No hay datos históricos")
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
                print(f"➕ Añadido precio: {registro['precio']} @ {fecha_registro}")
                
            if len(precios_filtrados) >= INTERVALO_RSI + 1:
                break
        
        # Ordenar de más antiguo a más reciente para el cálculo RSI
        precios_filtrados.reverse()
        print(f"📈 Precios filtrados: {len(precios_filtrados)}/{INTERVALO_RSI+1}")
        
        return np.array(precios_filtrados) if len(precios_filtrados) >= INTERVALO_RSI + 1 else None
        
    except Exception as e:
        print(f"❌ Error al obtener histórico {nombre}: {e}")
        return None

def obtener_precios_actuales():
    print("\n🔄 Obteniendo precios actuales de CoinMarketCap")
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    params = {"symbol": ",".join(MONEDAS), "convert": "EUR"}
    
    try:
        print("🌍 Realizando request a API...")
        r = requests.get(url, headers=headers, params=params)
        r.raise_for_status()
        print("✅ Respuesta recibida")
        
        data = r.json()["data"]
        precios = {m: round(data[m]["quote"]["EUR"]["price"], 8) for m in MONEDAS}
        print("📊 Precios actuales:", precios)
        return precios
    except Exception as e:
        print(f"❌ Error al obtener precios: {e}")
        return None

def insertar_precio(nombre, precio, rsi=None):
    print(f"\n💾 Insertando registro para {nombre}")
    try:
        registro = {
            "nombre": nombre,
            "precio": precio,
            "rsi": rsi,
            "fecha": ahora_madrid().isoformat()
        }
        print("📝 Registro a insertar:", registro)
        
        resultado = supabase.table("precios").insert(registro).execute()
        print("✅ Registro insertado correctamente")
        return resultado
    except Exception as e:
        print(f"❌ Error al insertar precio: {e}")
        return None

# --- Mensajes ---
def consejo_rsi(rsi):
    if rsi is None:
        return "Calculando RSI... (más datos necesarios)"
    elif rsi > 70:
        return "🔴 RSI alto, considerar vender"
    elif rsi < 30:
        return "🟢 RSI bajo, considerar comprar"
    else:
        return "🟡 Neutral, mantener posición"

def enviar_telegram(mensaje):
    print("\n📤 Enviando mensaje a Telegram")
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "HTML"
        }
        print("📩 Mensaje a enviar:", mensaje)
        
        response = requests.post(url, data=data)
        response.raise_for_status()
        print("✅ Mensaje enviado correctamente")
    except Exception as e:
        print(f"❌ Error al enviar Telegram: {e}")

# --- Endpoints ---
@app.route("/")
def home():
    print("\n🏠 Endpoint raíz accedido")
    return "Bot de Monitoreo Cripto - Operativo"

@app.route("/resumen")
def resumen():
    print("\n📊 Endpoint /resumen accedido")
    print("🔍 Obteniendo precios actuales...")
    precios = obtener_precios_actuales()
    
    if not precios:
        mensaje = "⚠️ No se pudieron obtener los precios actuales"
        print(mensaje)
        enviar_telegram(mensaje)
        return "Error al obtener precios", 500
    
    mensaje = "<b>📊 Resumen Criptomonedas</b>\n\n"
    ahora = ahora_madrid()
    print("⏰ Hora actual:", ahora)
    
    for moneda in MONEDAS:
        print(f"\n🔍 Procesando {moneda}...")
        precio = precios[moneda]
        print(f"💰 Precio actual: {precio}")
        
        historicos = obtener_precios_historicos(moneda)
        
        if historicos is None:
            rsi = None
            print(f"⚠️ No hay suficientes datos históricos para {moneda}")
            mensaje += f"<b>{moneda}:</b> {precio:,.8f} €\nℹ️ {consejo_rsi(rsi)}\n\n"
        else:
            print(f"📈 Datos históricos: {len(historicos)} puntos")
            rsi = calcular_rsi(historicos)
            mensaje += f"<b>{moneda}:</b> {precio:,.8f} €\n📈 RSI: {rsi:.2f} → {consejo_rsi(rsi)}\n\n"
        
        resultado = insertar_precio(moneda, precio, rsi)
        print(f"✅ {moneda} procesado correctamente")
    
    mensaje += f"🔄 <i>Actualizado: {formatear_fecha(ahora)} (Hora Madrid)</i>"
    print("\n📨 Enviando resumen completo a Telegram")
    enviar_telegram(mensaje)
    return "Resumen enviado", 200

if __name__ == "__main__":
    print("\n🚀 Iniciando aplicación...")
    app.run(host="0.0.0.0", port=10000)
