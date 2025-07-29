import os
import requests
from flask import Flask
from datetime import datetime, timedelta
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import numpy as np

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

# --- Funciones Auxiliares ---
def ahora_madrid():
    return datetime.now(ZoneInfo("Europe/Madrid"))

def formatear_fecha(fecha):
    return fecha.strftime("%d/%m/%Y %H:%M")

# --- Cálculo RSI ---
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
    
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

# --- Manejo de Datos ---
def obtener_precios_historicos(nombre: str):
    try:
        fecha_minima = ahora_madrid() - timedelta(hours=24)
        response = supabase.table("precios").select(
            "precio, fecha"
        ).eq(
            "nombre", nombre
        ).gte(
            "fecha", fecha_minima.isoformat()
        ).order(
            "fecha", desc=False
        ).execute()
        
        datos = response.data
        if not datos:
            return None
            
        # Filtrar para intervalo ~1h
        precios_filtrados = []
        ultima_hora = None
        
        for registro in datos:
            fecha_registro = datetime.fromisoformat(registro["fecha"])
            if ultima_hora is None or (fecha_registro - ultima_hora) >= timedelta(minutes=55):
                precios_filtrados.append(registro["precio"])
                ultima_hora = fecha_registro
        
        return np.array(precios_filtrados[-INTERVALO_RSI-1:])
    except Exception as e:
        print(f"Error al obtener histórico {nombre}: {e}")
        return None

def obtener_precios_actuales():
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    params = {"symbol": ",".join(MONEDAS), "convert": "EUR"}
    try:
        r = requests.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()["data"]
        return {m: round(data[m]["quote"]["EUR"]["price"], 8) for m in MONEDAS}
    except Exception as e:
        print(f"Error al obtener precios: {e}")
        return None

def insertar_precio(nombre, precio, rsi=None):
    try:
        supabase.table("precios").insert({
            "nombre": nombre,
            "precio": precio,
            "rsi": rsi,
            "fecha": ahora_madrid().isoformat()
        }).execute()
    except Exception as e:
        print(f"Error al insertar precio: {e}")

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
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
        requests.post(url, data=data)
    except Exception as e:
        print(f"Error al enviar Telegram: {e}")

# --- Endpoints ---
@app.route("/")
def home():
    return "Bot de Monitoreo Cripto - Operativo"

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
        
        if historicos is None or len(historicos) < INTERVALO_RSI + 1:
            rsi = None
            mensaje += f"<b>{moneda}:</b> {precio:,.8f} €\nℹ️ {consejo_rsi(rsi)}\n\n"
        else:
            rsi = calcular_rsi(historicos)
            mensaje += f"<b>{moneda}:</b> {precio:,.8f} €\n📈 RSI: {rsi:.2f} → {consejo_rsi(rsi)}\n\n"
        
        insertar_precio(moneda, precio, rsi)
    
    mensaje += f"🔄 <i>Actualizado: {formatear_fecha(ahora)} (Hora Madrid)</i>"
    enviar_telegram(mensaje)
    return "Resumen enviado", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
