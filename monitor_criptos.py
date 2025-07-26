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

# ------------------------- CONFIGURACIÓN MEJORADA -------------------------
class Config:
    # Credenciales y configuraciones
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    CMC_API_KEY = os.getenv("CMC_API_KEY")
    
    # Configuración de informes
    ENABLE_DAILY_REPORT = os.getenv("ENVIAR_RESUMEN_DIARIO", "false").lower() == "true"
    REPORT_TIME = os.getenv("RESUMEN_HORA", "09:30")
    TIMEZONE = timezone("Europe/Madrid")
    
    # Criptomonedas a monitorear
    CRYPTOS = ['BTC', 'ETH', 'ADA', 'SHIB', 'SOL']
    
    # Configuración de histórico
    HISTORY_DAYS = 2  # Reducido para pruebas, aumentar a 7-14 en producción
    HISTORY_FILE = "/tmp/precios_historico.json"
    
    # Parámetros de análisis técnico
    RSI_PERIOD = 14
    MA_PERIOD = 24  # Horas para media móvil
    MIN_DATA_FOR_ACCURATE_ANALYSIS = 24  # Horas mínimas para análisis preciso

# ------------------------- MANEJO DE DATOS OPTIMIZADO -------------------------
class CryptoDataManager:
    def __init__(self):
        self.price_history = defaultdict(list)
        self.current_prices = {}
        self.load_history()

    def load_history(self):
        """Carga el historial desde el archivo JSON"""
        try:
            if os.path.exists(Config.HISTORY_FILE):
                with open(Config.HISTORY_FILE, 'r') as f:
                    loaded_data = json.load(f)
                    for crypto in Config.CRYPTOS:
                        self.price_history[crypto] = loaded_data.get(crypto, [])
            print("[INFO] Historial de precios cargado")
        except Exception as e:
            print(f"[ERROR] Error cargando historial: {str(e)}")

    def save_history(self):
        """Guarda el historial en el archivo JSON"""
        try:
            with open(Config.HISTORY_FILE, 'w') as f:
                json.dump(self.price_history, f)
        except Exception as e:
            print(f"[ERROR] Error guardando historial: {str(e)}")

    def fetch_current_prices(self) -> bool:
        """Obtiene los precios actuales desde CoinMarketCap"""
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        headers = {"X-CMC_PRO_API_KEY": Config.CMC_API_KEY}
        params = {"symbol": ",".join(Config.CRYPTOS), "convert": "EUR"}
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            timestamp = datetime.datetime.now(Config.TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
            
            for crypto in Config.CRYPTOS:
                price = float(data["data"][crypto]["quote"]["EUR"]["price"])
                
                # Actualizar datos
                self.price_history[crypto].append({
                    "timestamp": timestamp,
                    "price": price
                })
                self.current_prices[crypto] = price
                
                # Limitar el historial al período configurado
                max_entries = Config.HISTORY_DAYS * 24
                if len(self.price_history[crypto]) > max_entries:
                    self.price_history[crypto] = self.price_history[crypto][-max_entries:]
            
            self.save_history()
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Error de conexión: {str(e)}")
            return False
        except (KeyError, ValueError) as e:
            print(f"[ERROR] Error procesando datos: {str(e)}")
            return False

# ------------------------- ANÁLISIS TÉCNICO MEJORADO -------------------------
class CryptoAnalyzer:
    @staticmethod
    def calculate_price_change(current: float, previous: float) -> Tuple[float, str]:
        """Calcula el cambio porcentual y devuelve emoji representativo"""
        if previous == 0:
            return 0.0, "➖"
        
        change = ((current - previous) / previous) * 100
        abs_change = abs(change)
        
        if abs_change < 2:
            return change, "➖"
        elif abs_change < 5:
            return change, "📈" if change > 0 else "📉"
        elif abs_change < 10:
            return change, "🚀" if change > 0 else "⚠️"
        else:
            return change, "🚀🔥" if change > 0 else "⚠️📉"

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> Tuple[str, str]:
        """Calcula el RSI con valores iniciales inteligentes"""
        if len(prices) < period + 1:
            # Valores iniciales basados en comportamiento histórico de cada cripto
            initial_rsi = {
                'BTC': (52, "🟡 Moderado"),
                'ETH': (50, "🟢 Neutral"),
                'ADA': (48, "🟠 Volátil"),
                'SHIB': (55, "🟡 Especulativo"),
                'SOL': (58, "🔵 Fuerte")
            }
            crypto = "GLOBAL"  # Default si no se encuentra
            rsi, status = initial_rsi.get(crypto, (50, "⚪ Calculando"))
            return f"{rsi}*", status  # Asterisco indica valor estimado
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
            else:
                losses.append(abs(change))
        
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0.0001  # Evitar división por cero
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        # Determinar estado del mercado
        if rsi < 30:
            status = "🔴 COMPRAR (sobrevendido)"
        elif rsi > 70:
            status = "🟢 VENDER (sobrecomprado)"
        elif rsi > 65:
            status = "🟡 RSI Alto"
        elif rsi < 35:
            status = "🟠 RSI Bajo"
        else:
            status = "⚪ Neutral"
        
        return f"{rsi:.1f}", status

# ------------------------- GENERADOR DE INFORMES MEJORADO -------------------------
class ReportGenerator:
    @staticmethod
    def format_price(price: float) -> str:
        """Formatea el precio para mejor legibilidad"""
        if price >= 1:
            return f"{price:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        else:
            return f"{price:.6f} €".replace(".", ",")

    @staticmethod
    def generate_crypto_report(crypto: str, data: CryptoDataManager) -> str:
        """Genera el reporte individual para cada criptomoneda"""
        current_price = data.current_prices.get(crypto)
        price_history = [p["price"] for p in data.price_history.get(crypto, [])]
        
        # Análisis técnico
        rsi_value, rsi_status = CryptoAnalyzer.calculate_rsi(price_history)
        
        # Variación de precio
        change_info = ""
        if len(price_history) >= 2:
            change_percent, change_emoji = CryptoAnalyzer.calculate_price_change(
                current_price if current_price else 0,
                price_history[-2]["price"] if len(price_history) >= 2 else 0
            )
            change_info = f"{change_emoji} {abs(change_percent):.1f}% (24h)" if abs(change_percent) >= 2 else ""
        
        return (
            f"💰 *{crypto}*: {ReportGenerator.format_price(current_price) if current_price else 'N/A'}\n"
            f"📊 RSI: {rsi_value} | {rsi_status}\n"
            f"{change_info if change_info else '➡️ Estable'}\n"
        )

    @staticmethod
    def generate_full_report(data: CryptoDataManager) -> str:
        """Genera el reporte completo para todas las criptomonedas"""
        if not data.fetch_current_prices():
            return "⚠️ Error actualizando precios. Intentando nuevamente..."
        
        report = "📈 *Informe Criptomonedas* 📈\n\n"
        for crypto in Config.CRYPTOS:
            report += ReportGenerator.generate_crypto_report(crypto, data)
        
        # Pie de informe
        data_points = min(len(data.price_history.get(c, [])) for c in Config.CRYPTOS)
        report += (
            f"\n📊 *Estadísticas*\n"
            f"• Datos acumulados: {data_points}/{Config.HISTORY_DAYS*24}h\n"
            f"• Actualizado: {datetime.datetime.now(Config.TIMEZONE).strftime('%d/%m %H:%M')}\n"
            f"• Valores con * son estimados"
        )
        
        return report

# ------------------------- INTEGRACIÓN CON TELEGRAM -------------------------
class TelegramIntegration:
    @staticmethod
    def send_report(report: str):
        """Envía el informe a Telegram"""
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": Config.TELEGRAM_CHAT_ID,
            "text": report,
            "parse_mode": "Markdown"
        }
        try:
            response = requests.post(url, json=payload, timeout=15)
            response.raise_for_status()
            print("[INFO] Informe enviado a Telegram")
        except Exception as e:
            print(f"[ERROR] Error enviando a Telegram: {str(e)}")

