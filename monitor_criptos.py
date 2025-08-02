# monitor_criptos.py
# monitor_criptos.py
from dotenv import load_dotenv
load_dotenv()
import os
import requests
import numpy as np
import json
import re
import time
from flask import Flask
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from zoneinfo import ZoneInfo
from requests.exceptions import HTTPError
import logging
import traceback
from functools import lru_cache
import backoff
import sys

# --- Logging --- (MOVIDO AL PRINCIPIO)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- Ahora sí podemos usar el logger en los decoradores ---
@backoff.on_exception(backoff.expo, 
                     (requests.exceptions.RequestException, json.JSONDecodeError), 
                     max_tries=3, 
                     max_time=30,
                     logger=logger)  # Ahora logger está definido
def obtener_datos_api(url, params, headers=None):
    """Función wrapper para llamadas a API con reintentos exponenciales"""
    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=15
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Fallo en obtener_datos_api: {str(e)}")
        raise

@lru_cache(maxsize=32)
def obtener_precio_cacheado(moneda: str, minutos_cache: int = 5):
    """Obtiene precio con caché para evitar llamadas redundantes"""
    cache_key = f"{moneda}_{int(time.time()) // (minutos_cache * 60)}"
    return obtener_precios_actuales().get(moneda)

# Límites de seguridad

MAX_REGISTROS_POR_LLAMADA = 50  # Máximo de registros a procesar por ejecución
MAX_REGISTROS_POR_LOTE = 25     # Tamaño de lote para inserciones
DIAS_MAXIMOS_HISTORICO = 7      # Máximo de días a obtener de APIs

# --- Flask ---
app = Flask(__name__)
application = app  # Render

# --- Entorno ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

def _env_float(key, default):
    try:
        return float(os.getenv(key, str(default)))
    except Exception:
        return float(default)

def _env_bool(key, default=False):
    v = str(os.getenv(key, str(default))).strip().lower()
    return v in ("1", "true", "t", "yes", "y", "si", "sí")

# --- Constantes ---
MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]
INTERVALO_RSI = 14
HORAS_HISTORICO = 48

# Sensibilidades MACD / tendencia (ahora más agresivas por env)
MACD_SIGMA_K = _env_float("MACD_SIGMA_K", 0.25)
MACD_SIGMA_K_TEND = _env_float("MACD_SIGMA_K_TEND", 0.15)
PENDIENTE_UMBRAL_REL = _env_float("PENDIENTE_UMBRAL_REL", 0.0004)

# Opciones de compra "casi cruce" y "dip"
PERMITIR_COMPRA_CASI_CRUCE = _env_bool("PERMITIR_COMPRA_CASI_CRUCE", True)
PERMITIR_COMPRA_DIP = _env_bool("PERMITIR_COMPRA_DIP", True)
DIP_PCT = _env_float("DIP_PCT", 2.5)  # %
DIP_LOOKBACK_PUNTOS = int(_env_float("DIP_LOOKBACK_PUNTOS", 24))
ZSCORE_DIP = _env_float("ZSCORE_DIP", -1.2)
COMPRA_PARCIAL_PCT = _env_float("COMPRA_PARCIAL_PCT", 0.25)
ZSCORE_TAKEPROFIT = _env_float("ZSCORE_TAKEPROFIT", 1.2)  # opcional
 
# --- Supabase ---  
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
# Prueba de conexión inicial (modificada)

try:
    logger.info("=== TESTING SUPABASE CONNECTION ===")
    test_result = supabase.table("ohlcv").select("id", count="exact").limit(1).execute()
    if not hasattr(test_result, 'count'):
        logger.error("Respuesta inesperada de Supabase")
        raise ConnectionError("Fallo en la conexión a Supabase")
    logger.info(f"Conexión exitosa. Tabla contiene {test_result.count} registros")
except Exception as e:
    logger.critical(f"Error de conexión a Supabase: {str(e)}")
    raise  # Detiene la ejecución si no hay conexión

# --- Utilidades ---
def ahora_madrid():
    return datetime.now(ZoneInfo("Europe/Madrid"))

def formatear_fecha(fecha):
    return fecha.strftime("%d/%m/%Y %H:%M")

# --- Indicadores ---

def calcular_rsi_mejorado(cierres, periodo=INTERVALO_RSI):
    """Versión mejorada del RSI con validación robusta"""
    try:
        if not isinstance(cierres, (list, np.ndarray)) or len(cierres) < periodo + 1:
            return None
            
        cierres = np.asarray(cierres, dtype=np.float64)
        if np.all(cierres == cierres[0]):  # Todos los valores iguales
            return 50.0
            
        deltas = np.diff(cierres)
        ganancias = np.maximum(deltas, 0)
        perdidas = np.maximum(-deltas, 0)
        
        # Suavizado exponencial
        avg_gain = np.mean(ganancias[:periodo])
        avg_loss = np.mean(perdidas[:periodo])
        
        for i in range(periodo, len(deltas)):
            avg_gain = (avg_gain * (periodo - 1) + ganancias[i]) / periodo
            avg_loss = (avg_loss * (periodo - 1) + perdidas[i]) / periodo
        
        if avg_loss < 1e-12:  # Evitar división por cero
            return 100.0 if avg_gain > 1e-12 else 50.0
            
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
        
    except Exception as e:
        logger.error(f"Error en RSI mejorado: {str(e)}")
        return None
 
