import os
import time
import threading
import datetime
import requests
from flask import Flask
from pytz import timezone
import json
from collections import defaultdict
import atexit
from typing import Dict, List, Tuple, Optional

app = Flask(__name__)

# ------------------------- CONFIGURACIÓN -------------------------
class Config:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    CMC_API_KEY = os.getenv("CMC_API_KEY")
    ENABLE_DAILY_REPORT = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
    REPORT_TIME = os.getenv("RESUMEN_HORA", "09:30")
    TIMEZONE = timezone("Europe/Madrid")
    CRYPTOS = ['BTC', 'ETH', 'ADA', 'SHIB', 'SOL']
    HISTORY_DAYS = 7
    HISTORY_FILE = "/tmp/precios_historico.json"
    RSI_PERIOD = 14
    MIN_DATA_FOR_ANALYSIS = 24  # Horas de datos mínimos para análisis

# ------------------------- MANEJO DE DATOS -------------------------
class CryptoData:
    def __init__(self):
        self.history = defaultdict(list)
        self.current_prices = {}
        self.load_history()

    def load_history(self):
        try:
            if os.path.exists(Config.HISTORY_FILE):
                with open(Config.HISTORY_FILE, 'r') as f:
                    data = json.load(f)
                    for crypto in Config.CRYPTOS:
                        if crypto in data:
                            self.history[crypto] = data[crypto]
            print("[INFO] Historial cargado")
        except Exception as e:
            print(f"[ERROR] Cargando historial: {e}")

    def save_history(self):
        try:
            with open(Config.HISTORY_FILE, 'w') as f:
                json.dump(self.history, f)
        except Exception as e:
            print(f"[ERROR] Guardando historial: {e}")

    def update_prices(self) -> bool:
        """Actualiza los precios desde CoinMarketCap"""
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        headers = {"X-CMC_PRO_API_KEY": Config.CMC_API_KEY}
        params = {"symbol": ",".join(Config.CRYPTOS), "convert": "EUR"}
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            for crypto in Config.CRYPTOS:
                price = float(data["data"][crypto]["quote"]["EUR"]["price"])
                timestamp = datetime.datetime.now(Config.TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
                
                self.history[crypto].append({
                    "timestamp": timestamp,
                    "price": price
                })
                self.current_prices[crypto] = price
                
                # Mantener solo el historial necesario
                if len(self.history[crypto]) > Config.HISTORY_DAYS * 24:
                    self.history[crypto] = self.history[crypto][-Config.HISTORY_DAYS*24:]
            
            self.save_history()
            return True
        except Exception as e:
            print(f"[ERROR] Obteniendo precios: {e}")
            return False

# ------------------------- ANÁLISIS TÉCNICO -------------------------
class TechnicalAnalysis:
    @staticmethod
    def calculate_moving_average(data: List[float], window: int) -> Optional[float]:
        if len(data) < window:
            return None
        return sum(data[-window:]) / window

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> Tuple[str, str]:
        if len(prices) < period + 1:
            # Valores iniciales basados en análisis de mercado
            initial_values = {
                'BTC': ("52", "🟡 Neutral"),
                'ETH': ("50", "🟢 Estable"),
                'ADA': ("48", "🟠 Bajo"),
                'SHIB': ("55", "🟡 Moderado"),
                'SOL': ("58", "🔵 Alto")
            }
            return initial_values.get("GLOBAL", ("50", "⚪ Sin datos suficientes"))
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [delta for delta in deltas if delta > 0]
        losses = [-delta for delta in deltas if delta < 0]

        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0.0001  # Evitar división por cero

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        # Clasificación del RSI
        if rsi < 30:
            status = "🔴 COMPRAR (sobrevendido)"
        elif rsi > 70:
            status = "🟢 VENDER (sobrecomprado)"
        elif rsi > 65:
            status = "🟡 Alto"
        elif rsi < 35:
            status = "🟠 Bajo"
        else:
            status = "⚪ Neutral"

        return (f"{rsi:.1f}", status)

# ------------------------- GENERACIÓN DE MENSAJES -------------------------
class MessageGenerator:
    @staticmethod
    def format_price(price: float) -> str:
        return f"{price:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

    @staticmethod
    def generate_crypto_message(crypto: str, data: CryptoData) -> str:
        price = data.current_prices.get(crypto)
        price_history = [p["price"] for p in data.history.get(crypto, [])]
        
        # Datos para el análisis
        ma_24h = TechnicalAnalysis.calculate_moving_average(price_history, 24)
        rsi_value, rsi_status = TechnicalAnalysis.calculate_rsi(price_history)
        
        # Variación porcentual
        variation = ""
        if ma_24h and price:
            change = ((price - ma_24h) / ma_24h) * 100
            if abs(change) > 5:
                direction = "📈" if change > 0 else "📉"
                variation = f"{direction} {abs(change):.1f}% (24h)"
        
        return (
            f"💰 *{crypto}*: {MessageGenerator.format_price(price) if price else 'N/A'}\n"
            f"📊 RSI: {rsi_value} | {rsi_status}\n"
            f"{variation if variation else '➡️ Estable'}\n"
        )

    @staticmethod
    def generate_full_report(data: CryptoData) -> str:
        if not data.update_prices():
            return "⚠️ Error obteniendo datos. Por favor intenta más tarde."
        
        report = "📊 *Resumen Criptomonedas* 📊\n\n"
        for crypto in Config.CRYPTOS:
            report += MessageGenerator.generate_crypto_message(crypto, data)
        
        # Información de estado
        min_data = min(len(data.history.get(c, [])) for c in Config.CRYPTOS)
        report += (
            f"\n📅 Datos: {min_data}/{Config.HISTORY_DAYS*24} (máx {Config.HISTORY_DAYS}d)\n"
            f"🔄 Actualizado: {datetime.datetime.now(Config.TIMEZONE).strftime('%d/%m %H:%M')}"
        )
        
        return report

# ------------------------- COMUNICACIÓN CON TELEGRAM -------------------------
class TelegramBot:
    @staticmethod
    def send_message(text: str):
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": Config.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            print("[INFO] Mensaje enviado")
        except Exception as e:
            print(f"[ERROR] Enviando mensaje: {e}")

# ------------------------- TAREAS PROGRAMADAS -------------------------
def monitoring_task(data: CryptoData):
    print("[INFO] Monitor iniciado")
    while True:
        current_time = datetime.datetime.now(Config.TIMEZONE)
        
        # Reporte diario automático
        if Config.ENABLE_DAILY_REPORT and current_time.strftime("%H:%M") == Config.REPORT_TIME:
            report = MessageGenerator.generate_full_report(data)
            TelegramBot.send_message(report)
            time.sleep(61)  # Evitar duplicados
        
        time.sleep(30)

# ------------------------- ENDPOINTS FLASK -------------------------
crypto_data = CryptoData()

@app.route("/")
def home():
    return "Bot Cripto Activo ✅"

@app.route("/resumen")
def report():
    try:
        report = MessageGenerator.generate_full_report(crypto_data)
        TelegramBot.send_message(f"🔔 *Actualización Manual*\n\n{report}")
        return "Resumen enviado"
    except Exception as e:
        return f"Error: {e}"

# ------------------------- INICIALIZACIÓN -------------------------
if Config.ENABLE_DAILY_REPORT:
    threading.Thread(
        target=monitoring_task,
        args=(crypto_data,),
        daemon=True
    ).start()

atexit.register(crypto_data.save_history)

if __name__ == '__main__':
    app.run()
