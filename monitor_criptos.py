import os
import requests
from flask import Flask, request
from datetime import datetime, timedelta
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import numpy as np

# Configuración inicial
app = Flask(__name__)

# Configuración de conexiones
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

# Constantes
MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]
INTERVALO_RSI = 14  # Periodo estándar para cálculo RSI
HORAS_HISTORICO = 24  # Ventana de tiempo para filtrar datos (24 horas)
MINUTOS_INTERVALO = 55  # Mínimo de minutos entre registros para considerarlos válidos

# --- Funciones de Utilidad ---
def ahora_madrid():
    """Devuelve la fecha/hora actual en zona horaria de Madrid"""
    return datetime.now(ZoneInfo("Europe/Madrid"))

def formatear_fecha(fecha: datetime) -> str:
    """Formatea fecha para mostrar en mensajes"""
    return fecha.strftime("%d/%m/%Y %H:%M")

# --- Cálculo de RSI Mejorado ---
def calcular_rsi(cierres: np.ndarray, periodo: int = INTERVALO_RSI) -> float:
    """
    Calcula el RSI usando suavizado exponencial (como TradingView)
    Args:
        cierres: Array de precios de cierre ordenados de más antiguo a más reciente
        periodo: Número de períodos a considerar (default 14)
    Returns:
        Valor RSI redondeado a 2 decimales
    """
    if len(cierres) < periodo + 1:
        return None
    
    deltas = np.diff(cierres)
    ganancias = np.where(deltas > 0, deltas, 0)
    perdidas = np.where(deltas < 0, -deltas, 0)
    
    # Primera media es SMA
    avg_gain = np.mean(ganancias[:periodo])
    avg_loss = np.mean(perdidas[:periodo])
    
    # Suavizado exponencial para el resto
    for i in range(periodo, len(ganancias)):
        avg_gain = (avg_gain * (periodo - 1) + ganancias[i]) / periodo
        avg_loss = (avg_loss * (periodo - 1) + perdidas[i]) / periodo
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

# --- Manejo de Datos ---
def obtener_precios_actuales() -> dict:
    """Obtiene precios actuales desde CoinMarketCap API"""
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    params = {"symbol": ",".join(MONEDAS), "convert": "EUR"}
    
    try:
        response = requests.get(
            "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest",
            headers=headers,
            params=params
        )
        response.raise_for_status()
        
        data = response.json()["data"]
        return {
            m: round(data[m]["quote"]["EUR"]["price"], 8)
            for m in MONEDAS
        }
    except Exception as e:
        print(f"Error API CoinMarketCap: {e}")
        return None

def obtener_historicos_filtrados(nombre: str) -> np.ndarray:
    """
    Obtiene precios históricos filtrados por intervalo de ~1 hora
    Args:
        nombre: Nombre de la criptomoneda (ej: "BTC")
    Returns:
        Array numpy con precios ordenados de más antiguo a más reciente
    """
    try:
        # Calculamos fecha mínima (ahora - HORAS_HISTORICO)
        fecha_minima = ahora_madrid() - timedelta(hours=HORAS_HISTORICO)
        
        # Consulta a Supabase
        response = supabase.table("precios")\
            .select("precio, fecha")\
            .eq("nombre", nombre)\
            .gte("fecha", fecha_minima.isoformat())\
            .order("fecha", desc=False)\  # Orden ascendente para cálculo
            .execute()
        
        datos = response.data
        if not datos:
            return None
            
        # Filtramos registros con intervalo ~1h
        precios_filtrados = []
        ultima_hora = None
        
        for registro in datos:
            fecha_registro = datetime.fromisoformat(registro["fecha"])
            
            if (ultima_hora is None or 
                (fecha_registro - ultima_hora) >= timedelta(minutes=MINUTOS_INTERVALO)):
                precios_filtrados.append(registro["precio"])
                ultima_hora = fecha_registro
        
        return np.array(precios_filtrados[-INTERVALO_RSI-1:])  # Necesitamos n+1 puntos para RSI
        
    except Exception as e:
        print(f"Error al obtener históricos de {nombre}: {e}")
        return None

def insertar_registro(nombre: str, precio: float, rsi: float = None):
    """Inserta un nuevo registro en la base de datos"""
    try:
        supabase.table("precios").insert({
            "nombre": nombre,
            "precio": precio,
            "rsi": rsi,
            "fecha": ahora_madrid().isoformat()
        }).execute()
    except Exception as e:
        print(f"Error al insertar registro para {nombre}: {e}")

# --- Generación de Mensajes ---
def generar_consejo_rsi(rsi: float) -> str:
    """Genera recomendación basada en el valor RSI"""
    if rsi is None:
        return "Calculando RSI... (más datos necesarios)"
    elif rsi > 70:
        return "🔴 RSI alto - Considerar tomar ganancias"
    elif rsi < 30:
        return "🟢 RSI bajo - Oportunidad de compra"
    else:
        return "🟡 RSI neutral - Esperar señal más clara"

def enviar_mensaje_telegram(mensaje: str):
    """Envía mensaje al chat de Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "HTML"
        }
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error al enviar mensaje a Telegram: {e}")

# --- Endpoints ---
@app.route("/")
def home():
    return "Bot de Monitoreo de Criptomonedas - Operativo"

@app.route("/resumen")
def generar_resumen():
    """Endpoint principal que genera el resumen y envía a Telegram"""
    # Obtener precios actuales
    precios_actuales = obtener_precios_actuales()
    if not precios_actuales:
        return "Error al obtener precios actuales", 500
    
    # Construir mensaje
    mensaje = "<b>📊 Resumen Criptomonedas</b>\n\n"
    ahora = ahora_madrid()
    
    for moneda in MONEDAS:
        precio = precios_actuales[moneda]
        historicos = obtener_historicos_filtrados(moneda)
        
        if historicos is None or len(historicos) < INTERVALO_RSI + 1:
            rsi = None
            mensaje += (
                f"<b>{moneda}:</b> {precio:,.8f} €\n"
                f"ℹ️ {generar_consejo_rsi(rsi)}\n\n"
            )
        else:
            rsi = calcular_rsi(historicos)
            mensaje += (
                f"<b>{moneda}:</b> {precio:,.8f} €\n"
                f"📈 RSI {rsi:.2f} - {generar_consejo_rsi(rsi)}\n\n"
            )
        
        # Insertar nuevo registro (con o sin RSI)
        insertar_registro(moneda, precio, rsi)
    
    # Pie del mensaje
    mensaje += (
        f"\n🔄 <i>Actualizado: {formatear_fecha(ahora)} (Hora Madrid)</i>\n"
        f"⏱ <i>Intervalo: {INTERVALO_RSI} períodos</i>"
    )
    
    # Enviar mensaje
    enviar_mensaje_telegram(mensaje)
    return "Resumen generado y enviado", 200

# --- Ejecución ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