def calcular_macd(cierres, periodo_largo=26, periodo_corto=12, periodo_senal=9):
    try:
        if len(cierres) < periodo_largo + periodo_senal:
            logger.warning(f"Datos insuficientes para MACD (se necesitan {periodo_largo + periodo_senal}, se tienen {len(cierres)})")
            return None, None, None

        c = np.array(cierres, dtype=np.float64)
        if np.all(np.diff(c) == 0):  # Verifica si no hay variación en los datos
            logger.warning("Datos sin variación: MACD no significativo")
            return 0.0, 0.0, 0.0
        # Resto del código...

        def ema(data, period):
            if len(data) < period:
                return np.mean(data)
            alpha = 2 / (period + 1)
            e = np.zeros_like(data)
            e[0] = data[0]
            for i in range(1, len(data)):
                e[i] = alpha * data[i] + (1 - alpha) * e[i-1]
            return e[-1]

        ema_c = ema(c, periodo_corto)
        ema_l = ema(c, periodo_largo)
        macd_line = ema_c - ema_l

        macd_values = []
        for i in range(periodo_corto, len(c)):
            macd_values.append(ema(c[:i+1], periodo_corto) - ema(c[:i+1], periodo_largo))

        signal_line = ema(np.array(macd_values), periodo_senal) if len(macd_values) >= periodo_senal else macd_line
        hist = macd_line - signal_line

        logger.info(f"MACD calculado: line={macd_line:.6f}, signal={signal_line:.6f}, hist={hist:.6f}")
        return macd_line, signal_line, hist

    except Exception as e:
        logger.error(f"Error calculando MACD: {str(e)}", exc_info=True)
        return None, None, None

def _tendencia_por_pendiente(historico, puntos=12, umbral_rel=PENDIENTE_UMBRAL_REL):
    """Pendiente de últimos 'puntos' cierres => ALZA/BAJA/PLANA."""
    h = np.asarray(historico[-max(5, puntos):], dtype=np.float64)
    x = np.arange(len(h), dtype=np.float64)
    m, _ = np.polyfit(x, h, 1)
    rel = m / max(1e-12, np.mean(h))
    if rel > umbral_rel:
        return "ALZA"
    if rel < -umbral_rel:
        return "BAJA"
    return "PLANA"

def calcular_confianza(historico, rsi, macd, macd_signal):
    """1–5 estrellas con MACD vs σ, RSI y tendencia."""
    try:
        h = np.asarray(historico, dtype=np.float64) if historico is not None else None
        if rsi is None or macd is None or macd_signal is None or h is None or len(h) < 27:
            logger.warning(f"calcular_confianza: datos insuficientes (rsi={rsi}, macd={macd}, signal={macd_signal}, len(h)={len(h) if h is not None else None})")
            return 1

        delta = macd - macd_signal
        difs = np.diff(h[-27:]) if len(h) >= 27 else np.diff(h)
        vol = np.std(difs)
        relevante = abs(delta) > MACD_SIGMA_K * max(1e-12, vol)
        tend = _tendencia_por_pendiente(h, puntos=12, umbral_rel=PENDIENTE_UMBRAL_REL)

        conf = 2
        if rsi < 30 or rsi > 70:
            conf += 1
        if (rsi < 50 and delta > 0) or (rsi > 50 and delta < 0):
            conf += 1
        if relevante:
            conf += 1
        if (tend == "ALZA" and delta < 0) or (tend == "BAJA" and delta > 0):
            conf = max(1, conf - 1)

        conf = int(max(1, min(5, conf)))
        logger.info(f"Confianza calculada: {conf} (rsi={rsi}, delta={delta:.6g}, vol={vol:.6g}, relevante={relevante}, tend={tend})")
        return conf
    except Exception:
        logger.error("Error calculando confianza", exc_info=True)
        return 1

def _zscore_ultima(cierres, ventana=20):
    h = np.asarray(cierres, dtype=np.float64)
    if len(h) < max(5, ventana):
        logger.warning(f"_zscore_ultima: datos insuficientes (len={len(h)}, se necesitan {ventana})")
        return None, None, None  # z, media, std
    sub = h[-ventana:]
    mu = float(np.mean(sub))
    sd = float(np.std(sub))
    if sd <= 0:
        return 0.0, mu, sd
    z = float((h[-1] - mu) / sd)
    return z, mu, sd

