# monitor_criptos.py

import os
import requests
import numpy as np
from flask import Flask
from datetime import datetime, timedelta
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import logging
import traceback

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

# --- Flask ---
app = Flask(__name__)
application = app  # Render

# --- Entorno ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

# --- Constantes ---
MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]
INTERVALO_RSI = 14
HORAS_HISTORICO = 48

def _env_float(key, default):
    try:
        return float(os.getenv(key, default))
    except Exception:
        return float(default)

MACD_SIGMA_K = _env_float("MACD_SIGMA_K", 0.5)            # umbral base (0.5σ)
MACD_SIGMA_K_TEND = _env_float("MACD_SIGMA_K_TEND", 0.35) # si coincide con tendencia
PENDIENTE_UMBRAL_REL = _env_float("PENDIENTE_UMBRAL_REL", 0.0005)  # 0.05%

# --- Supabase ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Utilidades ---
def ahora_madrid():
    return datetime.now(ZoneInfo("Europe/Madrid"))

def formatear_fecha(fecha):
    return fecha.strftime("%d/%m/%Y %H:%M")

# --- Indicadores ---
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

        avg_gain = np.mean(ganancias[:periodo])
        avg_loss = np.mean(perdidas[:periodo])

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
    except Exception:
        logging.error("Error calculando RSI", exc_info=True)
        return None

def calcular_macd(cierres, periodo_largo=26, periodo_corto=12, periodo_senal=9):
    """Calcula MACD clásico con EMAs."""
    try:
        if len(cierres) < periodo_largo + periodo_senal:
            return None, None, None

        c = np.array(cierres, dtype=np.float64)

        def ema(data, period):
            if len(data) < period:
                return np.mean(data)
            alpha = 2 / (period + 1)
            e = np.zeros_like(data)
            e[0] = data[0]
            for i in range(1, len(data)):
                e[i] = alpha * data[i] + (1 - alpha) * e[i - 1]
            return e[-1]

        ema_c = ema(c, periodo_corto)
        ema_l = ema(c, periodo_largo)
        macd_line = ema_c - ema_l

        macd_values = []
        for i in range(periodo_corto, len(c)):
            macd_values.append(ema(c[: i + 1], periodo_corto) - ema(c[: i + 1], periodo_largo))

        signal_line = ema(np.array(macd_values), periodo_senal) if len(macd_values) >= periodo_senal else macd_line
        hist = macd_line - signal_line

        print(f"DBG:macd macd={macd_line:.6f} signal={signal_line:.6f} hist={hist:.6f}")
        return macd_line, signal_line, hist
    except Exception:
        logging.error("Error calculando MACD", exc_info=True)
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
            print(f"DBG:confianza datos_insuf rsi={rsi} macd={macd} sig={macd_signal}")
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
        print(f"DBG:confianza rsi={rsi} delta={delta:.6g} vol={vol:.6g} relevante={relevante} tend={tend} -> {conf}")
        return conf
    except Exception:
        return 1

