import os
import requests
import numpy as np
import pandas as pd
from flask import Flask
from datetime import datetime, timedelta
from supabase import create_client, Client
from zoneinfo import ZoneInfo
from dateutil.parser import isoparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

app = Flask(__name__)
application = app

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]
INTERVALO_RSI = 14
HORAS_HISTORICO = 48
MINUTOS_ENTRE_REGISTROS = 55

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def ahora_madrid():
    return datetime.now(ZoneInfo("Europe/Madrid"))

def formatear_fecha(fecha):
    return fecha.strftime("%d/%m/%Y %H:%M")

def parsear_fecha_supabase(fecha_str):
    try:
        if '.' in fecha_str:
            partes = fecha_str.split('.')
            fecha_str = partes[0] + ('.' + partes[1][:6] if len(partes) > 1 else '')
        dt = isoparse(fecha_str)
        return dt.astimezone(ZoneInfo("Europe/Madrid"))
    except Exception as e:
        logging.error(f"Error parseando fecha {fecha_str}: {str(e)}")
        return ahora_madrid()

def calcular_confianza(historico, rsi, macd, macd_signal):
    if rsi is None or macd is None or macd_signal is None:
        return 1
    confianza = 1
    if rsi < 30 and macd > macd_signal:
        confianza = 5
    elif rsi > 70 and macd < macd_signal:
        confianza = 5
    elif rsi < 30 or rsi > 70:
        confianza = 4
    elif (30 <= rsi <= 35 and macd > macd_signal) or (65 <= rsi <= 70 and macd < macd_signal):
        confianza = 3
    elif 40 <= rsi <= 60:
        confianza = 2
    return confianza

def calcular_rsi(cierres, periodo: int = INTERVALO_RSI) -> float:
    if cierres is None:
        return None
    try:
        cierres = np.array(cierres, dtype=np.float64)
        if len(cierres) < periodo + 1:
            return None
        deltas = np.diff(cierres)
        if np.all(deltas == 0):
            return 50.0
        ganancias = np.maximum(deltas, 0)
        perdidas = np.maximum(-deltas, 0)
        avg_gain = np.mean(ganancias[:periodo])
        avg_loss = np.mean(perdidas[:periodo])
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(max(0, min(100, rsi)), 2)
    except Exception as e:
        logging.error(f"Error calculando RSI: {str(e)}")
        return None

def calcular_macd(cierres, periodo_largo=26, periodo_corto=12, periodo_senal=9):
    try:
        if len(cierres) < periodo_largo + periodo_senal:
            return None, None, None
        cierres = np.array(cierres, dtype=np.float64)
        def calcular_ema(data, period):
            if len(data) < period:
                return np.mean(data)
            alpha = 2 / (period + 1)
            ema = np.zeros_like(data)
            ema[0] = data[0]
            for i in range(1, len(data)):
                ema[i] = alpha * data[i] + (1 - alpha) * ema[i-1]
            return ema[-1]
        ema_corta = calcular_ema(cierres, periodo_corto)
        ema_larga = calcular_ema(cierres, periodo_largo)
        macd_line = ema_corta - ema_larga
        macd_values = [calcular_ema(cierres[:i+1], periodo_corto) - calcular_ema(cierres[:i+1], periodo_largo) for i in range(periodo_corto, len(cierres))]
        signal_line = calcular_ema(np.array(macd_values), periodo_senal) if len(macd_values) >= periodo_senal else macd_line
        histograma = macd_line - signal_line
        return macd_line, signal_line, histograma
    except Exception as e:
        logging.error(f"Error calculando MACD: {str(e)}")
        return None, None, None

def generar_señal_rsi(rsi, precio_actual, historico):
    try:
        if rsi is None or historico is None or len(historico) < 10:
            return {"señal": "DATOS_INSUFICIENTES", "confianza": 0, "tendencia": "DESCONOCIDA", "indicadores": {}}
        historico = np.array(historico, dtype=np.float64)
        macd, macd_signal, _ = calcular_macd(historico)
        media_corta = np.mean(historico[-5:])
        media_larga = np.mean(historico[-20:]) if len(historico) >= 20 else media_corta
        precio_actual = float(precio_actual)
        volatilidad = np.std(historico[-10:]) / np.mean(historico[-10:])
        ajuste_umbral = min(volatilidad * 40, 15)
        rsi_sobrecompra = 70 - ajuste_umbral/2
        rsi_sobreventa = 30 + ajuste_umbral/2
        if rsi < rsi_sobreventa:
            senal_rsi = "COMPRA"
        elif rsi > rsi_sobrecompra:
            senal_rsi = "VENTA"
        else:
            senal_rsi = "NEUTRO"
        if precio_actual > media_corta > media_larga:
            tendencia = "ALZA"
        elif precio_actual < media_corta < media_larga:
            tendencia = "BAJA"
        else:
            tendencia = "PLANA"
        confianza = calcular_confianza(historico, rsi, macd, macd_signal)
        return {
            "señal": senal_rsi,
            "confianza": confianza,
            "tendencia": tendencia,
            "indicadores": {
                "rsi": round(rsi, 2),
                "macd": round(macd, 4) if macd else None,
                "macd_signal": round(macd_signal, 4) if macd_signal else None,
                "rsi_umbral_compra": round(rsi_sobreventa, 2),
                "rsi_umbral_venta": round(rsi_sobrecompra, 2)
            }
        }
    except Exception as e:
        logging.error(f"Error en generar_señal_rsi: {str(e)}", exc_info=True)
        return {"señal": "ERROR", "confianza": 0, "tendencia": "DESCONOCIDA", "indicadores": {}}