def generar_señal_rsi(rsi: float, precio_actual: float, historico, moneda: str) -> dict:
    """Señal combinada RSI + MACD(σ) + tendencia + persistencia + métricas DIP"""
    sigma_k = 0.5 if moneda == "SHIB" else MACD_SIGMA_K
    
    try:
        if rsi is None or historico is None or len(historico) < 35:
            logger.warning(f"generar_señal_rsi: datos insuficientes (rsi={rsi}, len(historico)={len(historico) if historico is not None else None})")
            return {"señal": "DATOS_INSUFICIENTES", "confianza": 0, "tendencia": "DESCONOCIDA", "indicadores": {}}

        h = np.asarray(historico, dtype=np.float64)
        # --- Código de volatilidad añadido aquí ---
        volatilidad = np.std(h[-30:])/np.mean(h[-30:]) if len(h) >= 30 else 0
        if volatilidad < 0.01:  # Menos del 1% de volatilidad
            logger.info(f"Volatilidad muy baja ({volatilidad:.2%}), señal forzada a NEUTRO")
            return {
                "señal": "NEUTRO", 
                "confianza": 1, 
                "tendencia": "PLANA", 
                "indicadores": {
                    "volatilidad": round(volatilidad, 4),
                    **{k: None for k in [
                        "rsi", "macd", "macd_signal", "macd_raw", "macd_signal_raw",
                        "rsi_umbral_compra", "rsi_umbral_venta", "macd_delta", "macd_vol",
                        "zscore20", "ma20", "std20", "drawdown_pct", "lookback_puntos"
                    ]}
                }
            }
            
        macd, macd_signal, _ = calcular_macd(h)
        tendencia = _tendencia_por_pendiente(h, puntos=12, umbral_rel=PENDIENTE_UMBRAL_REL)
        
        # Umbrales RSI dinámicos (cap ±5)
        volatilidad = np.std(h[-10:]) / max(1e-12, np.mean(h[-10:]))
        ajuste = min(volatilidad * 20, 5)
        rsi_sobrecompra = 70 - ajuste/2
        rsi_sobreventa = 30 + ajuste/2

        # Señal base por RSI
        if rsi < rsi_sobreventa:
            senal_rsi = "COMPRA"
        elif rsi > rsi_sobrecompra:
            senal_rsi = "VENTA"
        else:
            senal_rsi = "NEUTRO"

        # Refuerzo por MACD con umbral relativo a σ y persistencia
        senal = senal_rsi
        delta = None
        vol = None
        if macd is not None and macd_signal is not None:
            delta = macd - macd_signal
            difs = np.diff(h[-27:]) if len(h) >= 27 else np.diff(h)
            vol = np.std(difs)
            relevante = abs(delta) > sigma_k * max(1e-12, vol)

            # Persistencia de cruce (tick anterior)
            macd_prev, sig_prev, _ = calcular_macd(h[:-1]) if len(h) > 35 else (None, None, None)
            if macd_prev is not None and sig_prev is not None:
                delta_prev = macd_prev - sig_prev
                mismo_signo = (delta > 0 and delta_prev > 0) or (delta < 0 and delta_prev < 0)
                if mismo_signo and abs(delta) > 0.25 * max(1e-12, vol):
                    relevante = True

            # Ajuste por tendencia
            tend = _tendencia_por_pendiente(h, puntos=12, umbral_rel=PENDIENTE_UMBRAL_REL)
            if tend == "ALZA" and delta > 0:
                relevante = abs(delta) > MACD_SIGMA_K_TEND * max(1e-12, vol)
            if tend == "BAJA" and delta < 0:
                relevante = abs(delta) > MACD_SIGMA_K_TEND * max(1e-12, vol)

            if relevante:
                if delta > 0 and rsi > 35 and senal_rsi != "VENTA":
                    senal = "COMPRA"
                elif delta < 0 and rsi < 65 and senal_rsi != "COMPRA":
                    senal = "VENTA"

            logger.info(f"MACD refuerzo: delta={delta:.6g}, vol={vol:.6g}, relevante={relevante}, tend={tend}")

        # Métricas DIP
        z, ma20, sd20 = _zscore_ultima(h, ventana=20)
        look = min(max(5, DIP_LOOKBACK_PUNTOS), len(h))
        max_ventana = float(np.max(h[-look:])) if look > 0 else float(np.max(h))
        dd_pct = 0.0
        if max_ventana > 0:
            dd_pct = (max_ventana - float(h[-1])) / max_ventana * 100.0

        # --- Desempate más agresivo ---
        if senal == "NEUTRO" and macd is not None and macd_signal is not None:
            if tendencia == "BAJA" and rsi < 55 and macd < macd_signal:
                senal = "VENTA"
            elif tendencia == "ALZA" and rsi > 45 and macd > macd_signal:
                senal = "COMPRA"

        confianza = calcular_confianza(h, rsi, macd, macd_signal)

        indicadores = {
           "rsi": round(rsi, 2),
           "macd": round(macd, 6) if macd is not None else None,
           "macd_signal": round(macd_signal, 6) if macd_signal is not None else None,
           "macd_raw": float(macd) if macd is not None else None,
           "macd_signal_raw": float(macd_signal) if macd_signal is not None else None,
           "rsi_umbral_compra": round(rsi_sobreventa, 2),
           "rsi_umbral_venta": round(rsi_sobrecompra, 2),
           "macd_delta": float(delta) if (macd is not None and macd_signal is not None) else None,
           "macd_vol": float(vol) if (macd is not None and macd_signal is not None) else None,
           "zscore20": float(z) if z is not None else None,
           "ma20": float(ma20) if ma20 is not None else None,
           "std20": float(sd20) if sd20 is not None else None,
           "drawdown_pct": round(dd_pct, 2),
           "lookback_puntos": int(look),
        }

        logger.info(f"Señal generada: {senal} (rsi={rsi}, base={senal_rsi}, tend={tendencia}, conf={confianza}, dd={dd_pct:.2f}%, z={z})")
        return {"señal": senal, "confianza": confianza, "tendencia": tendencia, "indicadores": indicadores}
    except Exception:
        logger.error("Error en generar_señal_rsi", exc_info=True)
        return {"señal": "ERROR", "confianza": 0, "tendencia": "DESCONOCIDA", "indicadores": {}}

def recomendar_accion(
    senal: str,
    rsi: float | None,
    macd: float | None,
    macd_signal: float | None,
    confianza: int,
    macd_delta: float | None = None,
    macd_vol: float | None = None,
    tendencia: str | None = None,
    zscore: float | None = None,
    drawdown_pct: float | None = None
) -> str:
    """Recomendación más agresiva: confirma con MACD, permite casi cruce (ambos sentidos) y dip."""
    try:
        def confirma_compra():
            return macd is not None and macd_signal is not None and macd > macd_signal
        def confirma_venta():
            return macd is not None and macd_signal is not None and macd < macd_signal

        # EPS más laxo para "casi cruce": 0.2 * K * σ
        eps = None
        if macd_delta is not None and macd_vol is not None:
            eps = 0.2 * MACD_SIGMA_K * max(1e-12, macd_vol)
        casi = (eps is not None and macd_delta is not None and abs(macd_delta) < eps)

        # Take-profit parcial por sobre-extensión al alza
        if zscore is not None and ZSCORE_TAKEPROFIT is not None and zscore >= ZSCORE_TAKEPROFIT:
            if (rsi is not None and rsi > 60) or confirma_venta():
                return "🟡 Podrías tomar ganancias parciales (sobre-extensión)"

        if senal == "COMPRA":
            if confirma_compra():
                return "🟢 Podrías comprar" + (" (señal fuerte)" if confianza >= 4 else " (señal débil)" if confianza <= 2 else "")
            if casi:  # más agresivo: incluso en tendencia BAJA
                return "🟡 Podrías comprar en pequeña cantidad (casi cruza)"
            if drawdown_pct is not None and zscore is not None and drawdown_pct >= DIP_PCT and (zscore <= ZSCORE_DIP or (rsi is not None and rsi < 40) or casi):
                return f"🟡 Podrías comprar en pequeña cantidad (dip {COMPRA_PARCIAL_PCT*100:.0f}%)"
            return "⚪ Quieto chato, no hagas huevadas (espera confirmación MACD)"

        elif senal == "VENTA":
            if confirma_venta():
                return "🔴 Podrías vender" + (" (señal fuerte)" if confianza >= 4 else " (señal débil)" if confianza <= 2 else "")
            if casi and macd_delta is not None and macd_delta < 0:
                return "🟠 Podrías vender en pequeña cantidad (casi cruza abajo)"
            return "⚪ Quieto chato, no hagas huevadas"

        elif senal == "NEUTRO":
            if drawdown_pct is not None and zscore is not None and drawdown_pct >= DIP_PCT and (zscore <= ZSCORE_DIP or (rsi is not None and rsi < 40) or (casi and (macd_delta is not None and macd_delta > 0))):
                return f"🟡 Podrías comprar en pequeña cantidad (dip {COMPRA_PARCIAL_PCT*100:.0f}%)"
            if casi and macd_delta is not None:
                if macd_delta > 0:
                    return "🟡 Podrías comprar en pequeña cantidad (casi cruza)"
                else:
                    return "🟠 Podrías vender en pequeña cantidad (casi cruza abajo)"
            return "⚪ Quieto chato, no hagas huevadas"

        else:
            return "ℹ️ Sin datos suficientes para recomendar"

    except Exception:
        logger.error("Error en recomendar_accion", exc_info=True)
        return "ℹ️ Sin datos suficientes para recomendar"

