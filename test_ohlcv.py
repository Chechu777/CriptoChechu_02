import os
from supabase import create_client
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Configuración directa (NO RECOMENDADO para producción)
SUPABASE_URL = "https://kcvniknwykjvwcybcdyj.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imtjdm5pa253eWtqdndjeWJjZHlqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTM1NTY2OTUsImV4cCI6MjA2OTEzMjY5NX0.u6IVtxAvXRBg51q42en4YO2szaJERXX4mMTHRSQ8BYw"

# Inicializar cliente Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def guardar_datos_test():
    print("=== Iniciando prueba de OHLCV ===")
    
    # Datos de prueba (BTC)
    test_data = [{
        "nombre": "BTC",
        "intervalo": "1d",
        "time_open": datetime.now(timezone.utc).isoformat(),
        "time_close": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "open": 50000.50,
        "high": 50500.75,
        "low": 49500.25,
        "close": 50200.00,
        "volume": 1250.42,
        "convert": "EUR",
        "fuente": "TEST_SCRIPT"
    }]

    try:
        print("Intentando insertar datos...")
        response = supabase.table("ohlcv").upsert(test_data).execute()
        
        if response.data:
            print(f"✅ Datos insertados correctamente. ID: {response.data[0]['id']}")
            print("Registro insertado:", response.data[0])
        else:
            print("⚠️ No se recibieron datos en la respuesta (¿conflicto de duplicados?)")

    except Exception as e:
        print(f"❌ Error al insertar: {str(e)}")

# Verificar conexión primero
def verificar_conexion():
    try:
        print("Verificando conexión a Supabase...")
        result = supabase.table("ohlcv").select("count", count="exact").limit(1).execute()
        print(f"✔️ Conexión exitosa. Tabla contiene {result.count} registros")
        return True
    except Exception as e:
        print(f"✖️ Error de conexión: {str(e)}")
        return False

# Ejecutar pruebas
if verificar_conexion():
    guardar_datos_test()

    # Consultar los últimos 3 registros
    print("\nConsultando últimos registros...")
    try:
        registros = supabase.table("ohlcv").select("*").order("time_open", desc=True).limit(3).execute()
        for idx, reg in enumerate(registros.data):
            print(f"\nRegistro {idx + 1}:")
            print(f"Moneda: {reg['nombre']} ({reg['intervalo']})")
            print(f"Fecha: {reg['time_open']}")
            print(f"Precios: O:{reg['open']} H:{reg['high']} L:{reg['low']} C:{reg['close']}")
    except Exception as e:
        print(f"Error al consultar: {str(e)}")