def generar_señal_rsi(rsi: float, precio_actual: float, historico) -> dict:
    """Señal combinada RSI + MACD (relativo a σ) + tendencia (+ persistencia y desempate)."""
    try:
        if rsi is None or historico is None or len(historico) < 35:
            return {"señal": "DATOS_INSUFICIENTES", "confianza": 0, "tendencia": "DESCONOCIDA", "indicadores": {}}

        h = np.asarray(historico, dtype=np.float64)
        macd, macd_signal, _ = calcular_macd(h)
        tendencia = _tendencia_por_pendiente(h, puntos=12, umbral_rel=PENDIENTE_UMBRAL_REL)

        # Umbrales dinámicos RSI (cap ±5)
        volatilidad = np.std(h[-10:]) / max(1e-12, np.mean(h[-10:]))
        ajuste = min(volatilidad * 20, 5)
        rsi_sobrecompra = 70 - ajuste / 2
        rsi_sobreventa = 30 + ajuste / 2

        # Señal base por RSI
        if rsi < rsi_sobreventa:
            senal_rsi = "COMPRA"
        elif rsi > rsi_sobrecompra:
            senal_rsi = "VENTA"
        else:
            senal_rsi = "NEUTRO"

        # --- Refuerzo por MACD con umbral relativo a σ ---
        senal = senal_rsi
        if macd is not None and macd_signal is not None:
            delta = macd - macd_signal

            # σ de las últimas diferencias de precio
            difs = np.diff(h[-27:]) if len(h) >= 27 else np.diff(h)
            vol = np.std(difs)

            # Umbral base
            relevante = abs(delta) > MACD_SIGMA_K * max(1e-12, vol)

            # [PATCH-3] Persistencia del cruce (2 ticks seguidos)
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

            # Inclinar la balanza si es relevante
            if relevante:
                if delta > 0 and rsi > 35:
                    senal = "COMPRA" if senal_rsi != "VENTA" else senal_rsi
                elif delta < 0 and rsi < 65:
                    senal = "VENTA" if senal_rsi != "COMPRA" else senal_rsi

            print(f"DBG:macd_ref delta={delta:.6g} vol={vol:.6g} relevante={relevante} tend={tend}")

        # Desempate si todo apunta al mismo lado (tendencia + RSI + MACD lado)
        if senal == "NEUTRO" and macd is not None and macd_signal is not None:
            if tendencia == "BAJA" and rsi < 45 and macd < macd_signal:
                senal = "VENTA"
            elif tendencia == "ALZA" and rsi > 55 and macd > macd_signal:
                senal = "COMPRA"

        confianza = calcular_confianza(h, rsi, macd, macd_signal)
        indicadores = {
            "rsi": round(rsi, 2),
            "macd": round(macd, 6) if macd is not None else None,
            "macd_signal": round(macd_signal, 6) if macd_signal is not None else None,
            "rsi_umbral_compra": round(rsi_sobreventa, 2),
            "rsi_umbral_venta": round(rsi_sobrecompra, 2),
        }
        print(f"DBG:senal rsi={rsi} base={senal_rsi} -> final={senal} tend={tendencia} conf={confianza}")
        return {"señal": senal, "confianza": confianza, "tendencia": tendencia, "indicadores": indicadores}
    except Exception:
        logging.error("Error en generar_señal_rsi", exc_info=True)
        print("DBG:EXC generar_señal_rsi", traceback.format_exc())
        return {"señal": "ERROR", "confianza": 0, "tendencia": "DESCONOCIDA", "indicadores": {}}

def recomendar_accion(senal: str, rsi: float | None, macd: float | None, macd_signal: float | None, confianza: int) -> str:
    """Recomendación condicionada a confirmación MACD."""
    try:
        def confirma_compra():
            return macd is not None and macd_signal is not None and macd > macd_signal
        def confirma_venta():
            return macd is not None and macd_signal is not None and macd < macd_signal

        if senal == "COMPRA":
            if confirma_compra():
                txt = "🟢 Podrías comprar" + (" (señal fuerte)" if confianza >= 4 else " (señal débil)" if confianza <= 2 else "")
            else:
                txt = "⚪ Quieto chato, no hagas huevadas (espera confirmación MACD)"
        elif senal == "VENTA":
            if confirma_venta():
                txt = "🔴 Podrías vender" + (" (señal fuerte)" if confianza >= 4 else " (señal débil)" if confianza <= 2 else "")
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

