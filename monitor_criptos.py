import threading, asyncio, requests, os
import pandas as pd, numpy as np
from datetime import datetime
from telegram import Bot
from flask import Flask

# ⚙️ CONFIG
symbols = ['BTCUSDT', 'ADAUSDT', 'SOLUSDT', 'SHIBUSDT']
threshold = 3.0
rsi_period = 14

# 🔐 TELEGRAM
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
bot = Bot(token=TOKEN)

# 🕒 RESUMEN DIARIO
ENVIAR_RESUMEN = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
HORA_RESUMEN = os.getenv("RESUMEN_HORA", "21:16")
resumen_enviado_hoy = None  # Controla que solo se envíe una vez al día

# 🌍 FLASK APP PARA RENDER
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Cripto Bot corriendo"

@app.route('/status')
def status():
    return f"🕒 Última ejecución: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

# 📊 Binance
def get_klines(symbol, interval='1m', limit=100):
    try:
        url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'trades',
            'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
        ])
        df['close'] = df['close'].astype(float)
        return df[['close']]
    except Exception as e:
        print(f"⚠️ Error al obtener datos de {symbol}: {e}")
        return None

def calc_rsi(prices, period=14):
    if len(prices) < period:
        return np.nan
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

async def analizar(symbol):
    df = get_klines(symbol)
    if df is None or len(df) < rsi_period + 1:
        print(f"⛔ Datos insuficientes para {symbol}")
        return

    last = df['close'].iloc
