@echo off
REM Recrea la base de QA de Compustock desde cero (borra el volumen PostgreSQL).
REM Uso: reset-db.cmd
setlocal
cd /d "%~dp0"

echo == Compustock: reset de la base QA ==
docker compose -f docker-compose.yml down -v
if errorlevel 1 exit /b %errorlevel%

docker compose -f docker-compose.yml up -d
if errorlevel 1 exit /b %errorlevel%

echo == Listo. Base reconstruida por 01_esquema.sql + 02_datos_semilla.sql ==
