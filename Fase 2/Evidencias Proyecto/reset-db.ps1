#!/usr/bin/env pwsh
# Recrea la base de QA de Compustock desde cero (borra el volumen PostgreSQL).
# Uso: .\reset-db.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "== Compustock: reset de la base QA =="
docker compose -f docker-compose.yml down -v
docker compose -f docker-compose.yml up -d

Write-Host "== Listo. Base reconstruida por 01_esquema.sql + 02_datos_semilla.sql =="
