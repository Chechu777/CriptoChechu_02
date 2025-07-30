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
    handlers=[logging.StreamHandler()] )

# [L~21] Flask
app = Flask(__name__)
application = app  # Alias para Render

# [L~35] Entorno
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

# [L~32] Constantes
MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]
INTERVALO_RSI = 14
HORAS_HISTORICO = 48
MINUTOS_ENTRE_REGISTROS = 55  # reservado

# [L~38] Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Utilidades -------------------------------------------------------------
# [L~44]
def ahora_madrid():
    return datetime.now(ZoneInfo("Europe/Madrid"))

# [L~46]
def formatear_fecha(fecha):
    return fecha.strftime("%d/%m/%Y %H:%M")

# [L~50]
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
# [L~64]
def calcular_confianza(historico, rsi, macd, macd_signal):
    """
    1–5 estrellas en base a:
      - RSI extremo
      - Confirmación MACD
      - Magnitud del cruce (delta_rel)
      - Alineación con tendencia por pendiente
    """
    try:
        h = np.asarray(historico, dtype=np.float64) if historico is not None else None
        if rsi is None or macd is None or macd_signal is None or h is None or len(h) < 26:
            print(f"DBG:confianza datos_insuf rsi={rsi} macd={macd} sig={macd_signal}")
            return 1

        delta = macd - macd_signal
        base = np.mean(h[-26:])
        delta_rel = abs(delta) / max(1e-12, base)  # tamaño del cruce relativo
        tendencia = _tendencia_por_pendiente(h, puntos=12, umbral_rel=0.0005)

        conf = 2  # base
        # +1 si RSI extremo
        if rsi < 30 or rsi > 70:
            conf += 1
        # +1 si MACD confirma el lado del RSI
        if (rsi < 50 and delta > 0) or (rsi > 50 and delta < 0):
            conf += 1
        # +1 si el cruce es relevante
        if delta_rel > 0.001:
            conf += 1
        # Ajuste por tendencia opuesta
        if (tendencia == "ALZA" and delta < 0) or (tendencia == "BAJA" and delta > 0):
            conf = max(1, conf - 1)

        conf = int(max(1, min(5, conf)))
        print(f"DBG:confianza rsi={rsi} delta_rel={delta_rel:.6f} tend={tendencia} -> {conf}")
        return conf
    except Exception:
        return 1

# [L~104]
def calcular_rsi(cierres, periodo: int = INTERVALO_RSI) -> float:
    """RSI de Wilder con manejo de edge cases."""
    if cierres is None:
        return None
    try:
        c = np.asarray(cierres, dtype=np.float64)
        if len(c) < periodo + 1:
            return None
        deltas = np.diff(c)
        ganancias = np.clip(deltas, 0, None)
        perdidas = np.clip(-deltas, 0, None)

        # Promedios iniciales
        avg_gain = np.mean(ganancias[:periodo])
        avg_loss = np.mean(perdidas[:periodo])

        # Suavizado Wilder
        for i in range(periodo, len(deltas)):
            avg_gain = (avg_gain * (periodo - 1) + ganancias[i]) / periodo
            avg_loss = (avg_loss * (periodo - 1) + perdidas[i]) / periodo
        if avg_loss == 0:
            rsi = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        rsi = round(float(np.clip(rsi, 0, 100)), 2)
        print(f"DBG:rsi(wilder) valor={rsi}")
        return rsi
    except Exception as e:
        logging.error(f"Error calculando RSI: {str(e)}")
        return None
# [L~136]
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
# [L~161]
def _tendencia_por_pendiente(historico, puntos=12, umbral_rel=0.0005):
    """
    Evalúa la pendiente de los últimos 'puntos' cierres.
    umbral_rel ~0.05% del precio medio: ALZA/BAJA; si no, PLANA.
    """
    h = np.asarray(historico[-max(5, puntos):], dtype=np.float64)
    y = h
    x = np.arange(len(h), dtype=np.float64)
    m, b = np.polyfit(x, y, 1)
    rel = m / max(1e-12, np.mean(h))
    if rel > umbral_rel:
        return "ALZA"
    if rel < -umbral_rel:
        return "BAJA"
    return "PLANA"