# --- IO: APIs / DB ---
def obtener_precios_actuales():
    """CoinMarketCap EUR"""
    try:
        logger.info("Obteniendo precios actuales desde CoinMarketCap...")
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        params = {"symbol": ",".join(MONEDAS), "convert": "EUR"}
        headers = {"Accepts": "application/json", "X-CMC_PRO_API_KEY": CMC_API_KEY}
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        datos = response.json()
        precios = {}
        for m in MONEDAS:
            try:
                precio = float(datos["data"][m]["quote"]["EUR"]["price"])
                if precio <= 0:
                    raise ValueError("Precio no positivo")
                precios[m] = precio
                logger.info(f"Precio obtenido para {m}: {precio} EUR")
            except (KeyError, ValueError) as e:
                logger.error(f"Error procesando {m}: {e}")
                return None
        return precios
    except requests.exceptions.RequestException:
        logger.error("Error API CoinMarketCap", exc_info=True)
        return None
 
def _cmc_headers():
    return {"Accepts": "application/json", "X-CMC_PRO_API_KEY": CMC_API_KEY}

def _obtener_de_supabase_cache(symbol: str, convert: str, days: int) -> list:
    """Obtiene datos históricos de la caché en Supabase"""
    try:
        fecha_limite = datetime.now(timezone.utc) - timedelta(days=days)
        
        response = supabase.table("ohlcv").select("*")\
            .eq("nombre", symbol)\
            .eq("intervalo", "1d")\
            .eq("convert", convert)\
            .gte("time_open", fecha_limite.isoformat())\
            .order("time_open", desc=True)\
            .limit(days * 2).execute()
              
        if response.data:
            logger.info(f"Obtenidos {len(response.data)} registros desde caché Supabase")
            return response.data
            
        return []
    except Exception as e:
        logger.error(f"Error obteniendo caché de Supabase: {str(e)}")
        return []
 
def obtener_ohlcv_diario(symbol: str, convert: str = "EUR", days: int = 30) -> list:
    """
    Obtiene datos OHLCV diarios solo desde CoinGecko, con caché local.
    Añade 'fuente': 'CoinGecko' a cada fila.
    """
    if not hasattr(obtener_ohlcv_diario, 'cache'):
        obtener_ohlcv_diario.cache = {}

    CACHE_KEY = f"{symbol}_{convert}_{days}"

    if CACHE_KEY in obtener_ohlcv_diario.cache:
        cached_data, timestamp = obtener_ohlcv_diario.cache[CACHE_KEY]
        if (datetime.now(timezone.utc) - timestamp) < timedelta(minutes=30):
            logger.info(f"Usando datos en caché para {symbol}")
            return cached_data

    logger.info(f"Obteniendo datos OHLCV para {symbol} ({days} días) desde CoinGecko")
 
    try:
        data = _obtener_de_coingecko_v3(symbol, convert, days)
        if data:
            for row in data:
                row["fuente"] = "CoinGecko"
            obtener_ohlcv_diario.cache[CACHE_KEY] = (data, datetime.now(timezone.utc))
            logger.info(f"Obtenidos {len(data)} registros usando CoinGecko")
            return data
        else:
            logger.warning(f"No se obtuvieron datos desde CoinGecko para {symbol}")
    except Exception as e:
        logger.error(f"Fallo al obtener datos de CoinGecko: {str(e)}", exc_info=True)

    logger.error("Todas las estrategias fallaron (solo CoinGecko activado)")
    return []
# =================
@backoff.on_exception(
    backoff.expo,
    requests.exceptions.HTTPError,
    max_tries=5,
    giveup=lambda e: e.response is not None and e.response.status_code != 429
)
# ================
def _obtener_de_coingecko_v3(symbol: str, convert: str, days: int) -> list:
    ids_coingecko = {
        'BTC': 'bitcoin',
        'ETH': 'ethereum',
        'ADA': 'cardano',
        'SHIB': 'shiba-inu',
        'SOL': 'solana'
    }

    try:
        coin_id = ids_coingecko.get(symbol.upper())
        if not coin_id:
            raise ValueError(f"Moneda {symbol} no soportada")

        # Asegurar que days esté dentro de rango
        if days not in [1, 7, 14, 30, 90, 180, 365]:
            days = max(1, min(days, 365))

        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
        params = {
            'vs_currency': convert.lower(),
            'days': days,
            'interval': 'daily'
        }

        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Python Crypto Bot'
        }

        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        precios = data.get("prices", [])
        volumenes = data.get("total_volumes", [])

        if not precios or not volumenes:
            raise ValueError("No se recibieron datos de precios o volúmenes")

        ohlcv_rows = []

        for i in range(len(precios)):
            ts_precio, close = precios[i]
            _, volume = volumenes[i]

            dt_open = datetime.utcfromtimestamp(ts_precio / 1000).replace(tzinfo=timezone.utc)
            dt_close = dt_open + timedelta(hours=23, minutes=59, seconds=59)

            row = {
                "nombre": symbol.upper(),
                "convert": convert.upper(),
                "intervalo": "1d",
                "time_open": dt_open.isoformat(),
                "time_close": dt_close.isoformat(),
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": float(volume),
                "fuente": "CoinGecko"
            }

            ohlcv_rows.append(row)

        logger.info(f"Procesados {len(ohlcv_rows)} registros válidos de {len(precios)} para {symbol}")
        return ohlcv_rows

    except Exception as e:
        logger.error(f"Error en _obtener_de_coingecko_v3: {str(e)}", exc_info=True)
        raise
