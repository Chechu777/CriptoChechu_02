import os
import requests
import numpy as np
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

# Configuración inicial de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

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
HORAS_HISTORICO = 48
MINUTOS_ENTRE_REGISTROS = 55

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
        logging.error(f"Error parseando fecha {fecha_str}: {str(e)}")
        return ahora_madrid()

def calcular_rsi(cierres, periodo: int = INTERVALO_RSI) -> float:
    """Cálculo optimizado del RSI con manejo de edge cases"""
    if cierres is None:
        return None
        
    try:
        if isinstance(cierres, (list, np.ndarray)):
            cierres = np.array(cierres, dtype=np.float64)
        else:
            cierres = np.array([float(cierres)], dtype=np.float64)
            
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

def obtener_precios_actuales():
    """Obtiene precios actuales de CoinMarketCap con manejo robusto de errores"""
    try:
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        params = {'symbol': ','.join(MONEDAS), 'convert': 'EUR'}
        headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': CMC_API_KEY}

        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        datos = response.json()
        
        precios = {}
        for moneda in MONEDAS:
            try:
                precio = float(datos['data'][moneda]['quote']['EUR']['price'])
                if precio <= 0:
                    raise ValueError("Precio no positivo")
                precios[moneda] = precio
            except (KeyError, ValueError) as e:
                logging.error(f"Error procesando {moneda}: {str(e)}")
                return None
                
        return precios
    except requests.exceptions.RequestException as e:
        logging.error(f"Error API CoinMarketCap: {str(e)}")
        return None

def obtener_precios_historicos(nombre: str):
    """Recupera precios históricos con validación de datos"""
    try:
        fecha_limite = ahora_madrid() - timedelta(hours=HORAS_HISTORICO)
        response = supabase.table("precios").select(
            "precio, fecha"
        ).eq("nombre", nombre
        ).gte("fecha", fecha_limite.strftime("%Y-%m-%d %H:%M:%S")
        ).order("fecha", desc=False
        ).limit(INTERVALO_RSI * 3).execute()
        logging.info(f"Datos crudos de Supabase para {nombre}: {response.data}")
        
        if not response.data:
            return None
            
        precios_validos = []
        for reg in response.data:
            try:
                precio = float(reg['precio'])
                if precio > 0:
                    precios_validos.append(precio)
            except (ValueError, TypeError):
                continue
                
        return np.array(precios_validos) if precios_validos else None
    except Exception as e:
        logging.error(f"Error obteniendo históricos: {str(e)}")
        return None

def insertar_precio(nombre: str, precio: float, rsi: float = None):
    """Inserta datos en Supabase con logging detallado"""
    try:
        if not isinstance(precio, (int, float)) or precio <= 0:
            raise ValueError("Precio inválido")
            
        datos = {
            "nombre": nombre,
            "precio": float(precio),
            "rsi": float(rsi) if rsi else None,
            "fecha": ahora_madrid().strftime("%Y-%m-%d %H:%M:%S.%f")
        }
        
        response = supabase.table("precios").insert(datos).execute()
        
        if response.data:
            logging.info(f"Insertado {nombre}: Precio={precio:.8f} | RSI={rsi or 'NULL'}")
            return True
        else:
            logging.warning(f"Respuesta inesperada de Supabase: {response}")
            return False
    except Exception as e:
        logging.error(f"Error insertando {nombre}: {str(e)}", exc_info=True)
        return False