def calcular_macd(cierres, periodo_largo=26, periodo_corto=12, periodo_senal=9):
    """Calcula el MACD usando solo numpy"""
    try:
        if len(cierres) < periodo_largo + periodo_senal:
            return None, None, None
        
        cierres = np.array(cierres, dtype=np.float64)
        
        # Función para calcular EMA
        def calcular_ema(data, period):
            if len(data) < period:
                return np.mean(data)
            
            alpha = 2 / (period + 1)
            ema = np.zeros_like(data)
            ema[0] = data[0]
            
            for i in range(1, len(data)):
                ema[i] = alpha * data[i] + (1 - alpha) * ema[i-1]
            
            return ema[-1]
        
        # Calcular EMAs
        ema_corta = calcular_ema(cierres, periodo_corto)
        ema_larga = calcular_ema(cierres, periodo_largo)
        macd_line = ema_corta - ema_larga
        
        # Para la línea de señal necesitamos valores históricos de MACD
        macd_values = []
        for i in range(periodo_corto, len(cierres)):
            ema_c = calcular_ema(cierres[:i+1], periodo_corto)
            ema_l = calcular_ema(cierres[:i+1], periodo_largo)
            macd_values.append(ema_c - ema_l)
        
        if len(macd_values) >= periodo_senal:
            signal_line = calcular_ema(np.array(macd_values), periodo_senal)
        else:
            signal_line = macd_line
            
        histograma = macd_line - signal_line
        
        return macd_line, signal_line, histograma
    
    except Exception as e:
        logging.error(f"Error calculando MACD: {str(e)}")
        return None, None, None

def enviar_telegram(mensaje: str):
    """Envía mensaje a Telegram con manejo de errores"""
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                'chat_id': TELEGRAM_CHAT_ID,
                'text': mensaje,
                'parse_mode': 'HTML'
            },
            timeout=10
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error enviando a Telegram: {str(e)}")
    except Exception as e:
        logging.error(f"Error inesperado en Telegram: {str(e)}")

# --- Endpoints ---
@app.route("/")
def home():
    return "Bot de Monitoreo Cripto - Endpoints: /health, /resumen", 200

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
        logging.error(f"Health check failed: {str(e)}")
        return {"status": "unhealthy", "error": str(e)}, 500

@app.route("/resumen")
def resumen():
    try:
        # Obtener precios actuales
        precios = obtener_precios_actuales()
        if not precios:
            enviar_telegram("⚠️ <b>Error crítico:</b> No se pudieron obtener los precios actuales")
            return "Error al obtener precios", 500
        
        mensaje = "📊 <b>Análisis Cripto Avanzado</b>\n"
        mensaje += "════════════════════════\n\n"
        ahora = ahora_madrid()
        
        for moneda in MONEDAS:
            try:
                precio = precios[moneda]
                historicos = obtener_precios_historicos(moneda)
                
                if historicos is None or len(historicos) < 10:
                    mensaje += f"<b>{moneda}:</b> {precio:,.8f} €\n"
                    mensaje += "⚠️ Datos insuficientes para análisis\n\n"
                    continue
                
                # Calcular indicadores
                rsi = calcular_rsi(historicos)
                macd, macd_signal, _ = calcular_macd(historicos)
                señal = generar_señal_rsi(rsi, precio, historicos)
                
                # Insertar en base de datos
                insertar_precio(moneda, precio, rsi)
                
                # Construir mensaje
                mensaje += f"<b>{moneda}:</b> {precio:,.8f} €\n"
                mensaje += f"📈 <b>RSI:</b> {señal['indicadores']['rsi']} "
                mensaje += f"(Compra<{señal['indicadores']['rsi_umbral_compra']}, "
                mensaje += f"Venta>{señal['indicadores']['rsi_umbral_venta']})\n"
                
                if macd is not None:
                    mensaje += f"📊 <b>MACD:</b> {señal['indicadores']['macd']:.4f} "
                    mensaje += f"(Señal: {señal['indicadores']['macd_signal']:.4f}) "
                    macd_trend = "↑" if señal['indicadores']['macd'] > señal['indicadores']['macd_signal'] else "↓"
                    mensaje += f"<b>{macd_trend}</b>\n"
                
                mensaje += f"🔄 <b>Tendencia:</b> {señal['tendencia']}\n"
                mensaje += f"🎯 <b>Señal:</b> <u>{señal['señal']}</u>\n"
                mensaje += f"🔍 <b>Confianza:</b> {'★' * señal['confianza']}{'☆' * (5 - señal['confianza'])}"
                mensaje += f" ({señal['confianza']}/5)\n\n"
                
            except Exception as e:
                logging.error(f"Error procesando {moneda}: {str(e)}", exc_info=True)
                mensaje += f"<b>{moneda}:</b> {precio:,.8f} €\n"
                mensaje += f"⚠️ Error en análisis - Ver logs\n\n"
        
        # Pie del mensaje
        mensaje += "════════════════════════\n"
        mensaje += f"🔄 <i>Actualizado: {formatear_fecha(ahora)} (Hora Madrid)</i>\n"
        mensaje += f"📶 <i>Indicadores: RSI(14), MACD(12,26,9)</i>"
        
        # Enviar mensaje
        enviar_telegram(mensaje)
        return "Resumen enviado", 200
        
    except Exception as e:
        logging.critical(f"Error general en /resumen: {str(e)}", exc_info=True)
        enviar_telegram("⚠️ <b>Error crítico:</b> Fallo al generar el resumen. Ver logs.")
        return "Error interno", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
