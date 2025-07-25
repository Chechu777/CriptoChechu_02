import os
import asyncio
import time
import requests
import pandas as pd
from flask import Flask
from telegram import Bot

# --- Configuración desde variables de entorno ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RESUMEN_HORA = os.getenv("RESUMEN_HORA", "22:10")
ENVIAR_RESUMEN_DIARIO = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"

CRYPTO_IDS = ["bitcoin", "cardano", "solana", "shiba-inu"]
SYMBOL_MAP = {
    "bitcoin": "BTC",
    "cardano": "ADA",
    "solana": "SOL",
    "shiba-inu": "SHIB"
}

API_PRECIO = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(CRYPTO_IDS)}&vs_currencies=eur"
API_HISTORICO = "https://api.coingecko.com/api/v3/coins/{id}/market_chart?vs_currency=eur&days=2&interval=hourly"

if not TOKEN or not CHAT_ID:
    raise Exception("Faltan variables de entorno TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")

bot = Bot(token=TOKEN)
precios_anteriores = {}

# --- Flask App (para que Render vea vida) ---
app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Bot Cripto activo y corriendo."

# --- Funciones de utilidad ---
def obtener_precios_actuales():
    try:
        resp = requests.get(API_PRECIO)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print("⚠️ Error obteniendo precios:", e)
        return {}

def calcular_rsi(prices, period=14):
    df = pd.DataFrame(prices, columns=["price"])
    delta = df["price"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2) if not rsi.empty and not pd.isna(rsi.iloc[-1]) else None

def obtener_rsi(crypto_id):
    try:
        url = API_HISTORICO.format(id=crypto_id)
        resp = requests.get(url)
        resp.raise_for_status()
        prices = [x[1] for x in resp.json().get("prices", [])]
        return calcular_rsi(prices)
    except Exception as e:
        print(f"⚠️ Error al calcular RSI de {crypto_id}:", e)
        return None

def detectar_cambios(precios_actuales):
    mensajes = []
    for cripto, data in precios_actuales.items():
        actual = data["eur"]
        anterior = precios_anteriores.get(cripto)

        if anterior:
            cambio = ((actual - anterior) / anterior) * 100
            if abs(cambio) >= 3:
                emoji = "📈" if cambio > 0 else "📉"
                mensajes.append(f"{emoji} *{SYMBOL_MAP[cripto]}*: {actual:.2f} EUR ({cambio:+.2f}%)")

        precios_anteriores[cripto] = actual
    return mensajes

# --- Tareas Asíncronas ---
async def monitorear_cambios():
    while True:
        precios = obtener_precios_actuales()
        cambios = detectar_cambios(precios)
        for mensaje in cambios:
            await bot.send_message(chat_id=CHAT_ID, text=mensaje, parse_mode="Markdown")
        await asyncio.sleep(300)

async def enviar_resumen_diario():
    while True:
        if not ENVIAR_RESUMEN_DIARIO:
            await asyncio.sleep(60)
            continue

        ahora = time.strftime("%H:%M")
        if ahora == RESUMEN_HORA:
            precios = obtener_precios_actuales()
            if precios:
                resumen = "*📊 Resumen Diario de Criptos:*\n\n"
                for cripto, data in precios.items():
                    simbolo = SYMBOL_MAP[cripto]
                    precio = data["eur"]
                    rsi = obtener_rsi(cripto)
                    resumen += f"• *{simbolo}*: {precio:.2f} EUR | RSI: {rsi if rsi is not None else 'N/A'}\n"

                await bot.send_message(chat_id=CHAT_ID, text=resumen, parse_mode="Markdown")
                await asyncio.sleep(60)
        await asyncio.sleep(30)

# --- Main asíncrono ---
async def main():
    tareas = [monitorear_cambios()]
    if ENVIAR_RESUMEN_DIARIO:
        tareas.append(enviar_resumen_diario())
    await asyncio.gather(*tareas)

# --- Lanzar Flask + Bot ---
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    app.run(host="0.0.0.0", port=10000)