def generar_señal_rsi(rsi: float, precio_actual: float, historico: list) -> dict:
    """Versión final a prueba de errores"""
    try:
        # Validación exhaustiva
        if (rsi is None or 
            historico is None or 
            not isinstance(historico, (list, np.ndarray)) or 
            (isinstance(historico, (list, np.ndarray)) and len(historico) < 5):
            return {"señal": "DATOS_INSUFICIENTES", "confianza": 0, "tendencia": "DESCONOCIDA"}
        
        # Conversión definitiva a lista
        try:
            if isinstance(historico, np.ndarray):
                historico = historico.tolist()
            historico = [float(h) for h in historico if h is not None and float(h) > 0]
        except Exception as e:
            logging.error(f"Error convirtiendo datos: {str(e)}")
            return {"señal": "ERROR_CONVERSION", "confianza": 0, "tendencia": "DESCONOCIDA"}
        
        if not historico:
            return {"señal": "HISTORICO_VACIO", "confianza": 0, "tendencia": "DESCONOCIDA"}
        
        # Cálculo de tendencia mejorado
        try:
            media_corta = np.mean(historico[-5:])
            precio_actual = float(precio_actual)
            diferencia = precio_actual - media_corta
            umbral_tendencia = np.std(historico[-10:]) * 0.5  # 0.5 desviaciones estándar
            
            if diferencia > umbral_tendencia:
                tendencia = "ALZA"
            elif diferencia < -umbral_tendencia:
                tendencia = "BAJA"
            else:
                tendencia = "PLANA"
        except Exception as e:
            logging.error(f"Error calculando tendencia: {str(e)}")
            tendencia = "DESCONOCIDA"
        
        # Cálculo de confianza robusto
        try:
            volatilidad = np.std(historico[-10:]) / np.mean(historico[-10:]) if len(historico) >=10 else 0.05
            confianza = min(5, max(1, int(5 - (volatilidad * 20))))  # Ajuste más sensible
        except:
            confianza = 3  # Valor por defecto
        
        # Generación de señal con umbrales dinámicos
        try:
            rsi = float(rsi)
            if rsi < 30 - (5 - confianza):  # Umbral más agresivo en alta confianza
                return {"señal": "COMPRA", "confianza": confianza, "tendencia": tendencia}
            elif rsi > 70 + (5 - confianza):
                return {"señal": "VENTA", "confianza": confianza, "tendencia": tendencia}
            return {"señal": "NEUTRO", "confianza": confianza, "tendencia": tendencia}
        except Exception as e:
            logging.error(f"Error generando señal: {str(e)}")
            return {"señal": "ERROR_RSI", "confianza": 0, "tendencia": tendencia}
            
    except Exception as e:
        logging.critical(f"Error crítico: {str(e)}", exc_info=True)
        return {"señal": "ERROR_CRITICO", "confianza": 0, "tendencia": "DESCONOCIDA"}

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
        precios = obtener_precios_actuales()
        if not precios:
            return "Error al obtener precios", 500
        
        mensaje = "📊 <b>Análisis Cripto Avanzado</b>\n\n"
        ahora = ahora_madrid()
        
        for moneda in MONEDAS:
            try:
                precio = precios[moneda]
                historicos = obtener_precios_historicos(moneda)
                
                # Conversión segura a lista
                datos_historicos = None
                if historicos is not None:
                    if isinstance(historicos, np.ndarray):
                        datos_historicos = historicos.tolist()
                    else:
                        datos_historicos = list(historicos) if hasattr(historicos, '__iter__') else [historicos]
                
                rsi = calcular_rsi(historicos) if historicos is not None else None
                señal = generar_señal_rsi(rsi, precio, datos_historicos)
                
                insertar_precio(moneda, precio, rsi)
                
                mensaje += (
                    f"<b>{moneda}:</b> {precio:,.8f} €\n"
                    f"📈 RSI: {rsi or 'N/A'} | Señal: {señal['señal']}\n"
                    f"🔍 Confianza: {'★' * señal['confianza']}{'☆' * (5 - señal['confianza'])} "
                    f"| Tendencia: {señal['tendencia']}\n\n"
                )
            
            except Exception as e:
                logging.error(f"Error procesando {moneda}: {str(e)}")
                mensaje += (
                    f"<b>{moneda}:</b> {precios.get(moneda, 'N/A'):,.8f} €\n"
                    f"⚠️ Error en análisis - Ver logs\n\n"
                )
        
        mensaje += f"🔄 <i>Actualizado: {formatear_fecha(ahora)} (Hora Madrid)</i>"
        enviar_telegram(mensaje)
        return "Resumen enviado", 200
        
    except Exception as e:
        logging.critical(f"Error general en /resumen: {str(e)}")
        return "Error interno", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
