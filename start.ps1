# Activa el entorno virtual
$env:VIRTUAL_ENV = ".\venv"
.\venv\Scripts\Activate.ps1

# Verificación previa de sintaxis y estilo
Write-Host "`n[PASO 1/3] Verificando sintaxis del código..." -ForegroundColor Cyan
python -m py_compile monitor_criptos.py
if (-not $?) {
    Write-Host "`n❌ Error de sintaxis encontrado. Corrige los errores antes de continuar." -ForegroundColor Red
    exit 1
}

Write-Host "`n[PASO 2/3] Verificando estilo y posibles errores..." -ForegroundColor Cyan
python -m flake8 monitor_criptos.py --max-line-length=120
if (-not $?) {
    Write-Host "`n⚠️ Advertencias de estilo encontradas. Considera corregirlas." -ForegroundColor Yellow
    # No salimos aquí porque pueden ser solo advertencias
}

Write-Host "`n[PASO 3/3] Ejecutando el script principal..." -ForegroundColor Cyan
python monitor_criptos.py

if (-not $?) {
    Write-Host "`n❌ El script terminó con errores." -ForegroundColor Red
    exit 1
}