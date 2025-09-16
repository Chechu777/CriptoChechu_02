# monitor_criptos.py
import os, io, logging, traceback, time
from datetime import datetime
from flask import Flask, jsonify, request, send_file, Response
import requests, dotenv

# importar funciones desde historicos.py (asegúrate que está en el mismo dir / PYTHONPATH)
from historicos import (
    guardar_datos,
    guardar_datos_dias,
    resumen_completo,
    generar_grafico
)

# ============================
# Config y logger
dotenv.load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # id numérico o @username (mejor id)
PORT = int(os.getenv("PORT", 10000))
HOST = os.getenv("HOST", "0.0.0.0")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("monitor_criptos")

app = Flask(__name__)

# Monedas por defecto (usa las mismas que en historicos.py si quieres)
DEFAULT_MONEDAS = os.getenv("MONEDAS", "BTC,ETH,ADA,SHIB,SOL").split(",")

# ============================
# Helpers Telegram
def telegram_send_message(text: str, parse_mode: str = "Markdown"):
    """Envía un text message a Telegram. Devuelve response dict."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_TOKEN o TELEGRAM_CHAT_ID no configurados; omito envío.")
        return {"ok": False, "error": "telegram no configurado"}

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=20)
        r.raise_for_status()
        logger.info(f"Enviado mensaje a Telegram (status {r.status_code})")
        return r.json()
    except Exception as e:
        logger.exception("Error enviando mensaje a Telegram")
        return {"ok": False, "error": str(e)}

def telegram_send_photo(buf: io.BytesIO, caption: str = None, filename: str = "grafico.png"):
    """Envía una imagen (BytesIO) a Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM no configurado; omito envío foto")
        return {"ok": False, "error": "telegram no configurado"}

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    files = {
        "photo": (filename, buf)
    }
    data = {
        "chat_id": TELEGRAM_CHAT_ID
    }
    if caption:
        data["caption"] = caption

    try:
        r = requests.post(url, files=files, data=data, timeout=30)
        r.raise_for_status()
        logger.info("Foto enviada a Telegram")
        return r.json()
    except Exception as e:
        logger.exception("Error enviando foto a Telegram")
        return {"ok": False, "error": str(e)}

# ============================
# Endpoints

@app.route("/", methods=["GET"])
def index():
    return (
        "Monitor Criptos: endpoints disponibles:\n"
        "/resumen -> genera y envía resumen a Telegram\n"
        "/historicos_auto -> guarda históricos (1h y 1d) para todas las monedas\n"
        "/grafico?moneda=BTC -> genera gráfico PNG y lo devuelve\n"
        "/health -> health check\n"
    )

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat() + "Z"})

@app.route("/resumen", methods=["GET"])
def endpoint_resumen():
    """
    Genera resumen para las monedas por defecto (o parámetro ?monedas=BTC,ETH)
    y lo envía a Telegram. Devuelve el resultado de la operación.
    """
    monedas = request.args.get("monedas")
    if monedas:
        monedas_list = [m.strip().upper() for m in monedas.split(",") if m.strip()]
    else:
        monedas_list = [m.strip().upper() for m in DEFAULT_MONEDAS]

    try:
        resumen = resumen_completo(monedas_list)
        texto = resumen.get("resumen_txt") if isinstance(resumen, dict) else str(resumen)
        # enviar a telegram (si está configurado)
        tg_resp = telegram_send_message(texto, parse_mode="Markdown")
        return jsonify({"status": "ok", "tg_response": tg_resp, "resumen": texto})
    except Exception as e:
        logger.exception("Error en /resumen")
        return jsonify({"status": "error", "error": str(e), "trace": traceback.format_exc()}), 500
