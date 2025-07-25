import requests, pandas as pd, numpy as np, time
from datetime import datetime
from telegram import Bot

# ⚙️ CONFIGURACIÓN
symbols = ['BTCUSDT', 'ADAUSDT', 'SOLUSDT', 'SHIBUSDT']
threshold = 3.0  # % cambio significativo
rsi_period = 14

# 🔐 TELEGRAM
TOKEN = '8382852811:AAG1v_mbYRNaOIU4vJxC1PywM8qSW1p3w88'
CHAT_ID = '6232492493'  # reemplaza con tu número real
bot = Bot(token=TOKEN)

# 📊 Obtener datos históricos de Binance
def get_klines(symbol, interval='1m', limit=100):
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
    data = requests.get(url).json()
    df = pd.DataFrame(data, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'trades',
        'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
    ])
    df['close'] = df['close'].astype(float)
    return df[['close']]

# 📈 Calcular RSI
def calc_rsi(prices, period=14):
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# 🔍 Analizar moneda
def analizar(symbol):
    df = get_klines(symbol)
    last = df['close'].iloc[-1]
    prev = df['close'].iloc[-2]
    rsi = calc_rsi(df['close'], rsi_period).iloc[-1]
    change = ((last - prev) / prev) * 100

    mensaje = f"💰 {symbol} | Precio: {last:.4f} USD\nCambio: {change:.2f}% | RSI: {rsi:.2f}"

    if abs(change) >= threshold:
        if rsi < 30:
            mensaje += "\n✅ SUGERENCIA: COMPRAR (RSI bajo)"
        elif rsi > 70:
            mensaje += "\n🔴 SUGERENCIA: VENDER (RSI alto)"
        else:
            mensaje += "\n🟡 OBSERVAR: Movimiento sin señal clara"
        print(mensaje)
        bot.send_message(chat_id=CHAT_ID, text=mensaje)

# ♻️ Bucle principal (cada minuto)
while True:
    try:
        for moneda in symbols:
            analizar(moneda)
        time.sleep(60)
    except Exception as e:
        print("❌ ERROR:", e)
        time.sleep(60)
