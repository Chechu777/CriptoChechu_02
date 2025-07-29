# monitor_criptos.py

import os
import requests
import numpy as np
import pandas as pd  # por si lo necesitas luego
from flask import Flask
from datetime import datetime, timedelta
from supabase import create_client, Client
from zoneinfo import ZoneInfo
from dateutil.parser import isoparse
import logging
import traceback

# [L~20] Logging básico
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

# [L~30] Flask
app = Flask(__name__)
application = app  # Alias para Render

# [L~35] Entorno
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

# [L~45] Constantes
MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]
INTERVALO_RSI = 14
HORAS_HISTORICO = 48
MINUTOS_ENTRE_REGISTROS = 55  # reservado

# [L~55] Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Utilidades -------------------------------------------------------------

# [L~65]
def ahora_madrid():
    return datetime.now(ZoneInfo("Europe/Madrid"))

# [L~70]
def formatear_fecha(fecha):
    return fecha.strftime("%d/%m/%Y %H:%M")

# [L~75]
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

# --- Indicadores ------------------------------------------------------------

# [L~95]
def calcular_confianza(historico, rsi, macd, macd_signal):
    """
    Devuelve 1-5 según la coherencia RSI/MACD.
    """
    try:
        if rsi is None or macd is None or macd_signal is None:
            return 1

        # Reglas simples pero efectivas
        if rsi < 30 and macd > macd_signal:
            return 5
        if rsi > 70 and macd < macd_signal:
            return 5
        if rsi < 30 or rsi > 70:
            return 4
        if (30 <= rsi <= 35 and macd > macd_signal) or (65 <= rsi <= 70 and macd < macd_signal):
            return 3
        if 40 <= rsi <= 60:
            return 2
        return 1
    finally:
        # Print para localizar rápido en logs
        print(f"DBG:confianza rsi={rsi} macd={macd} signal={macd_signal}")

# [L~125]
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
        rsi = round(max(0, min(100, rsi)), 2)
        print(f"DBG:rsi valor={rsi}")  # debug visible
        return rsi
    except Exception as e:
        logging.error(f"Error calculando RSI: {str(e)}")
        return None

# [L~165]
def calcular_macd(cierres, periodo_largo=26, periodo_corto=12, periodo_senal=9):
    """Calcula MACD usando numpy"""
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
                ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
            return ema[-1]

        ema_corta = calcular_ema(cierres, periodo_corto)
        ema_larga = calcular_ema(cierres, periodo_largo)
        macd_line = ema_corta - ema_larga

        macd_values = []
        for i in range(periodo_corto, len(cierres)):
            ema_c = calcular_ema(cierres[:i + 1], periodo_corto)
            ema_l = calcular_ema(cierres[:i + 1], periodo_largo)
            macd_values.append(ema_c - ema_l)

        if len(macd_values) >= periodo_senal:
            signal_line = calcular_ema(np.array(macd_values), periodo_senal)
        else:
            signal_line = macd_line

        histograma = macd_line - signal_line
        print(f"DBG:macd macd={macd_line:.5f} signal={signal_line:.5f} hist={histograma:.5f}")
        return macd_line, signal_line, histograma
    except Exception as e:
        logging.error(f"Error calculando MACD: {str(e)}")
        return None, None, None

