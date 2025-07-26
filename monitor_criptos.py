import os
import requests
from flask import Flask
from datetime import datetime
from supabase import create_client, Client

app = Flask(__name__)

# Variables de entorno
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
COINMARKETCAP_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

CRIPTOS = ["BTC", "ETH", "ADA", "SHIBA", "SOL"]

# Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def enviar_mensaje(texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown"
    })

def obtener_precios():
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": COINMARKETCAP_API_KEY}
    params = {"symbol": ",".join(CRIPTOS), "convert": "EUR"}

    try:
        res = requests.get(url, headers=headers, params=params)
        data = res.json()["data"]
        precios = {
            cripto: round(data[cripto]["quote"]["EUR"]["price"], 5)
            for cripto in CRIPTOS
        }
        return precios
    except Exception as e:
        enviar_mensaje(f"⚠️ Error al obtener precios: {e}")
        return {}

def guardar_precios(precios):
    ahora = datetime.utcnow().isoformat()
    for cripto, precio in precios.items():
        try:
            supabase.table("precios_historicos").insert({
                "cripto": cripto,
                "precio": precio,
                "timestamp": ahora
            }).execute()
        except Exception as e:
            enviar_mensaje(f"❌ Error guardando {cripto}: {e}")

@app.route("/resumen")
def resumen_manual():
    precios = obtener_precios()
    if not precios:
        return "Error al obtener precios"

    guardar_precios(precios)

    mensaje = "📊 *Resumen Manual de Criptomonedas*\n\n"
    for cripto, precio in precios.items():
        mensaje += f"• {cripto}: {precio} €\n"

    mensaje += f"\n⏱️ Actualizado: {datetime.now().strftime('%d/%m %H:%M')} (Hora Europa)"
    enviar_mensaje(mensaje)
    return "Resumen enviado correctamente ✅"

@app.route("/")
def home():
    return "✅ Monitor Criptos Activo"

if __name__ == "__main__":
    app.run(debug=True)
