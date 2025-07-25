import os
import requests
import time
import datetime
import pytz
from telegram import Bot

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "22:30")

MONEDAS = ["bitcoin", "cardano", "solana", "shiba-inu"]
NOMBRES = {"bitcoin": "BTC", "cardano": "ADA", "solana": "SOL", "shiba-inu": "SHIBA"}
API_URL = "https://api.coingecko.com/api/v3/simple/price?ids={}&vs_currencies=eur"

INTERVALO_MINUTOS = 10
VARIACION_ALERTA = 2.0  # %

bot = Bot(token=TOKEN)
precios_anteriores = {}

def obtener_precios():
    ids = ",".join(MONEDAS)
    url = API_URL.format(ids)
    r = requests.get(url)
    return r.json()

def enviar_mensaje(texto):
    try:
        bot.send_message(chat_id=CHAT_ID, text=texto)
    except Exception as e:
        print("Error enviando mensaje:", e)

def es_hora_de_resumen():
    ahora = datetime.datetime.now(pytz.timezone("Europe/Madrid"))  # o Europe/Amsterdam
    hora_actual = ahora.strftime("%H:%M")
    return RESUMEN_DIARIO and hora_actual == RESUMEN_HORA

def generar_resumen(precios):
    ahora = datetime.datetime.now(pytz.timezone("Europe/Madrid")).strftime("%d-%m %H:%M")
    resumen = f"📊 *Resumen diario* ({ahora}):\n"
    for k, v in precios.items():
        simbolo = NOMBRES.get(k, k.upper())
        resumen += f"- {simbolo}: {v['eur']} €\n"
    return resumen

def detectar_cambios(precios):
    for k, v in precios.items():
        actual = v["eur"]
        anterior = precios_anteriores.get(k)
        if anterior:
            variacion = ((actual - anterior) / anterior) * 100
            if abs(variacion) >= VARIACION_ALERTA:
                direccion = "⬆️ subió" if variacion > 0 else "⬇️ bajó"
                mensaje = f"{NOMBRES[k]} {direccion} {variacion:.2f}% → {actual} €"
                enviar_mensaje(mensaje)
        precios_anteriores[k] = actual

if __name__ == "__main__":
    while True:
        try:
            precios = obtener_precios()
            detectar_cambios(precios)
            if es_hora_de_resumen():
                resumen = generar_resumen(precios)
                enviar_mensaje(resumen)
        except Exception as e:
            print("Error en ejecución:", e)
        time.sleep(INTERVALO_MINUTOS * 60)