# [L~215]
def generar_señal_rsi(rsi: float, precio_actual: float, historico) -> dict:
    """
    Genera señal y empaqueta indicadores.
    """
    try:
        if rsi is None or historico is None or len(historico) < 10:
            return {
                "señal": "DATOS_INSUFICIENTES",
                "confianza": 0,
                "tendencia": "DESCONOCIDA",
                "indicadores": {}
            }

        if isinstance(historico, list):
            historico = np.array(historico, dtype=np.float64)

        macd, macd_signal, _ = calcular_macd(historico)

        # Medias para tendencia
        media_corta = np.mean(historico[-5:])
        media_larga = np.mean(historico[-20:]) if len(historico) >= 20 else media_corta
        precio_actual = float(precio_actual)

        # Umbral dinámico RSI
        volatilidad = np.std(historico[-10:]) / max(1e-12, np.mean(historico[-10:]))
        ajuste_umbral = min(volatilidad * 40, 15)  # máx ±15
        rsi_sobrecompra = 70 - ajuste_umbral / 2
        rsi_sobreventa = 30 + ajuste_umbral / 2

        if rsi < rsi_sobreventa:
            señal_rsi = "COMPRA"
        elif rsi > rsi_sobrecompra:
            señal_rsi = "VENTA"
        else:
            señal_rsi = "NEUTRO"

        # Tendencia
        if precio_actual > media_corta > media_larga:
            tendencia = "ALZA"
        elif precio_actual < media_corta < media_larga:
            tendencia = "BAJA"
        else:
            tendencia = "PLANA"

        confianza = calcular_confianza(historico, rsi, macd, macd_signal)

        indicadores = {
            "rsi": round(rsi, 2),
            "macd": round(macd, 4) if macd is not None else None,
            "macd_signal": round(macd_signal, 4) if macd_signal is not None else None,
            "rsi_umbral_compra": round(rsi_sobreventa, 2),
            "rsi_umbral_venta": round(rsi_sobrecompra, 2)
        }

        print(f"DBG:senal rsi={rsi} senal={señal_rsi} tend={tendencia} conf={confianza}")
        return {
            "señal": señal_rsi,
            "confianza": confianza,
            "tendencia": tendencia,
            "indicadores": indicadores
        }

    except Exception as e:
        logging.error(f"Error en generar_señal_rsi: {str(e)}", exc_info=True)
        print("DBG:EXC generar_señal_rsi", traceback.format_exc())
        return {
            "señal": "ERROR",
            "confianza": 0,
            "tendencia": "DESCONOCIDA",
            "indicadores": {}
        }

# [L~290]
def recomendar_accion(senal: str, rsi: float | None, macd: float | None, macd_signal: float | None, confianza: int) -> str:
    """
    Devuelve texto de recomendación en base a la señal calculada.
    - 'COMPRA'  -> 'Podrías comprar'
    - 'VENTA'   -> 'Podrías vender'
    - 'NEUTRO'  -> 'Quieto chato, no hagas huevadas'
    - 'DATOS_INSUFICIENTES' / 'ERROR' -> aviso neutral
    """
    try:
        if senal == "COMPRA":
            txt = "🟢 Podrías comprar"
        elif senal == "VENTA":
            txt = "🔴 Podrías vender"
        elif senal == "NEUTRO":
            txt = "⚪ Quieto chato, no hagas huevadas"
        elif senal in ("DATOS_INSUFICIENTES", "ERROR"):
            txt = "ℹ️ Sin datos suficientes para recomendar"
        else:
            txt = "ℹ️ Sin datos suficientes para recomendar"

        # Añade matiz por confianza (opcional, breve)
        if senal in ("COMPRA", "VENTA"):
            if confianza >= 4:
                txt += " (señal fuerte)"
            elif confianza <= 2:
                txt += " (señal débil)"

        print(f"DBG:reco senal={senal} rsi={rsi} macd={macd} sig={macd_signal} conf={confianza} -> {txt}")
        return txt
    except Exception:
        return "ℹ️ Sin datos suficientes para recomendar"

# --- IO: APIs / DB ----------------------------------------------------------

# [L~300]
def obtener_precios_actuales():
    """CoinMarketCap EUR"""
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

        print(f"DBG:precios {precios}")
        return precios
    except requests.exceptions.RequestException as e:
        logging.error(f"Error API CoinMarketCap: {str(e)}")
        return None