#=================
def _procesar_datos_coingecko(data: list, symbol: str, convert: str) -> list:
    """Procesa los datos de la API v3 de CoinGecko al formato de nuestra base de datos"""
    processed = []
    for item in data:
        try:
            # La API v3 de CoinGecko devuelve arrays con: [timestamp, open, high, low, close]
            if len(item) != 5:
                continue
                
            timestamp = datetime.fromtimestamp(item[0]/1000, tz=timezone.utc)
            
            processed.append({
                "time_open": timestamp.isoformat(),
                "time_close": (timestamp + timedelta(days=1)).isoformat(),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": None,  # CoinGecko no provee volumen en este endpoint
                "nombre": symbol,
                "intervalo": "1d",
                "convert": convert,
                "fuente": "CoinGecko"
            })
        except Exception as e:
            logger.warning(f"Error procesando dato de CoinGecko: {str(e)}")
            continue
            
    logger.info(f"Procesados {len(processed)} registros válidos de {len(data)} para {symbol}")
    return processed

def _obtener_de_coinmarketcap(symbol: str, convert: str = "EUR", days: int = 30) -> list:
    """    Obtiene datos OHLCV históricos de CoinMarketCap API con manejo robusto de errores y validación de datos.    
    Args:
        symbol: Símbolo de la criptomoneda (ej: 'BTC')
        convert: Moneda de conversión (ej: 'EUR')
        days: Número de días históricos a obtener (máx 365)
    
    Returns:
        Lista de diccionarios con datos OHLCV o lista vacía en caso de error
    """
    # Validación inicial
    if not CMC_API_KEY:
        logger.error("API Key de CoinMarketCap no configurada")
        return []
        
    if days <= 0:
        logger.warning(f"Días debe ser positivo, recibido: {days}")
        return []

    logger.info(f"Obteniendo datos de CoinMarketCap para {symbol} ({days} días)")

    try:
        # Configuración de la API
        url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/ohlcv/historical"
        params = {
            "symbol": symbol,
            "convert": convert,
            "time_period": "daily",
            "count": min(days, 365),  # Límite según plan de API
            "interval": "daily"
        }
        
        # Headers con API Key
        headers = {
            "Accepts": "application/json",
            "X-CMC_PRO_API_KEY": CMC_API_KEY
        }

        # Solicitud HTTP
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=20
        )
        
        # Manejo de errores HTTP
        if response.status_code == 403:
            logger.error("Acceso denegado - Verifica tu API Key y plan de CoinMarketCap")
            return []
            
        response.raise_for_status()
        
        # Procesamiento de datos
        processed = []
        quotes = response.json().get('data', {}).get('quotes', [])
        
        if not quotes:
            logger.warning("No se obtuvieron datos en la respuesta")
            return []

        for quote in quotes:
            try:
                q = quote.get('quote', {}).get(convert, {})
                if not q:
                    continue

                # Validación de campos requeridos
                required_fields = ['timestamp', 'open', 'high', 'low', 'close']
                if not all(field in q for field in required_fields):
                    logger.warning(f"Faltan campos en quote: {q.keys()}")
                    continue

                # Parseo de timestamp
                timestamp = datetime.strptime(
                    quote['timestamp'], 
                    '%Y-%m-%dT%H:%M:%S.%fZ'
                ).replace(tzinfo=timezone.utc)
                
                # Validación de precios
                ohlc = {
                    'open': float(q['open']),
                    'high': float(q['high']),
                    'low': float(q['low']),
                    'close': float(q['close'])
                }
                
                # Validación lógica OHLC
                if not (ohlc['high'] >= ohlc['low'] and 
                        ohlc['high'] >= ohlc['close'] >= ohlc['low'] and
                        ohlc['high'] >= ohlc['open'] >= ohlc['low']):
                    logger.warning(f"Valores OHLC inconsistentes: {ohlc}")
                    continue

                # Construcción del registro
                processed.append({
                    "time_open": timestamp.isoformat(),
                    "time_close": (timestamp + timedelta(days=1)).isoformat(),
                    **ohlc,
                    "volume": float(q['volume']) if q.get('volume') else None,
                    "nombre": symbol,
                    "intervalo": "1d",
                    "convert": convert,
                    "fuente": "CoinMarketCap"
                })

            except (ValueError, KeyError, TypeError) as e:
                logger.warning(f"Error procesando quote: {str(e)}")
                continue
                
        logger.info(f"Procesados {len(processed)} registros válidos de {len(quotes)}")
        return processed
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error de conexión: {str(e)}")
        return []
    except json.JSONDecodeError:
        logger.error("Respuesta no es JSON válido")
        return []
    except Exception as e:
        logger.error(f"Error inesperado: {str(e)}", exc_info=True)
        return [] 
  
