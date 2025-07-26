import os
import requests
from datetime import datetime
from flask import Flask

app = Flask(__name__)

# Variables de entorno necesarias
CMC_API_KEY = os.getenv("CMC_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower()
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "09:30")

CRIPTOS = ["BTC", "SHIBA-INU", "ADA", "SOL"]

def obtener_datos_criptos():
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    parametros = {
        "symbol": ",".join([c.replace("SHIBA-INU", "SHIB") for c in CRIPTOS]),
        "convert": "EUR"
    }
    respuesta = requests.get(url, headers=headers, params=parametros)
    datos = respuesta.json()["data"]
    resultados = {}

    for cripto in CRIPTOS:
        simbolo = cripto.replace("SHIBA-INU", "SHIB")
        precio = datos[simbolo]["quote"]["EUR"]["price"]
        rsi = calcular_rsi_simulado(precio)
        resultados[cripto] = {
            "precio": precio,
            "rsi": rsi
        }

    return resultados

def calcular_rsi_simulado(precio):
    # Simulación aleatoria de RSI solo para ejemplo
    import random
    return round(random.uniform(20, 80), 1)

def interpretar_rsi(rsi):
    if rsi < 30:
        return "💸 (RSI bajo)", "Te aconsejo que compres"
    elif rsi > 70:
        return "📈 (RSI alto)", "Te aconsejo que vendas"
    else:
        return "😐 (RSI normal)", "Te aconsejo que te estés quieto por ahora"

def formatear_precio(precio):
    if precio >= 1:
        return f"{precio:,.2f}€"
    elif precio >= 0.01:
        return f"{precio:,.4f}€"
    else:
        return f"{precio:,.8f}€"

def crear_mensaje(datos):
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    mensaje = f"📊 *Resumen Diario de Criptos* ({ahora})\n\n"

    for cripto, info in datos.items():
        precio = formatear_precio(info['precio'])
        rsi = info['rsi']
        estado, consejo = interpretar_rsi(rsi)
        mensaje += f"*{cripto}*: {precio}\nRSI: {rsi} → {estado}\n_{consejo}_\n\n"

    return mensaje

def enviar_telegram(texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown"
    }
    requests.post(url, data=payload)

@app.route('/resumen')
def resumen_diario():
    ahora = datetime.now().strftime("%H:%M")
    if ENVIAR_RESUMEN_DIARIO == "true" and ahora == RESUMEN_HORA:
        datos = obtener_datos_criptos()
        mensaje = crear_mensaje(datos)
        enviar_telegram(mensaje)
        return "Resumen diario enviado ✅"
    else:
        return f"No es la hora del resumen ({ahora} ≠ {RESUMEN_HORA}) ⏰"

@app.route('/')
def inicio():
    return "Bot de criptos funcionando ✅"

if __name__ == '__main__':
    app.run()