# [L~340]
def obtener_precios_historicos(nombre: str):
    """Recupera precios históricos recientes desde Supabase"""
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

        arr = np.array(precios_validos) if precios_validos else None
        print(f"DBG:historico {nombre} n={len(arr) if arr is not None else 0}")
        return arr
    except Exception as e:
        logging.error(f"Error obteniendo históricos: {str(e)}")
        return None

# [L~380]
def insertar_precio(nombre: str, precio: float, rsi: float = None):
    """Inserta datos en Supabase con logging detallado"""
    try:
        if not isinstance(precio, (int, float)) or precio <= 0:
            raise ValueError("Precio inválido")

        datos = {
            "nombre": nombre,
            "precio": float(precio),
            "rsi": float(rsi) if rsi is not None else None,
            "fecha": ahora_madrid().strftime("%Y-%m-%d %H:%M:%S.%f")
        }

        response = supabase.table("precios").insert(datos).execute()

        if response.data:
            logging.info(f"Insertado {nombre}: Precio={precio:.8f} | RSI={rsi if rsi is not None else 'NULL'}")
            print(f"DBG:insert {nombre} ok")
            return True
        else:
            logging.warning(f"Respuesta inesperada de Supabase: {response}")
            print(f"DBG:insert {nombre} sin data")
            return False
    except Exception as e:
        logging.error(f"Error insertando {nombre}: {str(e)}", exc_info=True)
        print("DBG:EXC insertar_precio", traceback.format_exc())
        return False

# --- Telegram ---------------------------------------------------------------