# --- IO: APIs / DB ---
def obtener_precios_actuales():
    """CoinMarketCap EUR"""
    try:
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        params = {"symbol": ",".join(MONEDAS), "convert": "EUR"}
        headers = {"Accepts": "application/json", "X-CMC_PRO_API_KEY": CMC_API_KEY}
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        datos = r.json()
        precios = {}
        for m in MONEDAS:
            try:
                precio = float(datos["data"][m]["quote"]["EUR"]["price"])
                if precio <= 0:
                    raise ValueError("Precio no positivo")
                precios[m] = precio
            except (KeyError, ValueError) as e:
                logging.error(f"Error procesando {m}: {e}")
                return None
        print(f"DBG:precios {precios}")
        return precios
    except requests.exceptions.RequestException:
        logging.error("Error API CoinMarketCap", exc_info=True)
        return None

def obtener_precios_historicos(nombre: str):
    """Histórico reciente desde Supabase."""
    try:
        fecha_limite = ahora_madrid() - timedelta(hours=HORAS_HISTORICO)
        resp = supabase.table("precios").select("precio, fecha") \
            .eq("nombre", nombre) \
            .gte("fecha", fecha_limite.strftime("%Y-%m-%d %H:%M:%S")) \
            .order("fecha", desc=False) \
            .limit(max(60, INTERVALO_RSI * 5)).execute()
        data = resp.data
        logging.info(f"Datos crudos de Supabase para {nombre}: {data}")
        if not data:
            return None
        precios = []
        for reg in data:
            try:
                p = float(reg["precio"])
                if p > 0:
                    precios.append(p)
            except (ValueError, TypeError):
                continue
        arr = np.array(precios) if precios else None
        print(f"DBG:historico {nombre} n={len(arr) if arr is not None else 0}")
        return arr
    except Exception:
        logging.error("Error obteniendo históricos", exc_info=True)
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
        resp = supabase.table("precios").insert(datos).execute()
        if resp.data:
            logging.info(f"Insertado {nombre}: Precio={precio:.8f} | RSI={rsi if rsi is not None else 'NULL'}")
            print(f"DBG:insert {nombre} ok")
            return True
        logging.warning(f"Respuesta inesperada de Supabase: {resp}")
        print(f"DBG:insert {nombre} sin data")
        return False
    except Exception:
        logging.error(f"Error insertando {nombre}", exc_info=True)
        print("DBG:EXC insertar_precio", traceback.format_exc())
        return False