#==========================
@app.route("/historicos_auto", methods=["GET"])
def endpoint_historicos_auto():
    """
    Recorre monedas (o ?monedas=BTC,ETH) y llama a guardar_datos(...).
    También llama guardar_datos_dias(...) para históricos diarios si se solicita (?dias_dias=90).
    ⚠️ No usamos time.sleep porque bloquea Gunicorn → worker timeout.
    """
    monedas = request.args.get("monedas")
    if monedas:
        monedas_list = [m.strip().upper() for m in monedas.split(",") if m.strip()]
    else:
        monedas_list = [m.strip().upper() for m in DEFAULT_MONEDAS]

    dias = int(request.args.get("dias", 7))
    dias_dias = int(request.args.get("dias_dias", 90))
    rellenar_huecos = request.args.get("rellenar_huecos", "true").lower() in ("1", "true", "yes")

    resultados = []
    try:
        for m in monedas_list:
            try:
                logger.info(f"Guardando históricos 1h para {m} (dias={dias}, rellenar={rellenar_huecos})")
                r1 = guardar_datos(moneda=m, dias=dias, timeframe="1h", rellenar_huecos=rellenar_huecos)
                logger.info(f"Resultado guardar_datos({m}): {r1}")
            except Exception as e:
                logger.exception(f"Error guardando datos 1h para {m}")
                r1 = f"error: {str(e)}"

            try:
                logger.info(f"Guardando históricos 1d para {m} (dias={dias_dias})")
                r2 = guardar_datos_dias(moneda=m, dias=dias_dias)
                logger.info(f"Resultado guardar_datos_dias({m}): {r2}")
            except Exception as e:
                logger.exception(f"Error guardando datos 1d para {m}")
                r2 = {"error": str(e)}

            resultados.append({"moneda": m, "1h": r1, "1d": r2})

        return jsonify({"status": "ok", "resultados": resultados})

    except Exception as e:
        logger.exception("Error en /historicos_auto")
        return jsonify({"status": "error", "error": str(e), "trace": traceback.format_exc()}), 500

#=====================
@app.route("/grafico", methods=["GET"])
def endpoint_grafico():
    """
    Genera gráfico PNG en memoria para una moneda.
    Parámetro: ?moneda=BTC & ?dias=30
    Devuelve image/png.
    """
    moneda = request.args.get("moneda", "").strip().upper()
    if not moneda:
        return jsonify({"status": "error", "error": "parámetro 'moneda' requerido (ej: ?moneda=BTC)"}), 400
    dias = int(request.args.get("dias", 30))

    try:
        buf = generar_grafico(moneda, dias=dias)
        if buf is None:
            return jsonify({"status": "error", "error": f"No hay datos para {moneda}"}), 404
        # devolver como image/png desde memoria
        buf.seek(0)
        return send_file(buf, mimetype="image/png", download_name=f"{moneda}_grafico.png")
    except Exception as e:
        logger.exception("Error generando gráfico")
        return jsonify({"status": "error", "error": str(e), "trace": traceback.format_exc()}), 500

# Endpoint útil para enviar gráfico a telegram (opcional)
@app.route("/grafico_send", methods=["GET"])
def endpoint_grafico_send():
    moneda = request.args.get("moneda", "").strip().upper()
    if not moneda:
        return jsonify({"status": "error", "error": "parámetro 'moneda' requerido"}), 400
    dias = int(request.args.get("dias", 30))
    caption = request.args.get("caption")

    try:
        buf = generar_grafico(moneda, dias=dias)
        if buf is None:
            return jsonify({"status": "error", "error": f"No hay datos para {moneda}"}), 404
        buf.seek(0)
        tg_resp = telegram_send_photo(buf, caption=caption or f"{moneda} - {dias}d")
        return jsonify({"status": "ok", "tg_response": tg_resp})
    except Exception as e:
        logger.exception("Error en /grafico_send")
        return jsonify({"status": "error", "error": str(e), "trace": traceback.format_exc()}), 500

# ============================
if __name__ == "__main__":
    logger.info(f"Arrancando monitor_criptos en {HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False)


