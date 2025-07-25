import requests, pandas as pd, numpy as np, time
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode  # Opcional
from telegram.ext import Application

application = Application.builder().token(TOKEN).build()
await application.bot.send_message(chat_id=CHAT_ID, text="Bot iniciado")  # Usa async

# ⚙️ CONFIGURACIÓN
symbols = ['BTCUSDT', 'ADAUSDT', 'SOLUSDT', 'SHIBUSDT']
threshold = 3.0  # % cambio significativo
rsi_period = 14

# 🔐 TELEGRAM
TOKEN = '8382852811:AAG1v_mbYRNaOIU4vJxC1PywM8qSW1p3w88'  # <-- cambia este token urgente
CHAT_ID = '6232492493'
bot = Bot(token=TOKEN)

# 📊 Obtener datos históricos de Binance
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

# 📈 Calcular RSI
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

# 🔍 Analizar moneda
def analizar(symbol):
    df = get_klines(symbol)
    if df is None or len(df) < rsi_period + 1:
        print(f"⛔ Datos insuficientes para {symbol}")
        return

    last = df['close'].iloc[-1]
    prev = df['close'].iloc[-2]
    rsi_value = calc_rsi(df['close'], rsi_period).iloc[-1]

    if np.isnan(rsi_value):
        print(f"⚠️ RSI no disponible para {symbol}")
        return

    change = ((last - prev) / prev) * 100
    mensaje = f"💰 {symbol} | Precio: {last:.4f} USD\nCambio: {change:.2f}% | RSI: {rsi_value:.2f}"

    if abs(change) >= threshold:
        if rsi_value < 30:
            mensaje += "\n✅ SUGERENCIA: COMPRAR (RSI bajo)"
        elif rsi_value > 70:
            mensaje += "\n🔴 SUGERENCIA: VENDER (RSI alto)"
        else:
            mensaje += "\n🟡 OBSERVAR: Movimiento sin señal clara"

        print(mensaje)
        try:
            bot.send_message(chat_id=CHAT_ID, text=mensaje)
        except Exception as e:
            print(f"⚠️ Error al enviar mensaje de {symbol}: {e}")

# ♻️ Bucle principal (cada minuto)
while True:
    try:
        print(f"⏰ Ejecutando análisis: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        for moneda in symbols:
            analizar(moneda)
            time.sleep(1)  # Evitar rate limiting en Binance
        time.sleep(60)
    except Exception as e:
        print("❌ ERROR GENERAL:", e)
        time.sleep(60)