# --- Telegram ---
def enviar_telegram(mensaje: str):
    """Envía mensaje a Telegram con manejo de errores y fallback."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload_html = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload_html, timeout=10)
        if r.status_code == 200:
            print("DBG:telegram enviado OK (HTML)")
            return
        body = (r.text or "")[:500]
        logging.error(f"Telegram {r.status_code}: {body}")
        print(f"DBG:telegram resp={r.status_code} body={body}")
        if "parse" in body.lower() or "entity" in body.lower():
            payload_plain = {"chat_id": TELEGRAM_CHAT_ID, "text": _a_texto_plano(mensaje), "disable_web_page_preview": True}
            r2 = requests.post(url, json=payload_plain, timeout=10)
            print(f"DBG:telegram fallback status={r2.status_code} body={(r2.text or '')[:300]}")
            r2.raise_for_status()
            return
        if "chat not found" in body.lower():
            logging.error("Verifica TELEGRAM_CHAT_ID.")
        if "bot was blocked" in body.lower():
            logging.error("El usuario bloqueó al bot.")
        if "message is too long" in body.lower():
            logging.error("Mensaje supera 4096 caracteres; recórtalo.")
        r.raise_for_status()
    except requests.exceptions.RequestException:
        logging.error("Error enviando a Telegram", exc_info=True)
        print("DBG:EXC telegram", traceback.format_exc())
    except Exception:
        logging.error("Error inesperado en Telegram", exc_info=True)
        print("DBG:EXC telegram", traceback.format_exc())

def _a_texto_plano(m: str) -> str:
    """Convierte un HTML mínimo a texto plano para fallback."""
    repl = (("<b>", ""), ("</b>", ""), ("<i>", ""), ("</i>", ""), ("<u>", ""), ("</u>", ""),
            ("<code>", "`"), ("</code>", "`"), ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"))
    out = m
    for a, b in repl:
        out = out.replace(a, b)
    return out

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
        logging.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}, 500

@app.route("/resumen")
def resumen():
    try:
        precios = obtener_precios_actuales()
        if not precios:
            enviar_telegram("⚠️ <b>Error crítico:</b> No se pudieron obtener los precios actuales")
            return "Error al obtener precios", 500

        mensaje = "📊 <b>Análisis Cripto Avanzado</b>\n════════════════════════\n\n"
        ahora = ahora_madrid()

        for moneda in MONEDAS:
            try:
                precio = precios[moneda]
                historicos = obtener_precios_historicos(moneda)

                if historicos is None or len(historicos) < 10:
                    mensaje += f"<b>{moneda}:</b> {precio:,.8f} €\n⚠️ Datos insuficientes para análisis\n\n"
                    print(f"DBG:{moneda} insuficiente n={0 if historicos is None else len(historicos)}")
                    insertar_precio(moneda, precio, None)
                    continue

                rsi = calcular_rsi(historicos)
                señal = generar_señal_rsi(rsi, precio, historicos)
                insertar_precio(moneda, precio, rsi)

                mensaje += f"<b>{moneda}:</b> {precio:,.8f} €\n"
                ind = señal.get("indicadores") or {}

                rsi_val = ind.get("rsi")
                if rsi_val is not None:
                    mensaje += f"📈 <b>RSI:</b> {rsi_val} (Compra&lt;{ind.get('rsi_umbral_compra','?')}, Venta&gt;{ind.get('rsi_umbral_venta','?')})\n"
                else:
                    mensaje += "📈 <b>RSI:</b> No disponible\n"

                macd_val = ind.get("macd"); macd_sig = ind.get("macd_signal")
                if macd_val is not None and macd_sig is not None:
                    macd_trend = "↑" if macd_val > macd_sig else "↓"
                    mensaje += f"📊 <b>MACD:</b> {macd_val:.4f} (Señal: {macd_sig:.4f}) <b>{macd_trend}</b>\n"
                else:
                    mensaje += "📊 <b>MACD:</b> No disponible\n"

                mensaje += f"🔄 <b>Tendencia:</b> {señal.get('tendencia','?')}\n"
                conf = int(señal.get("confianza", 0))
                mensaje += f"🎯 <b>Señal:</b> <u>{señal.get('señal','?')}</u>\n"
                mensaje += f"🔍 <b>Confianza:</b> {'★' * conf}{'☆' * (5 - conf)} ({conf}/5)\n"
                reco = recomendar_accion(señal.get("señal"), rsi_val, macd_val, macd_sig, conf)
                mensaje += f"🤖 <b>Recomendación:</b> {reco}\n\n"

                print(f"DBG:{moneda} OK rsi={rsi_val} macd={macd_val} sig={macd_sig} conf={conf}")

            except Exception:
                logging.error(f"Error procesando {moneda}", exc_info=True)
                print(f"DBG:EXC procesando {moneda}", traceback.format_exc())
                mensaje += f"<b>{moneda}:</b> {precios.get(moneda, 'N/D')} €\n⚠️ Error en análisis - Ver logs\n\n"

        mensaje += "════════════════════════\n"
        mensaje += f"🔄 <i>Actualizado: {formatear_fecha(ahora)} (Hora Madrid)</i>\n"
        mensaje += "📶 <i>Indicadores: RSI(14), MACD(12,26,9)</i>"
        print(f"DBG:mensaje_len={len(mensaje)}")
        enviar_telegram(mensaje)
        return "Resumen enviado", 200

    except Exception:
        logging.critical("Error general en /resumen", exc_info=True)
        print("DBG:EXC resumen", traceback.format_exc())
        enviar_telegram("⚠️ <b>Error crítico:</b> Fallo al generar el resumen. Ver logs.")
        return "Error interno", 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
