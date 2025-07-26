import os
import json
import requests
from flask import Flask, request
from datetime import datetime, timedelta

app = Flask(__name__)

price_history = {}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")

CRIPTO_LISTA = ["BTC", "ETH", "ADA", "SHIB", "SOL"]

def enviar_mensaje_telegram(texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

def obtener_precio_actual(cripto):
    headers = {
        "X-CMC_PRO_API_KEY": os.getenv("COINMARKETCAP_API_KEY")
    }
    params = {
        "symbol": cripto,
        "convert": "EUR"
    }
    response = requests.get("https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest", headers=headers, params=params)
    data = response.json()
    precio = data["data"][cripto]["quote"]["EUR"]["price"]
    
    # Guardar en historial
    timestamp = datetime.utcnow().isoformat()
    if cripto not in price_history:
        price_history[cripto] = []
    price_history[cripto].append({
        "timestamp": timestamp,
        "price": precio
    })
    # Limpiar histórico mayor a 2 horas
    price_history[cripto] = [
        p for p in price_history[cripto]
        if datetime.fromisoformat(p["timestamp"]) > datetime.utcnow() - timedelta(hours=2)
    ]
    
    return precio

def obtener_precio_hace_una_hora(cripto):
    if cripto not in price_history:
        return None
    hace_una_hora = datetime.utcnow() - timedelta(hours=1)
    posibles = [
        p["price"] for p in price_history[cripto]
        if datetime.fromisoformat(p["timestamp"]) <= hace_una_hora
    ]
    return posibles[-1] if posibles else None

def analizar_y_sugerir(cripto, precio_actual):
    precio_hora_pasada = obtener_precio_hace_una_hora(cripto)
    if not precio_hora_pasada:
        return f"{cripto}: Precio actual €{precio_actual:.4f} (esperando histórico para sugerencias)"

    diferencia = ((precio_actual - precio_hora_pasada) / precio_hora_pasada) * 100

    if diferencia > 5:
        consejo = "📈 *TE ACONSEJO QUE VENDAS*"
    elif diferencia < -5:
        consejo = "📉 *TE ACONSEJO QUE COMPRES*"
    else:
        consejo = "🤔 *ESPERA, sin cambios fuertes*"

    return f"{cripto}: €{precio_actual:.4f} | Hace 1h: €{precio_hora_pasada:.4f} ({diferencia:+.2f}%)\n{consejo}"

@app.route("/resumen", methods=["GET"])
def resumen_diario():
    ahora = datetime.utcnow().strftime("%H:%M")
    es_hora_resumen = ahora == RESUMEN_HORA

    resumen = []
    for cripto in CRIPTO_LISTA:
        try:
            precio_actual = obtener_precio_actual(cripto)
            resultado = analizar_y_sugerir(cripto, precio_actual)
            resumen.append(resultado)
        except Exception as e:
            resumen.append(f"{cripto}: Error al obtener precio ({e})")

    mensaje = f"📊 *Resumen cripto {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC*\n\n" + "\n\n".join(resumen)

    # Enviar siempre al acceder
    enviar_mensaje_telegram(mensaje)

    if es_hora_resumen and ENVIAR_RESUMEN_DIARIO:
        return "✅ Resumen enviado a Telegram por hora configurada ⏰"
    else:
        return f"⏰ Resumen enviado manualmente (actual: {ahora} ≠ {RESUMEN_HORA})"

if __name__ == "__main__":
    app.run(debug=True)