# [L~193]
def generar_señal_rsi(rsi: float, precio_actual: float, historico) -> dict:
    try:
        if rsi is None or historico is None or len(historico) < 35:  # asegurar MACD
            return {"señal": "DATOS_INSUFICIENTES", "confianza": 0, "tendencia": "DESCONOCIDA", "indicadores": {}}

        h = np.asarray(historico, dtype=np.float64)
        macd, macd_signal, hist = calcular_macd(h)

        # Tendencia por pendiente (más fiel que medias cortas/largas simples)
        tendencia = _tendencia_por_pendiente(h, puntos=12, umbral_rel=0.0005)

        # Umbral dinámico RSI (cap ±5 máx)
        volatilidad = np.std(h[-10:]) / max(1e-12, np.mean(h[-10:]))
        ajuste = min(volatilidad * 20, 5)  # antes 40 y cap 15 -> demasiado ancho
        rsi_sobrecompra = 70 - ajuste/2
        rsi_sobreventa  = 30 + ajuste/2

        # Señal base por RSI
        if rsi < rsi_sobreventa:
            senal_rsi = "COMPRA"
        elif rsi > rsi_sobrecompra:
            senal_rsi = "VENTA"
        else:
            senal_rsi = "NEUTRO"

        # --- Refuerzo por MACD con filtro de magnitud ---
        senal = senal_rsi
        macd_ok = (macd is not None and macd_signal is not None)
        if macd_ok:
            delta = macd - macd_signal
            # Magnitud relativa del cruce vs precio medio de 26 (evita ruido)
            base = np.mean(h[-26:]) if len(h) >= 26 else np.mean(h)
            delta_rel = abs(delta) / max(1e-12, base)

            # Umbral de relevancia (0.1% del precio)
            relevante = delta_rel > 0.001

            if relevante:
                if delta > 0 and rsi > 35:     # fuerza alcista
                    senal = "COMPRA" if senal_rsi != "VENTA" else senal_rsi
                elif delta < 0 and rsi < 65:   # fuerza bajista
                    senal = "VENTA"  if senal_rsi != "COMPRA" else senal_rsi

        confianza = calcular_confianza(h, rsi, macd, macd_signal)

        indicadores = {
            "rsi": round(rsi, 2),
            "macd": round(macd, 6) if macd is not None else None,
            "macd_signal": round(macd_signal, 6) if macd_signal is not None else None,
            "rsi_umbral_compra": round(rsi_sobreventa, 2),
            "rsi_umbral_venta": round(rsi_sobrecompra, 2)
        }

        print(f"DBG:senal rsi={rsi} base={senal_rsi} -> final={senal} tend={tendencia} conf={confianza}")
        return {"señal": senal, "confianza": confianza, "tendencia": tendencia, "indicadores": indicadores}

    except Exception as e:
        logging.error(f"Error en generar_señal_rsi: {str(e)}", exc_info=True)
        print("DBG:EXC generar_señal_rsi", traceback.format_exc())
        return {"señal": "ERROR", "confianza": 0, "tendencia": "DESCONOCIDA", "indicadores": {}}

# [L~255]
def recomendar_accion(senal: str, rsi: float | None, macd: float | None, macd_signal: float | None, confianza: int) -> str:
    """
    Recomendación condicionada a confirmación MACD:
      - COMPRA  -> requiere macd > macd_signal
      - VENTA   -> requiere macd < macd_signal
      - Si no hay confirmación o datos, se recomienda esperar.
    """
    try:
        def confirma_compra():
            return macd is not None and macd_signal is not None and macd > macd_signal

        def confirma_venta():
            return macd is not None and macd_signal is not None and macd < macd_signal

        if senal == "COMPRA":
            if confirma_compra():
                txt = "🟢 Podrías comprar"
                if confianza >= 4:
                    txt += " (señal fuerte)"
                elif confianza <= 2:
                    txt += " (señal débil)"
            else:
                txt = "⚪ Quieto chato, no hagas huevadas (espera confirmación MACD)"

        elif senal == "VENTA":
            if confirma_venta():
                txt = "🔴 Podrías vender"
                if confianza >= 4:
                    txt += " (señal fuerte)"
                elif confianza <= 2:
                    txt += " (señal débil)"
            else:
                txt = "⚪ Quieto chato, no hagas huevadas (espera confirmación MACD)"

        elif senal == "NEUTRO":
            txt = "⚪ Quieto chato, no hagas huevadas"
        else:
            txt = "ℹ️ Sin datos suficientes para recomendar"

        print(f"DBG:reco senal={senal} macd={macd} sig={macd_signal} conf={confianza} -> {txt}")
        return txt

    except Exception:
        return "ℹ️ Sin datos suficientes para recomendar"

# --- IO: APIs / DB ----------------------------------------------------------
# [L~302]
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

# [L~331]
def obtener_precios_historicos(nombre: str):
    """Recupera precios históricos recientes desde Supabase"""
    try:
        fecha_limite = ahora_madrid() - timedelta(hours=HORAS_HISTORICO)
        response = supabase.table("precios").select(
            "precio, fecha"
        ).eq("nombre", nombre
        ).gte("fecha", fecha_limite.strftime("%Y-%m-%d %H:%M:%S")
        ).order("fecha", desc=False
        ).limit(max(60, INTERVALO_RSI * 5)).execute()

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

# [L~364]
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
# [L~394]
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

# [L~443]
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
# [L~460]
@app.route("/")
def home():
    return "Bot de Monitoreo Cripto - Endpoints: /health, /resumen", 200

# [L~465]
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

# [L~479]
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

# [L~568]
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