# [L~420]
def enviar_telegram(mensaje: str):
    """Envía mensaje a Telegram con manejo de errores y fallback."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload_html = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': mensaje,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    try:
        r = requests.post(url, json=payload_html, timeout=10)
        if r.status_code == 200:
            print("DBG:telegram enviado OK (HTML)")
            return
        # Log detallado
        body = (r.text or "")[:500]
        logging.error(f"Telegram {r.status_code}: {body}")
        print(f"DBG:telegram resp={r.status_code} body={body}")

        # Fallback si es error de parseo HTML
        if "parse" in body.lower() or "entity" in body.lower():
            payload_plain = {
                'chat_id': TELEGRAM_CHAT_ID,
                'text': _a_texto_plano(mensaje),
                'disable_web_page_preview': True
            }
            r2 = requests.post(url, json=payload_plain, timeout=10)
            print(f"DBG:telegram fallback status={r2.status_code} body={(r2.text or '')[:300]}")
            r2.raise_for_status()
            return

        # Otros errores comunes: chat id, bot bloqueado, etc.
        if "chat not found" in body.lower():
            logging.error("Verifica TELEGRAM_CHAT_ID: ¿es el chat correcto y el bot está dentro del chat?")
        if "bot was blocked" in body.lower():
            logging.error("El usuario bloqueó al bot.")
        if "message is too long" in body.lower():
            logging.error("Mensaje supera 4096 caracteres; recórtalo.")

        r.raise_for_status()

    except requests.exceptions.RequestException as e:
        logging.error(f"Error enviando a Telegram: {str(e)}")
        print("DBG:EXC telegram", traceback.format_exc())
    except Exception as e:
        logging.error(f"Error inesperado en Telegram: {str(e)}")
        print("DBG:EXC telegram", traceback.format_exc())


def _a_texto_plano(m: str) -> str:
    """Convierte un HTML mínimo a texto plano para fallback."""
    # Quita etiquetas básicas y desescapa lo necesario
    repl = (
        ("<b>", ""), ("</b>", ""),
        ("<i>", ""), ("</i>", ""),
        ("<u>", ""), ("</u>", ""),
        ("<code>", "`"), ("</code>", "`"),
        ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&")
    )
    out = m
    for a, b in repl:
        out = out.replace(a, b)
    return out

# --- Endpoints --------------------------------------------------------------

# [L~450]
@app.route("/")
def home():
    return "Bot de Monitoreo Cripto - Endpoints: /health, /resumen", 200

# [L~455]
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

# [L~470]
@app.route("/resumen")
def resumen():
    try:
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

                # Si no hay histórico suficiente, informa y sigue
                if historicos is None or len(historicos) < 10:
                    mensaje += f"<b>{moneda}:</b> {precio:,.8f} €\n"
                    mensaje += "⚠️ Datos insuficientes para análisis\n\n"
                    print(f"DBG:{moneda} insuficiente n={0 if historicos is None else len(historicos)}")
                    # Aún así guarda el precio sin RSI
                    insertar_precio(moneda, precio, None)
                    continue

                # Indicadores
                rsi = calcular_rsi(historicos)
                macd, macd_signal, _ = calcular_macd(historicos)
                señal = generar_señal_rsi(rsi, precio, historicos)

                # Insertar en DB
                insertar_precio(moneda, precio, rsi)

                # Construir mensaje seguro
                mensaje += f"<b>{moneda}:</b> {precio:,.8f} €\n"

                indicadores = señal.get("indicadores") or {}

                rsi_val = indicadores.get("rsi")
                if rsi_val is not None:
                    # [L~510] — línea RSI del mensaje
                    mensaje += f"📈 <b>RSI:</b> {rsi_val} "
                    mensaje += f"<code>(Compra<{indicadores.get('rsi_umbral_compra','?')}, "
                    mensaje += f"Venta>{indicadores.get('rsi_umbral_venta','?')})</code>\n"
                else:
                    mensaje += "📈 <b>RSI:</b> No disponible\n"

                macd_val = indicadores.get("macd")
                macd_sig = indicadores.get("macd_signal")
                if macd_val is not None and macd_sig is not None:
                    macd_trend = "↑" if macd_val > macd_sig else "↓"
                    mensaje += f"📊 <b>MACD:</b> {macd_val:.4f} (Señal: {macd_sig:.4f}) <b>{macd_trend}</b>\n"
                else:
                    mensaje += "📊 <b>MACD:</b> No disponible\n"

                mensaje += f"🔄 <b>Tendencia:</b> {señal.get('tendencia','?')}\n"
                conf = int(señal.get('confianza', 0))
                mensaje += f"🎯 <b>Señal:</b> <u>{señal.get('señal','?')}</u>\n"
                mensaje += f"🔍 <b>Confianza:</b> {'★' * conf}{'☆' * (5 - conf)} ({conf}/5)\n\n"
                
                reco = recomendar_accion(señal.get('señal'), rsi_val, macd_val, macd_sig, conf)
                mensaje += f"🤖 <b>Recomendación:</b> {reco}\n\n"
                
                print(f"DBG:{moneda} OK rsi={rsi_val} macd={macd_val} sig={macd_sig} conf={conf}")

            except Exception as e:
                # No duplicamos cabecera; mostramos un bloque de error por moneda
                logging.error(f"Error procesando {moneda}: {str(e)}", exc_info=True)
                print(f"DBG:EXC procesando {moneda}", traceback.format_exc())
                mensaje += f"<b>{moneda}:</b> {precios.get(moneda, 'N/D')} €\n"
                mensaje += "⚠️ Error en análisis - Ver logs\n\n"

        # Pie del mensaje
        mensaje += "════════════════════════\n"
        mensaje += f"🔄 <i>Actualizado: {formatear_fecha(ahora)} (Hora Madrid)</i>\n"
        mensaje += f"📶 <i>Indicadores: RSI(14), MACD(12,26,9)</i>"

        # Enviar
        enviar_telegram(mensaje)
        return "Resumen enviado", 200

    except Exception as e:
        logging.critical(f"Error general en /resumen: {str(e)}", exc_info=True)
        print("DBG:EXC resumen", traceback.format_exc())
        enviar_telegram("⚠️ <b>Error crítico:</b> Fallo al generar el resumen. Ver logs.")
        return "Error interno", 500

# [L~570]
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