def _procesar_datos_ohlcv(data: list, symbol: str, convert: str, fuente: str) -> list:
    """
    Procesa y valida datos OHLCV crudos de cualquier API.
    
    Args:
        data (list): Datos crudos de la API
        symbol (str): Símbolo de la criptomoneda
        convert (str): Moneda de conversión
        fuente (str): Fuente de los datos ('CoinGecko' o 'CoinMarketCap')
    
    Returns:
        list: Datos procesados y validados
    """
    processed = []
    
    for item in data:
        try:
            # Validación y normalización de fechas
            if fuente == "CoinGecko":
                timestamp = datetime.fromtimestamp(item[0]/1000, timezone.utc)
                open_, high, low, close = item[1:5]
                volume = None
            else:  # CoinMarketCap
                timestamp = datetime.strptime(item['time_open'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
                open_, high, low, close = item['open'], item['high'], item['low'], item['close']
                volume = item.get('volume')
            
            # Validación de precios
            if not all(isinstance(x, (int, float)) for x in [open_, high, low, close]):
                continue
                
            if not (high >= open_ >= low and high >= close >= low):
                continue
                
            processed.append({
                "time_open": timestamp.isoformat(),
                "time_close": (timestamp + timedelta(days=1)).isoformat(),
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume) if volume is not None else None,
                "nombre": symbol,
                "intervalo": "1d",
                "convert": convert,
                "fuente": fuente
            })
        except Exception as e:
            logger.warning(f"Error procesando item OHLCV: {str(e)}")
            continue
            
    logger.info(f"Procesados {len(processed)} registros válidos de {len(data)} para {symbol}")
    return processed
 
def _procesar_datos_ohlcv(data, symbol, convert):
    """Procesa los datos crudos de la API según estructura de tabla"""
    ohlcv_list = []
    for row in data:
        try:
            if len(row) != 5:  # [timestamp, open, high, low, close]
                continue
                
            # Validar que todos los valores numéricos existan
            if any(v is None for v in row[1:5]):
                logger.warning(f"Datos OHLC con valores nulos para {symbol}: {row}")
                continue
                
            timestamp_ms = row[0]
            time_open = datetime.fromtimestamp(timestamp_ms/1000, tz=timezone.utc)
            time_close = time_open + timedelta(days=1)  # Asume datos diarios
            
            # Validación básica de precios
            if not (row[2] >= row[1] >= row[3] and  # high >= open >= low
                    row[2] >= row[4] >= row[3]):    # high >= close >= low
                logger.warning(f"Datos OHLC inválidos para {symbol} en {time_open}")
                continue
                
            ohlcv_list.append({
                "time_open": time_open.isoformat(),
                "time_close": time_close.isoformat(),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": None,  # CoinGecko no provee volumen en este endpoint
                "nombre": symbol,
                "intervalo": "1d",
                "convert": convert,
                "fuente": "CoinGecko"
            })
        except Exception as e:
            logger.warning(f"Error procesando fila OHLCV: {str(e)}")
            continue
            
    return ohlcv_list

def obtener_intradia_cierres(symbol: str, convert="EUR", interval="1h", count=60, time_end=None):
    logger.info(f"Obteniendo cierres intradía para {symbol} desde CoinMarketCap...")
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/historical"
    params = {
        "symbol": symbol, "convert": convert,
        "interval": interval, "count": count
    }
    if time_end: params["time_end"] = time_end
    try:
        r = requests.get(url, headers=_cmc_headers(), params=params, timeout=15)
        r.raise_for_status()
        data = r.json()["data"]["quotes"]
        closes = [float(q["quote"][convert]["price"]) for q in data]
        ts = [q["timestamp"] for q in data]
        logger.info(f"Cierres intradía obtenidos para {symbol}: {len(closes)} registros")
        return np.array(closes, dtype=np.float64), ts
    except Exception as e:
        logger.error(f"Error obteniendo cierres intradía para {symbol}: {str(e)}", exc_info=True)
        return None, None

# --- Supabase ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

MAX_REGISTROS_DUPLICADOS = 1000  

# --- OHLCV Batch ---
def guardar_ohlcv_batch(nombre: str, intervalo: str, ohlcv_rows: list, convert: str = "EUR", fuente: str = "CoinGecko") -> bool:
    if not ohlcv_rows:
        return True

    registros_validos = []
    for row in ohlcv_rows:
        try:
            # Validación de datos
            time_open = datetime.fromisoformat(row['time_open'].replace('Z', '+00:00'))
            
            # Verificar si el registro ya existe
            existe = supabase.table("ohlcv").select("id").match({
                "nombre": nombre,
                "intervalo": intervalo,
                "time_open": time_open.isoformat()
            }).execute()
            
            if existe.data:
                continue  # Saltar registros existentes

            # Preparar registro válido
            registros_validos.append({
                "nombre": nombre,
                "intervalo": intervalo,
                "time_open": time_open.isoformat(),
                "time_close": (time_open + timedelta(days=1)).isoformat() if intervalo == "1d" else (time_open + timedelta(hours=1)).isoformat(),
                "open": round(float(row['open']), 8),
                "high": round(float(row['high']), 8),
                "low": round(float(row['low']), 8),
                "close": round(float(row['close']), 8),
                "volume": round(float(row['volume']), 8) if row.get('volume') is not None else None,
                "convert": convert,
                "fuente": fuente
            })
        except Exception as e:
            logger.warning(f"Error procesando fila - {str(e)}")
            continue

    if not registros_validos:
        logger.info("No hay registros nuevos para insertar")
        return True

    try:
        response = supabase.table("ohlcv").upsert(
            registros_validos,
            on_conflict="nombre,intervalo,time_open",
            returning="minimal"
        ).execute()
        
        return True if response.data else False
        
    except Exception as e:
        logger.error(f"Error crítico al insertar: {str(e)}")
        return False
  
def obtener_precios_historicos(nombre: str):
    """Histórico reciente desde Supabase con diagnóstico detallado."""
    logger.info(f"Obteniendo históricos para {nombre}")
    
    try:
        fecha_limite = ahora_madrid() - timedelta(hours=HORAS_HISTORICO)
        logger.info(f"Fecha límite: {fecha_limite}")
        
        # Consulta a Supabase
        resp = supabase.table("precios").select("precio,fecha")\
                     .eq("nombre", nombre)\
                     .gte("fecha", fecha_limite.strftime("%Y-%m-%d %H:%M:%S"))\
                     .order("fecha", desc=False)\
                     .limit(max(70, INTERVALO_RSI * 5)).execute()
        
        if not resp.data:
            logger.warning(f"No hay datos en la respuesta para {nombre}")
            return None
            
        logger.info(f"Se obtuvieron {len(resp.data)} registros")
        
        # Procesamiento de datos - asegurarse de devolver array de precios de cierre
        precios = []
        for reg in resp.data:
            try:
                precio = float(reg["precio"])
                if precio > 0:
                    precios.append(precio)
            except (ValueError, TypeError, KeyError) as e:
                logger.warning(f"Error procesando registro {reg}: {str(e)}")
                continue
        
        if not precios:
            logger.error("No hay precios válidos después del filtrado")
            return None
            
        return np.array(precios, dtype=np.float64)
        
    except Exception as e:
        logger.error(f"Error inesperado en obtener_precios_historicos: {str(e)}", exc_info=True)
        return None

def insertar_precio(nombre: str, precio: float, rsi: float = None):
    """Inserta datos en Supabase."""
    try:
        if not isinstance(precio, (int, float)) or precio <= 0:
            raise ValueError("Precio inválido")
        datos = {
            "nombre": nombre,
            "precio": float(precio),
            "rsi": float(rsi) if rsi is not None else None,
            "fecha": ahora_madrid().strftime("%Y-%m-%d %H:%M:%S.%f"),
        }
        logger.info(f"Insertando precio para {nombre}: {precio:.8f} (RSI: {rsi})")
        # Eliminar timeout
        resp = supabase.table("precios").insert(datos).execute()
        if resp.data:
            logger.info(f"Precio insertado para {nombre}")
            return True
        logger.warning(f"Respuesta inesperada de Supabase al insertar {nombre}: {resp}")
        return False
    except Exception as e:
        logger.error(f"Error insertando precio para {nombre}: {str(e)}", exc_info=True)
        return False

# --- Telegram ---
def enviar_telegram(mensaje: str):
    """Envía mensaje a Telegram con manejo de errores y fallback."""
    # Limpiar caracteres problemáticos
    mensaje = mensaje.replace("<?", "").replace("?>", "").replace("&", "&amp;")
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    try:
        logger.info("Enviando mensaje a Telegram...")
        # Primero intentamos con HTML
        payload_html = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        r = requests.post(url, json=payload_html, timeout=10)
        
        if r.status_code != 200:
            # Fallback a texto plano si hay error con HTML
            payload_plain = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": _a_texto_plano(mensaje),
                "disable_web_page_preview": True
            }
            r = requests.post(url, json=payload_plain, timeout=10)
            r.raise_for_status()
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Error enviando a Telegram: {str(e)}", exc_info=True)
    except Exception as e:
        logger.error(f"Error inesperado en Telegram: {str(e)}", exc_info=True)
 
