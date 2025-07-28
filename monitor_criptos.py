import os
import requests
from flask import Flask
from datetime import datetime
from supabase import create_client, Client
from zoneinfo import ZoneInfo
import pytz

# Configuración
app = Flask(__name__)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

MONEDAS = ["BTC", "ETH", "ADA", "SHIB", "SOL"]

# Funciones auxiliares
def obtener_precios():
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    params = {"symbol": ",".join(MONEDAS), "convert": "EUR"}
    r = requests.get(url, headers=headers, params=params)
    data = r.json()["data"]
    precios = {}
    for m in MONEDAS:
        raw = data[m]["quote"]["EUR"]["price"]
        precio = round(raw, 8)  # Guardar hasta 8 decimales
        precios[m] = precio
    return precios

def obtener_rsi(moneda):
    # Mock RSI entre 30 y 70
    import random
    return round(random.uniform(30, 70), 2)

def consejo_rsi(rsi):
    if rsi > 70:
        return "🔴 RSI alto, quizá vender\n⚠️ Podría haber una bajada en el precio."
    elif rsi < 30:
        return "🟢 RSI bajo, quizá comprar\n📈 Podría rebotar pronto al alza."
    else:
        return "🟡 Quieto chato, no hagas huevadas"

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
    requests.post(url, data=data)

def insertar_en_supabase(nombre, precio, rsi, fecha):
    try:
        # Asegurar que está en la zona horaria correcta
        hora_madrid = fecha.astimezone(ZoneInfo("Europe/Madrid")) if fecha.tzinfo else fecha.replace(tzinfo=ZoneInfo("Europe/Madrid"))
        
        # Formatear para Supabase
        fecha_formateada = hora_madrid.strftime('%Y-%m-%d %H:%M:%S.%f')
        
        response = supabase.table("precios").insert({
            "nombre": nombre,
            "precio": precio,
            "rsi": rsi,
            "fecha": fecha_formateada
        }).execute()
        
        if hasattr(response, 'error') and response.error:
            print(f"Error insertando en Supabase: {response.error}")
    except Exception as e:
        print(f"Excepción al insertar en Supabase: {str(e)}")
        raise

# Y en generar_y_enviar_resumen, modifica la obtención de la hora:
def generar_y_enviar_resumen():
    precios = obtener_precios()
    ahora = datetime.now(ZoneInfo("Europe/Madrid"))  # Esto ya está correcto
    resumen = "<b>📊 Resumen Manual de Criptomonedas</b>\n"

    for m in MONEDAS:
        precio = precios[m]
        rsi = obtener_rsi(m)
        insertar_en_supabase(m, precio, rsi, ahora)  # Pasamos la hora con zona horaria
        consejo = consejo_rsi(rsi)
        resumen += f"\n<b>{m}</b>: {precio:,.8f} €\nRSI: {rsi} → {consejo}\n"

    resumen += f"\n🗱️ Actualizado: {ahora.strftime('%d/%m %H:%M')} (Hora Europa)"
    enviar_telegram(resumen)

# Rutas
@app.route("/")
def home():
    return "OK"

@app.route("/resumen")
def resumen():
    generar_y_enviar_resumen()
    return "<h1>Resumen enviado a Telegram 📢</h1><p>También guardado en Supabase.</p>"

# Ejecutar
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
