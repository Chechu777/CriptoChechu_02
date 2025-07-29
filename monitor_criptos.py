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

def calcular_rsi(cierres: np.ndarray, periodo: int = INTERVALO_RSI) -> float:
    """Cálculo optimizado del RSI con manejo de edge cases"""
    if len(cierres) < periodo + 1:
        return None
    
    try:
        cierres = np.array(cierres, dtype=np.float64)
        if np.isnan(cierres).any():
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
    """
    Versión optimizada que corrige:
    - Cálculo de tendencia usando media móvil corta
    - Ajuste de confianza basado en volatilidad normalizada
    - Umbrales dinámicos de RSI
    """
    try:
        # Validación inicial robusta
        if rsi is None or not historico or len(historico) < 5:
            return {"señal": "INDETERMINADO", "confianza": 0, "tendencia": "DESCONOCIDA"}
        
        # Convertir y limpiar datos históricos
        historico = [float(h) for h in historico if h is not None and float(h) > 0]
        if not historico:
            return {"señal": "ERROR_DATOS", "confianza": 0, "tendencia": "DESCONOCIDA"}
        
        precio_actual = float(precio_actual)
        
        # Cálculo de tendencia mejorado (usando media móvil de 5 períodos)
        ultimos_precios = historico[-5:]
        media_corta = np.mean(ultimos_precios)
        tendencia = "ALZA" if precio_actual > media_corta * 1.005 else "BAJA" if precio_actual < media_corta * 0.995 else "PLANA"
        
        # Cálculo de confianza optimizado
        confianza = 3  # Valor por defecto
        if len(historico) >= 10:
            volatilidad = np.std(historico[-10:]) / np.mean(historico[-10:])
            # Escala de confianza ajustada:
            if volatilidad < 0.01:  # Mercado muy estable
                confianza = 5
            elif volatilidad < 0.03:
                confianza = 4
            elif volatilidad < 0.05:
                confianza = 3
            elif volatilidad < 0.08:
                confianza = 2
            else:
                confianza = 1
        
        # Umbrales dinámicos de RSI basados en volatilidad
        umbral_compra = 28 if confianza >=4 else 30
        umbral_venta = 72 if confianza >=4 else 70
        
        # Generación de señal mejorada
        if rsi < umbral_compra and tendencia == "BAJA":
            return {"señal": "COMPRA", "confianza": confianza, "tendencia": tendencia}
        elif rsi > umbral_venta and tendencia == "ALZA":
            return {"señal": "VENTA", "confianza": confianza, "tendencia": tendencia}
        return {"señal": "NEUTRO", "confianza": confianza, "tendencia": tendencia}
        
    except Exception as e:
        logging.error(f"Error en generar_señal_rsi: {str(e)}", exc_info=True)
        return {"señal": "ERROR", "confianza": 0, "tendencia": "DESCONOCIDA"}

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
            logging.error("No se pudieron obtener precios actuales")
            return "Error al obtener precios", 500
        
        mensaje = "📊 <b>Análisis Cripto Avanzado</b>\n\n"
        ahora = ahora_madrid()
        
        for moneda in MONEDAS:
            try:
                precio = precios[moneda]
                historicos = obtener_precios_historicos(moneda)
                
                logging.info(f"Procesando {moneda} - Datos históricos: {len(historicos) if historicos is not None else 0} registros")
                
                rsi = calcular_rsi(historicos) if historicos is not None else None
                señal = generar_señal_rsi(rsi, precio, historicos)
                
                if not insertar_precio(moneda, precio, rsi):
                    logging.warning(f"No se pudo insertar {moneda} en Supabase")
                
                mensaje += (
                    f"<b>{moneda}:</b> {precio:,.8f} €\n"
                    f"📈 RSI: {rsi or 'N/A'} | Señal: {señal['señal']}\n"
                    f"🔍 Confianza: {'★' * señal['confianza']}{'☆' * (5 - señal['confianza'])} "
                    f"| Tendencia: {señal['tendencia']}\n\n"
                )
                
            except Exception as e:
                logging.error(f"Error procesando {moneda}: {str(e)}")
                mensaje += f"<b>{moneda}:</b> Error en análisis\n\n"
        
        mensaje += f"🔄 <i>Actualizado: {formatear_fecha(ahora)} (Hora Madrid)</i>"
        enviar_telegram(mensaje)
        return "Resumen enviado", 200
        
    except Exception as e:
        logging.critical(f"Error general en /resumen: {str(e)}")
        return "Error interno", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
