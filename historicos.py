import pandas as pd, ccxt, os, io, requests, dotenv, numpy as np, time, json, logging, matplotlib.pyplot as plt
from datetime import datetime, timedelta, timezone

# ============================
# 🔹 Configuración inicial
dotenv.load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

MAX_REGISTROS_POR_LOTE = 25   # 🔹 Inserción por lotes

logger = logging.getLogger("historicos")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(levelname)s - %(message)s")

# ============================
# 🔹 Mapeo de símbolos Binance
SYMBOL_MAP = {
    "BTC": "BTC/USDT",
    "ETH": "ETH/USDT",
    "ADA": "ADA/USDT",
    "SHIB": "1000SHIB/USDT",
    "SOL": "SOL/USDT",
}

# Mapas de símbolos Kraken (evita load_markets pesado)
KRAKEN_SYMBOLS = {
    "BTC": "BTC/EUR",
    "ETH": "ETH/EUR",
    "ADA": "ADA/EUR",
    "SHIB": "SHIB/EUR",
    "SOL": "SOL/EUR",
}

# ============================
def generar_grafico(moneda: str, dias: int = 30):
    """Genera gráfico de precios, RSI y MACD de los últimos X días"""
    df = cargar_horas_30d(moneda)
    if df.empty:
        return None

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    fig.suptitle(f"{moneda} - Últimos {dias} días", fontsize=14)

    ax1.plot(df["time_open"], df["close"], label="Cierre", color="blue")
    ax1.set_ylabel("Precio (€)")
    ax1.legend()

    ax2.plot(df["time_open"], df["rsi"], label="RSI", color="orange")
    ax2.axhline(30, color="green", linestyle="--")
    ax2.axhline(70, color="red", linestyle="--")
    ax2.set_ylabel("RSI")
    ax2.legend()

    ax3.plot(df["time_open"], df["macd"], label="MACD", color="purple")
    ax3.plot(df["time_open"], df["macd_signal"], label="Señal", color="black", linestyle="--")
    ax3.bar(df["time_open"], df["macd_hist"], label="Histograma", color="gray")
    ax3.set_ylabel("MACD")
    ax3.legend()

    plt.xticks(rotation=30)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close(fig)

    return buf
# ============================ # 🔹 Obtener históricos desde CoinGecko
def obtener_historicos_coingecko(moneda, dias, timeframe="1h"):
    """ Usa CoinGecko como último recurso. 
    En Render evitamos time.sleep → si devuelve 429, se retorna vacío directamente. """
    
    id_map = {
        "BTC": "bitcoin", "ETH": "ethereum",
        "ADA": "cardano", "SHIB": "shiba-inu", "SOL": "solana"
    }
    if moneda not in id_map:
        return pd.DataFrame()
    interval = "hourly" if timeframe == "1h" else "daily"
    if timeframe == "1h":
        logger.warning(f"{moneda}: CoinGecko gratis no soporta interval=hourly → usando daily")
        interval = "daily"
    url = (f"https://api.coingecko.com/api/v3/coins/{id_map[moneda]}/market_chart"
           f"?vs_currency=eur&days={dias}&interval={interval}")
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 429:
            logger.warning(f"{moneda}: rate limit en CoinGecko (429) → devolviendo vacío")
            return pd.DataFrame()
        if not r.ok:
            logger.error(f"{moneda}: fallo {r.status_code} en CoinGecko")
            return pd.DataFrame()
    except Exception as e:
        logger.error(f"{moneda}: error de red en CoinGecko → {e}")
        return pd.DataFrame()
    data = r.json()
    if "prices" not in data:
        logger.warning(f"{moneda}: sin 'prices' en respuesta de CoinGecko")
        return pd.DataFrame()
    df = pd.DataFrame({
        "time_open": [pd.to_datetime(p[0], unit="ms", utc=True) for p in data["prices"]],
        "close": [p[1] for p in data["prices"]],
    })
    df["open"] = df["close"]
    df["high"] = df["close"]
    df["low"] = df["close"]
    df["volume"] = [v[1] for v in data.get("total_volumes", [[0, 0]] * len(df))]

    df["time_close"] = df["time_open"] + (pd.to_timedelta("1h") if timeframe == "1h" else pd.to_timedelta("1d"))
    df["nombre"] = moneda
    df["fuente"] = "coingecko"

    return df[["nombre", "time_open", "time_close", "open", "high", "low", "close", "volume", "fuente"]]
