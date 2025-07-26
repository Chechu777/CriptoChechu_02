import os
import requests
from flask import Flask, request
from datetime import datetime
from supabase import create_client, Client

app = Flask(__name__)

# Variables de entorno
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Criptomonedas a monitorear
CRIPTOS = ["BTC", "ADA", "SHIBA", "SOL"]

# Crear cliente de Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def obtener_precios():
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": os.getenv("COINMARKETCAP_API_KEY")}
    params = {"symbol": ",".join(CRIPTOS), "convert": "EUR"}

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()["data"]
        precios = {
            cripto: round(data[cripto]["quote"]["EUR"]["price"], 5)
            for cripto in CRIPTOS
        }
        return precios
    except Exception as e:
        enviar_mensaje(f"⚠️ Error al obtener precios: {e}")
        return {}

def guardar_precios_en_supabase(precios):
    timestamp_actual = datetime.utcnow().isoformat()

    for cripto, precio in precios.items():
        data = {
            "cripto": cripto,
            "precio": precio,
            "timestamp": timestamp_actual
        }
        try:
            supabase.table("precios_historicos").insert(data).execute()
        except Exception as e:
            enviar_mensaje(f"❌ Error al guardar en Supabase: {e}")

def enviar_mensaje(texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown"
    }
    requests.post(url, data=payload)

@app.route("/ver-precios")
def ver_precios():
    precios = obtener_precios()
    if not precios:
        return "Error al obtener precios."

    guardar_precios_en_supabase(precios)

    mensaje = "💰 *Precios actuales:*\n"
    for cripto, precio in precios.items():
        mensaje += f"• {cripto}: {precio} €\n"
    enviar_mensaje(mensaje)
    return "Precios enviados."

@app.route("/resumen-diario")
def resumen_diario():
    if not ENVIAR_RESUMEN_DIARIO:
        return "Resumen diario desactivado."

    precios = obtener_precios()
    if not precios:
        return "Error al obtener precios."

    guardar_precios_en_supabase(precios)

    ahora = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    mensaje = f"📊 *Resumen Diario ({ahora} UTC)*\n"
    for cripto, precio in precios.items():
        mensaje += f"• {cripto}: {precio} €\n"
    enviar_mensaje(mensaje)
    return "Resumen enviado."

if __name__ == "__main__":
    app.run(debug=True)
