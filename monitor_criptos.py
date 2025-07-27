import os
import requests
from datetime import datetime, timedelta
from flask import Flask, request
from supabase import create_client
import pytz

# Configuración desde variables de entorno
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COINMARKETCAP_API_KEY = os.getenv("COINMARKETCAP_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")

# Inicializar servicios
app = Flask(__name__)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

criptos = ["BTC", "ADA", "SHIBA", "SOL"]

def obtener_datos(cripto):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": COINMARKETCAP_API_KEY}
    params = {"symbol": cripto, "convert": "EUR"}

    r = requests.get(url, headers=headers, params=params)
    data = r.json()
    
    try:
        precio = round(data["data"][cripto]["quote"]["EUR"]["price"], 5)
        rsi = calcular_rsi(precio)
        return precio, rsi
    except Exception as e:
        print(f"Error al obtener datos de {cripto}: {e}")
        return None, None

def calcular_rsi(precio_actual):
    return round(50 + (precio_actual % 10), 2)

def guardar_precio_en_supabase(nombre, precio, rsi):
    ahora = datetime.utcnow().isoformat()
    supabase.table("precios").insert({
        "nombre": nombre,
        "precio": precio,
        "rsi": rsi,
        "fecha": ahora
    }).execute()

def obtener_ultima_fecha_envio():
    res = supabase.table("precios").select("*").eq("nombre", "CONTROL_ENVIO").order("fecha", desc=True).limit(1).execute()
    if res.data:
        return datetime.fromisoformat(res.data[0]['fecha'])
    return None

def registrar_envio():
    supabase.table("precios").insert({
        "nombre": "CONTROL_ENVIO",
        "precio": 0,
        "rsi": 0,
        "fecha": datetime.utcnow().isoformat()
    }).execute()

def enviar_mensaje_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    requests.post(url, data=data)

def construir_mensaje():
    mensaje = "🪙 *Resumen de Criptomonedas*\n\n"
    for cripto in criptos:
        precio, rsi = obtener_datos(cripto)
        if precio is not None:
            guardar_precio_en_supabase(cripto, precio, rsi)

            consejo = ""
            if rsi > 70:
                consejo = "🚨 *TE ACONSEJO QUE VENDAS*"
            elif rsi < 30:
                consejo = "🟢 *TE ACONSEJO QUE COMPRES*"
            else:
                consejo = "🤔 *ESPERA, sin señales claras*"

            mensaje += f"*{cripto}*\nPrecio: {precio:.5f} €\nRSI: {rsi}\n{consejo}\n\n"
    return mensaje

@app.route("/resumen")
def mostrar_resumen():
    return "<h1>Resumen Criptos</h1><p>Próximamente más info aquí.</p>"

def es_hora_de_resumen():
    if not ENVIAR_RESUMEN_DIARIO:
        return False
    zona = pytz.timezone("Europe/Madrid")
    ahora = datetime.now(zona)
    hora_actual = ahora.strftime("%H:%M")
    return hora_actual == RESUMEN_HORA

@app.route("/forzar", methods=["GET"])
def forzar_envio():
    mensaje = construir_mensaje()
    enviar_mensaje_telegram(mensaje)
    registrar_envio()
    return "✅ Mensaje forzado enviado"

@app.route("/", methods=["GET"])
def ejecutar_automatico():
    from datetime import timezone
    ahora = datetime.now(timezone.utc)
    ultima = obtener_ultima_fecha_envio()

    if not ultima or ahora - ultima > timedelta(minutes=59):
        mensaje = construir_mensaje()
        enviar_mensaje_telegram(mensaje)
        registrar_envio()
        return "✅ Mensaje automático enviado"
    elif es_hora_de_resumen():
        mensaje = construir_mensaje()
        enviar_mensaje_telegram(mensaje)
        registrar_envio()
        return "✅ Resumen diario enviado"
    else:
        return "⏳ Aún no ha pasado una hora"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