# ============================
# 🔹 Indicadores
def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / (avg_loss.replace(0, np.nan))
    return (100 - (100 / (1 + rs))).fillna(50.0)

def _macd(series: pd.Series, fast=12, slow=26, signal=9):
    exp1 = series.ewm(span=fast, adjust=False).mean()
    exp2 = series.ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    return macd, macd_signal, macd - macd_signal

def _add_indicadores(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["rsi"] = _rsi(df["close"], 14)
    macd, macd_sig, macd_hist = _macd(df["close"])
    df["macd"], df["macd_signal"], df["macd_hist"] = macd, macd_sig, macd_hist
    df["tendencia"] = np.where(df["macd"] > df["macd_signal"], "ALZA",
                        np.where(df["macd"] < df["macd_signal"], "BAJA", "PLANA"))
    df["recomendacion"] = np.where(df["rsi"] < 30, "COMPRA",
                            np.where(df["rsi"] > 70, "VENTA", "MANTENER"))
    df["confianza"] = 1.0
    return df

# ============================
# 🔹 Inserción 1h
def insertar_filas(df: pd.DataFrame, tabla: str = "ohlcv_historicos"):
    if df.empty:
        return 0

    df = _add_indicadores(df)

    df["time_open"] = pd.to_datetime(df["time_open"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    df["time_close"] = pd.to_datetime(df["time_close"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    df = df.replace([np.nan, np.inf, -np.inf], None)

    columnas_validas = [
        "nombre", "time_open", "time_close",
        "open", "high", "low", "close", "volume",
        "rsi", "macd", "macd_signal", "macd_hist",
        "tendencia", "recomendacion", "confianza"
    ]
    registros = df[columnas_validas].to_dict(orient="records")

    url = f"{SUPABASE_URL}/rest/v1/{tabla}?on_conflict=nombre,time_open"
    headers = {**HEADERS, "Prefer": "resolution=ignore-duplicates"}

    total_insertados = 0
    for i in range(0, len(registros), MAX_REGISTROS_POR_LOTE):
        lote = registros[i:i+MAX_REGISTROS_POR_LOTE]
        r = requests.post(url, headers=headers, json=lote)
        if not r.ok:
            logger.error(f"Error insertando en {tabla}: {r.text}")
            continue
        total_insertados += len(lote)

    logger.info(f"Insertados {total_insertados} registros nuevos en {tabla} (duplicados ignorados)")
    return total_insertados

# ============================
# 🔹 Inserción 1d
def insertar_filas_dias(df: pd.DataFrame) -> int:
    if df.empty:
        return 0

    df = _add_indicadores(df)

    df["time_open"] = pd.to_datetime(df["time_open"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    df["time_close"] = pd.to_datetime(df["time_close"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    df["confianza"] = 1.0
    df = df.replace([np.nan, np.inf, -np.inf], None)

    columnas_validas = [
        "nombre", "time_open", "time_close",
        "open", "high", "low", "close", "volume",
        "rsi", "macd", "macd_signal", "macd_hist",
        "tendencia", "recomendacion", "confianza"
    ]
    registros = df[columnas_validas].to_dict(orient="records")

    url = f"{SUPABASE_URL}/rest/v1/ohlcv_historicos_dias?on_conflict=nombre,time_open"
    headers = {**HEADERS, "Prefer": "resolution=ignore-duplicates"}

    total_insertados = 0
    for i in range(0, len(registros), MAX_REGISTROS_POR_LOTE):
        lote = registros[i:i+MAX_REGISTROS_POR_LOTE]
        r = requests.post(url, headers=headers, json=lote)
        if not r.ok:
            logger.error(f"Error insertando en ohlcv_historicos_dias: {r.text}")
            continue
        total_insertados += len(lote)

    logger.info(f"Insertados {total_insertados} registros nuevos en ohlcv_historicos_dias (duplicados ignorados)")
    return total_insertados
# ============================ # 
def obtener_historicos_kraken(moneda, dias, timeframe="1h"):
    """
    Descarga OHLCV desde Kraken usando ccxt (rápido y sin load_markets pesado).
    """
    try:
        exchange = ccxt.kraken({
            "enableRateLimit": True,
            "options": {"fetchMarkets": False}
        })
        ahora_utc = datetime.now(timezone.utc)
        desde = exchange.parse8601((ahora_utc - timedelta(days=dias)).strftime('%Y-%m-%dT%H:%M:%S'))

        # Definir symbol manualmente (evitamos exchange.load_markets())
        symbol = KRAKEN_SYMBOLS.get(moneda, f"{moneda}/EUR")

        logger.info(f"[DESCARGA] {moneda} ({dias} días, {timeframe}) desde Kraken con symbol={symbol}...")

        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=desde, limit=1000)
        if not ohlcv:
            logger.warning(f"{moneda}: sin datos válidos en Kraken")
            return pd.DataFrame()

        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["time_open"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

        delta = pd.to_timedelta("1d") if timeframe == "1d" else pd.to_timedelta("1h")
        df["time_close"] = df["time_open"] + delta

        # 🔧 Aquí estaba el bug → usamos pd.Timestamp para floor()
        end_time = pd.Timestamp(ahora_utc).tz_convert("UTC").floor("h" if timeframe == "1h" else "d")
        expected_times = pd.date_range(
            start=df["time_open"].min(),
            end=end_time,
            freq="1h" if timeframe == "1h" else "1d"
        ).tz_convert("UTC")

        df = df.set_index("time_open").reindex(expected_times)
        df.index.name = "time_open"

        df["nombre"] = moneda
        df["fuente"] = "kraken"

        # Relleno forward/backward para gaps
        df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].ffill().bfill()
        df["volume"] = df["volume"].fillna(0)

        df["time_close"] = df.index + delta
        df = df.reset_index()

        return df[["nombre", "time_open", "time_close", "open", "high", "low", "close", "volume", "fuente"]]

    except Exception as e:
        logger.error(f"{moneda}: error en obtener_historicos_kraken → {e}")
        return pd.DataFrame()

# ============================ # # Detectar si estamos en Render
def obtener_historicos(moneda, dias, timeframe="1h"):
    """
    Intenta obtener históricos en cascada:
    - Kraken (siempre primero, estable en EU)
    - CoinGecko (último recurso, aunque limitado en plan gratis)
    """
    # 🔹 Siempre probamos Kraken primero
    try:
        df = obtener_historicos_kraken(moneda, dias, timeframe)
        if not df.empty:
            return df
    except Exception as e:
        logger.warning(f"{moneda}: Kraken falló ({e}), probando CoinGecko...")
    # 🔹 CoinGecko como fallback
    try:
        df = obtener_historicos_coingecko(moneda, dias, timeframe)
        if not df.empty:
            return df
    except Exception as e:
        logger.error(f"{moneda}: CoinGecko falló definitivamente ({e})")
    logger.error(f"{moneda}: ❌ sin datos válidos en ninguna fuente")
    return pd.DataFrame()
# ====================# 🔹 Guardar datos
def guardar_datos(moneda, dias, timeframe="1h", rellenar_huecos=True):
    df = obtener_historicos(moneda, dias, timeframe)
    if df.empty:
        return f"{moneda}: ❌ sin datos válidos"

    existentes = obtener_fechas_existentes(moneda)
    faltantes = df[~df["time_open"].isin(existentes)]

    if rellenar_huecos:
        expected_times = pd.date_range(start=df["time_open"].min(), end=df["time_open"].max(), freq="h", tz="UTC")
        df = df.set_index("time_open").reindex(expected_times)
        df.index.name = "time_open"
        df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].ffill().bfill()
        df["volume"] = df["volume"].fillna(0)
        df = df.reset_index()
        inserted = insertar_filas(df)
    else:
        inserted = insertar_filas(faltantes) if not faltantes.empty else 0

    return f"{moneda}: ✅ completado ({inserted} registros)"

def guardar_datos_dias(moneda: str, dias: int = 90) -> dict:
    df = obtener_historicos(moneda, dias, "1d")
    if df.empty:
        return {"moneda": moneda, "insertados": 0}

    url = f"{SUPABASE_URL}/rest/v1/ohlcv_historicos_dias?select=time_open&nombre=eq.{moneda}"
    r = requests.get(url, headers=HEADERS)
    existentes = set(pd.to_datetime(i["time_open"]).strftime("%Y-%m-%dT%H:%M:%S") for i in r.json() if "time_open" in i)

    df["str_time_open"] = pd.to_datetime(df["time_open"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S")
    nuevos = df[~df["str_time_open"].isin(existentes)].drop(columns=["str_time_open"])
    inserted = insertar_filas_dias(nuevos) if not nuevos.empty else 0
    return {"moneda": moneda, "insertados": int(inserted)}

# ============================
# 🔹 Utilidades fetch
def obtener_fechas_existentes(moneda):
    url = f"{SUPABASE_URL}/rest/v1/ohlcv_historicos?select=time_open&nombre=eq.{moneda}&limit=2000&order=time_open.desc"
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code == 200:
        existentes = [fila["time_open"] for fila in r.json()]
        return set(pd.to_datetime(existentes))
    return set()

def _fetch_supabase(url: str) -> list:
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json() if isinstance(r.json(), list) else []

def cargar_horas_30d(moneda: str) -> pd.DataFrame:
    hasta = datetime.now(timezone.utc)
    desde = hasta - timedelta(days=30)
    url = (f"{SUPABASE_URL}/rest/v1/ohlcv_historicos"
           f"?select=nombre,time_open,time_close,open,high,low,close,volume,"
           f"rsi,macd,macd_signal,macd_hist,tendencia,recomendacion,confianza"
           f"&nombre=eq.{moneda}"
           f"&time_open=gte.{desde.strftime('%Y-%m-%dT%H:%M:%SZ')}"
           f"&order=time_open.asc")
    return pd.DataFrame(_fetch_supabase(url))

def cargar_dias_hist(moneda: str) -> pd.DataFrame:
    url = (f"{SUPABASE_URL}/rest/v1/ohlcv_historicos_dias"
           f"?select=nombre,time_open,time_close,open,high,low,close,volume,"
           f"rsi,macd,macd_signal,macd_hist,tendencia,recomendacion,confianza"
           f"&nombre=eq.{moneda}&order=time_open.asc")
    return pd.DataFrame(_fetch_supabase(url))

# ============================
# 🔹 Análisis
def analizar_moneda_completo(moneda: str) -> str:
    try:
        h = cargar_horas_30d(moneda)
        d = cargar_dias_hist(moneda)
        if h.empty:
            return f"*{moneda}:* N/A €\n⚠️ Datos insuficientes\n\n"

        last_close = float(h["close"].iloc[-1])
        rsi = float(_rsi(h["close"], 14).iloc[-1])
        rsi_compra = 30 + (np.random.rand() - 0.5) * 0.3
        rsi_venta  = 70 + (np.random.rand() - 0.5) * 0.3

        exp12, exp26 = h["close"].ewm(span=12, adjust=False).mean(), h["close"].ewm(span=26, adjust=False).mean()
        macd_raw, macd_signal = exp12 - exp26, (exp12 - exp26).ewm(span=9, adjust=False).mean()
        macd, macd_sig = float(macd_raw.iloc[-1]), float(macd_signal.iloc[-1])
        macd_trend = "↑" if macd > macd_sig else "↓" if macd < macd_sig else "→"
        trend = "ALZA" if macd > macd_sig else "BAJA" if macd < macd_sig else "PLANA"

        if rsi < rsi_compra:
            recomendacion = "🟡 Podrías comprar en pequeña cantidad (dip 25%)"
        elif rsi > rsi_venta:
            recomendacion = "🔴 Podrías vender"
        else:
            recomendacion = "⚪️ Quieto chato, no hagas huevadas"

        hi_total = float(d["high"].max()) if not d.empty else None
        lo_total = float(d["low"].min()) if not d.empty else None

        msg = f"*{moneda}:* {last_close:,.8f} €\n"
        msg += f"🟡 *RSI:* {rsi:.2f} (Compra<{rsi_compra:.2f}, Venta>{rsi_venta:.2f})\n"
        msg += f"{'🟢' if macd > macd_sig else '🔴' if macd < macd_sig else '⚪️'} *MACD:* {macd:.4f} (Señal: {macd_sig:.4f}) *{macd_trend}*\n"
        msg += f"📶 *Tendencia:* {trend}\n"
        if hi_total and lo_total:
            msg += f"📊 *Histórico:* ATH {hi_total:.2f} / ATL {lo_total:.2f}\n"
        msg += f"💡 *Recomendación:* {recomendacion}\n\n"
        return msg
    except Exception as e:
        logger.error(f"Error en analizar_moneda_completo({moneda}): {e}")
        return f"*{moneda}:* Error en análisis\n\n"

def resumen_completo(monedas: list) -> dict:
    textos = [analizar_moneda_completo(m) for m in monedas]
    actualizado = datetime.now().strftime("%d/%m/%Y %H:%M")
    resumen_txt = ("📊 *Análisis Cripto Avanzado*\n"
                   "════════════════════════\n\n" +
                   "".join(textos) +
                   "════════════════════════\n"
                   f"🔄 _Actualizado: {actualizado}_")
    return {"status": "ok", "resumen_txt": resumen_txt}
# ============================
def obtener_historicos_cmc(moneda, dias, timeframe="1h"):
    """ Usa CoinMarketCap para obtener OHLCV históricos. """
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/ohlcv/historical"
    params = {
        "symbol": moneda,
        "convert": "EUR",
        "time_start": (datetime.utcnow() - timedelta(days=dias)).strftime("%Y-%m-%d"),
        "time_end": datetime.utcnow().strftime("%Y-%m-%d"),
        "interval": "hourly" if timeframe == "1h" else "daily"
    }
    headers = {"X-CMC_PRO_API_KEY": os.getenv("COINMARKETCAP_API_KEY")}

    r = requests.get(url, headers=headers, params=params, timeout=30)
    if r.status_code == 403:
        logger.warning(f"{moneda}: CoinMarketCap no soportado en tu plan, saltando...")
        return pd.DataFrame()
    if not r.ok:
        logger.error(f"{moneda}: error en CoinMarketCap {r.status_code} {r.text}")
        return pd.DataFrame()

    data = r.json()
    if "data" not in data or "quotes" not in data["data"]:
        return pd.DataFrame()

    registros = []
    for q in data["data"]["quotes"]:
        registros.append({
            "nombre": moneda,
            "time_open": pd.to_datetime(q["time_open"], utc=True),
            "time_close": pd.to_datetime(q["time_close"], utc=True),
            "open": q["quote"]["EUR"]["open"],
            "high": q["quote"]["EUR"]["high"],
            "low": q["quote"]["EUR"]["low"],
            "close": q["quote"]["EUR"]["close"],
            "volume": q["quote"]["EUR"]["volume"],
            "fuente": "coinmarketcap"
        })
    return pd.DataFrame(registros)
# ============================
def obtener_historicos_binance(moneda, dias, timeframe="1h"):
    try:
        exchange = ccxt.binance()
        ahora_utc = datetime.now(timezone.utc)
        desde = exchange.parse8601((ahora_utc - timedelta(days=dias)).strftime('%Y-%m-%dT%H:%M:%S'))

        symbol = SYMBOL_MAP.get(moneda, f"{moneda}/USDT")
        logger.info(f"[DESCARGA] {moneda} ({dias} días, {timeframe}) desde Binance con symbol={symbol}...")

        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=desde, limit=1000)
        if not ohlcv:
            logger.warning(f"{moneda}: sin datos válidos en Binance")
            return pd.DataFrame()

        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["time_open"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        delta = pd.to_timedelta("1d") if timeframe == "1d" else pd.to_timedelta("1h")
        df["time_close"] = df["time_open"] + delta

        df["nombre"] = moneda
        df["fuente"] = "binance"

        return df[["nombre", "time_open", "time_close", "open", "high", "low", "close", "volume", "fuente"]]

    except Exception as e:
        logger.error(f"{moneda}: error en obtener_historicos_binance → {e}")
        return pd.DataFrame()

# ============================
if __name__ == "__main__":
    monedas = ["BTC", "ETH", "ADA", "SHIB", "SOL"]
    for m in monedas:
        print(guardar_datos(m, dias=3))
    for m in monedas:
        print(guardar_datos_dias(m, dias=30))
    print("=== ANALISIS ===")
    print(resumen_completo(monedas))





