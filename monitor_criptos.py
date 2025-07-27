import os
import requests
import random
from flask import Flask
from supabase import create_client, Client
from pytz import timezone
from datetime import datetime, timedelta

app = Flask(__name__)

# Variables de entorno
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
COINMARKETCAP_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

CRIPTOS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]

# Inicializar Supabase
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
        precios = {}
        for cripto in CRIPTOS:
            precio = data[cripto]["quote"]["EUR"]["price"]
            precios[cripto] = precio
        return precios
    except Exception as e:
        enviar_mensaje(f"⚠️ Error al obtener precios: {e}")
        return {}

def guardar_precios(precios):
    ahora = datetime.utcnow().isoformat()
    for cripto, precio in precios.items():
        precio_formateado = f"{precio:.12f}"
        try:
            supabase.table("precios_historicos").insert({
                "cripto": cripto,
                "precio": precio_formateado,
                "timestamp": ahora
            }).execute()
        except Exception as e:
            enviar_mensaje(f"❌ Error guardando {cripto}: {e}")

def debe_ejecutar():
    ahora = datetime.utcnow()
    try:
        res = supabase.table("ejecuciones").select("*").order("timestamp", desc=True).limit(1).execute()
        registros = res.data
        if not registros:
            # Primera vez, guardar y permitir ejecución
            supabase.table("ejecuciones").insert({"timestamp": ahora.isoformat()}).execute()
            return True
        ultima = datetime.fromisoformat(registros[0]["timestamp"])
        if (ahora - ultima) > timedelta(minutes=60):
            supabase.table("ejecuciones").insert({"timestamp": ahora.isoformat()}).execute()
            return True
        return False
    except Exception as e:
        enviar_mensaje(f"⚠️ Error validando ejecución: {e}")
        return True  # Por si hay error, mejor no bloquear

def generar_recomendacion(rsi):
    if rsi < 30:
        return "Te aconsejo que *compres* 🟢 (RSI bajo)"
    elif rsi > 70:
        return "Te aconsejo que *vendas* 🔴 (RSI alto)"
    else:
        return "Te aconsejo que te estés *quieto por ahora* 🟡 (RSI neutro)"

@app.route("/resumen")
def resumen_manual():
    if not debe_ejecutar():
        return "⏳ Ya se ejecutó recientemente. Espera unos minutos."

    precios = obtener_precios()
    if not precios:
        return "Error al obtener precios"

    guardar_precios(precios)

    mensaje = "📊 *Resumen Manual de Criptomonedas*\n\n"
    for cripto, precio in precios.items():
        rsi = round(random.uniform(20, 80), 1)
        consejo = generar_recomendacion(rsi)

        if precio < 0.01:
            precio_str = f"{precio:,.12f}"
        else:
            precio_str = f"{precio:,.5f}"

        mensaje += f"*{cripto}*: {precio_str} €\nRSI: {rsi} → {consejo}\n\n"

    hora_europa = datetime.now(timezone("Europe/Madrid"))
    mensaje += f"⏱️ Actualizado: {hora_europa.strftime('%d/%m %H:%M')} (Hora Europa)"

    enviar_mensaje(mensaje)
    return "Resumen enviado correctamente ✅"

@app.route("/")
def home():
    return "✅ Monitor Criptos Activo"

if __name__ == "__main__":
    app.run(debug=True)