def _a_texto_plano(m: str) -> str:
    """Convierte HTML a texto plano y sanitiza números."""
    # Reemplaza comas en decimales (ej: "30,04" -> "30.04")
    m = re.sub(r'(\d),(\d)', r'\1.\2', m)
    # Elimina tags HTML y caracteres problemáticos
    repl = [
        ("<b>", "*"), ("</b>", "*"), ("<i>", "_"), ("</i>", "_"),
        ("<code>", "`"), ("</code>", "`"), ("&lt;", "<"), ("&gt;", ">"),
        ("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'")
    ]
    for a, b in repl:
        m = m.replace(a, b)
    return m
   
# --- Endpoints ---
@app.route("/")
def home():
    return "Bot de Monitoreo Cripto - Endpoints: /health, /resumen", 200

@app.route("/health")
def health_check():
    try:
        supabase.table("precios").select("count", count="exact").limit(1).execute()
        return {"status": "healthy", "supabase": "connected", "timestamp": ahora_madrid().isoformat()}, 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}, 500

def construir_mensaje_moneda(moneda, precio, rsi, señal):
    ind = señal.get("indicadores") or {}
    msg = f"<b>{moneda}:</b> {precio:,.8f} €\n"
    
    if rsi is not None:
        color_rsi = "🟢" if rsi < 30 else "🔴" if rsi > 70 else "🟡"
        msg += f"{color_rsi} <b>RSI:</b> {rsi:.2f} (Compra<{ind.get('rsi_umbral_compra','?')}, Venta>{ind.get('rsi_umbral_venta','?')})\n"
    
    if ind.get('macd') is not None:
        trend = "↑" if ind.get('macd_raw',0) > ind.get('macd_signal_raw',0) else "↓"
        color_macd = "🟢" if trend == "↑" and señal.get('señal') == "COMPRA" else "🔴" if trend == "↓" and señal.get('señal') == "VENTA" else "⚪"
        msg += f"{color_macd} <b>MACD:</b> {ind['macd']:.4f} (Señal: {ind['macd_signal']:.4f}) <b>{trend}</b>\n"
    
    msg += f"📶 <b>Tendencia:</b> {señal.get('tendencia','?')}\n"
    # Recomendación basada en la señal
    recomendacion = recomendar_accion(
        señal.get('señal'),
        rsi,
        ind.get('macd_raw'),
        ind.get('macd_signal_raw'),
        señal.get('confianza'),
        ind.get('macd_delta'),
        ind.get('macd_vol'),
        señal.get('tendencia'),
        ind.get('zscore20'),
        ind.get('drawdown_pct')
    )
    msg += f"💡 <b>Recomendación:</b> {recomendacion}\n\n"
    
    return msg

from concurrent.futures import ThreadPoolExecutor
 
@app.route("/resumen")
def resumen():
    logger.info("=== INICIO DE EJECUCIÓN ===")
    
    try:
        # 1. Obtener y guardar datos OHLCV con manejo mejorado de errores
        for moneda in MONEDAS:
            intentos = 0
            max_intentos = 2
            datos_obtenidos = False
            
            while intentos < max_intentos and not datos_obtenidos:
                try:
                    logger.info(f"Obteniendo datos OHLCV para {moneda} (intento {intentos+1})")
                    ohlcv_data = obtener_ohlcv_diario(moneda, days=7)
                    
                    if ohlcv_data:
                        logger.info(f"Guardando {len(ohlcv_data)} registros para {moneda}")
                        fuente_usada = ohlcv_data[0].get("fuente", "Desconocido")
                        resultado = guardar_ohlcv_batch(
                            nombre=moneda,
                            intervalo="1d",
                            ohlcv_rows=ohlcv_data,
                            convert="EUR",
                            fuente=fuente_usada
                        )
                        if resultado:
                            datos_obtenidos = True
                        else:
                            logger.warning(f"Fallo al guardar datos para {moneda}")
                    else:
                        logger.warning(f"No se obtuvieron datos OHLCV para {moneda}")
                        
                except Exception as e:
                    logger.error(f"Error en intento {intentos+1} para {moneda}: {str(e)}", exc_info=True)
                
                intentos += 1
                if not datos_obtenidos and intentos < max_intentos:
                    time.sleep(2 ** intentos)  # Backoff exponencial entre intentos
                # Agrega esto aquí para evitar el rate limit de CoinGecko
                time.sleep(3)

        # 2. Obtener precios actuales para el análisis (manteniendo la lógica original)
        precios = obtener_precios_actuales()
        if not precios:
            enviar_telegram("⚠️ <b>Error crítico:</b> No se pudieron obtener los precios actuales")
            return "Error al obtener precios", 500

        mensaje = "📊 <b>Análisis Cripto Avanzado</b>\n════════════════════════\n\n"
        ahora = ahora_madrid()
 
        # Procesar cada moneda en paralelo (manteniendo la lógica original)