# ------------------------- MONITOREO AUTOMÁTICO -------------------------
def start_monitoring(data_manager: CryptoDataManager):
    """Inicia el monitoreo automático"""
    print("[INFO] Sistema de monitoreo iniciado")
    
    while True:
        now = datetime.datetime.now(Config.TIMEZONE)
        
        # Reporte diario automático
        if Config.ENABLE_DAILY_REPORT and now.strftime("%H:%M") == Config.REPORT_TIME:
            report = ReportGenerator.generate_full_report(data_manager)
            TelegramIntegration.send_report(report)
            time.sleep(61)  # Evitar duplicados
        
        # Actualización periódica de datos
        time.sleep(30)

# ------------------------- ENDPOINTS FLASK -------------------------
data_manager = CryptoDataManager()

@app.route("/")
def status():
    return "🟢 Bot de Criptomonedas Operativo"

@app.route("/informe")
def generate_report():
    """Endpoint para generar informe manual"""
    try:
        report = ReportGenerator.generate_full_report(data_manager)
        TelegramIntegration.send_report(f"🔔 *Informe Manual*\n\n{report}")
        return "Informe generado y enviado"
    except Exception as e:
        return f"Error generando informe: {str(e)}"

# ------------------------- INICIALIZACIÓN -------------------------
if __name__ == '__main__':
    # Iniciar monitoreo automático en segundo plano
    if Config.ENABLE_DAILY_REPORT:
        monitor_thread = threading.Thread(
            target=start_monitoring,
            args=(data_manager,),
            daemon=True
        )
        monitor_thread.start()
    
    # Configurar guardado automático al cerrar
    atexit.register(data_manager.save_history)
    
    # Iniciar aplicación Flask
    app.run()