#=====================================
        def procesar_moneda(moneda):
            try:
                precio = precios[moneda]
                historicos = obtener_precios_historicos(moneda)
                
                if historicos is None or len(historicos) < INTERVALO_RSI:
                    return f"<b>{moneda}:</b> {precio:,.8f} €\n⚠️ Datos insuficientes\n\n"

                # Calcular indicadores
                rsi = calcular_rsi_mejorado(historicos)
                señal = generar_señal_rsi(rsi, precio, historicos, moneda)

                # Insertar precio con RSI
                insertar_precio(moneda, precio, rsi)

                # Obtener el último ID insertado para esa moneda
                resp = supabase.table("precios")\
                    .select("id")\
                    .eq("nombre", moneda)\
                    .order("fecha", desc=True)\
                    .limit(1)\
                    .execute()

                if resp.data:
                    ultimo_id = resp.data[0]["id"]
                    recomendacion_texto = recomendar_accion(
                        señal.get('señal'),
                        rsi,
                        señal['indicadores'].get('macd_raw'),
                        señal['indicadores'].get('macd_signal_raw'),
                        señal.get('confianza'),
                        señal['indicadores'].get('macd_delta'),
                        señal['indicadores'].get('macd_vol'),
                        señal.get('tendencia'),
                        señal['indicadores'].get('zscore20'),
                        señal['indicadores'].get('drawdown_pct')
                    )

                    supabase.table("precios").update({
                        "recomendacion": recomendacion_texto,
                        "confianza": señal.get("confianza")
                    }).eq("id", ultimo_id).execute()

                return construir_mensaje_moneda(moneda, precio, rsi, señal)

            except Exception as e:
                logger.error(f"Error procesando {moneda}: {str(e)}", exc_info=True)
                return f"<b>{moneda}:</b> Error en análisis\n\n"
#=====================================
        # Ejecutar en paralelo
        with ThreadPoolExecutor(max_workers=3) as executor:
            resultados = list(executor.map(procesar_moneda, MONEDAS))
        
        mensaje += "".join(resultados)
        mensaje += f"════════════════════════\n🔄 <i>Actualizado: {formatear_fecha(ahora)}</i>"
        
        enviar_telegram(mensaje)
        return "Resumen enviado", 200

    except Exception as e:
        logger.error(f"Error general en resumen: {str(e)}", exc_info=True)
        enviar_telegram("⚠️ <b>Error crítico:</b> Fallo en el análisis general")
        return "Error interno", 500
 
 # === función auxiliar para verificar registros existentes === 
def _existe_registro(nombre: str, intervalo: str, time_open: str) -> bool:
    """Verifica si un registro ya existe en la base de datos (ahora opcional gracias a UPSERT)"""
    try:
        time_open_dt = datetime.fromisoformat(time_open.replace('Z', '+00:00'))
        response = supabase.table("ohlcv").select("id", count="exact")\
                   .eq("nombre", nombre)\
                   .eq("intervalo", intervalo)\
                   .eq("time_open", time_open_dt.isoformat())\
                   .limit(1).execute()
        return response.count > 0
    except Exception as e:
        logger.warning(f"Error verificando existencia de registro: {str(e)}")
        return False
        
# Test mejorado
def limpiar_datos_prueba():
    """Elimina registros de prueba existentes"""
    try:
        supabase.table("ohlcv")\
            .delete()\
            .eq("nombre", "TEST")\
            .eq("intervalo", "1d")\
            .execute()
        logger.info("Datos de prueba limpiados exitosamente")
        return True
    except Exception as e:
        logger.error(f"Error limpiando datos de prueba: {str(e)}")
        return False

# Llamar esta función antes de ejecutar_pruebas()
def ejecutar_pruebas():
    logger.info("=== PRUEBAS SIMPLIFICADAS ===")
    
    # 1. Datos de prueba que cumplen todas las restricciones
    test_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    test_data = {
        "time_open": test_time.isoformat(),
        "open": 100.00000001,
        "high": 105.00000000,
        "low": 95.00000000,
        "close": 102.00000000,
        "volume": 1000.00000000
    }

    try:
        # 2. Inserción directa
        response = supabase.table("ohlcv").insert({
            "nombre": "TEST",
            "intervalo": "1d",
            "time_open": test_time.isoformat(),
            "time_close": (test_time + timedelta(days=1)).isoformat(),
            "open": test_data["open"],
            "high": test_data["high"],
            "low": test_data["low"],
            "close": test_data["close"],
            "volume": test_data["volume"],
            "convert": "EUR",
            "fuente": "Pruebas"
        }).execute()

        # 3. Verificación básica
        if not hasattr(response, 'data'):
            raise ValueError("La respuesta no contiene datos")
            
        logger.info("Prueba exitosa. Datos insertados correctamente.")
        return True
        
    except Exception as e:
        logger.error(f"Prueba fallida: {str(e)}")
        return False
    finally:
        # 4. Limpieza (opcional durante desarrollo)
        supabase.table("ohlcv").delete().eq("nombre", "TEST").execute()

def crear_datos_prueba():
    """Genera datos que cumplen con todas las restricciones"""
    ahora = datetime.now(timezone.utc)
    return [{
        "time_open": ahora.isoformat(),
        "open": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 102.0,
        "volume": 1000.0
    }]
  
if __name__ == "__main__":
    if ejecutar_pruebas():
        logger.info("=== PRUEBAS EXITOSAS ===")
        port = int(os.getenv("PORT", "10000"))
        app.run(host="0.0.0.0", port=port)
    else:
        logger.error("=== PRUEBAS FALLIDAS - NO SE INICIA EL SERVIDOR ===")

        sys.exit(1)  # Salir con código de error


