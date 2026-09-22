@echo off
title Saldo de Diarias - MDS/DITRAN

echo ============================================
echo   Sistema de Controle de Saldo de Diarias
echo   MDS / DITRAN
echo ============================================
echo.

:: Verifica Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale em https://python.org
    pause
    exit /b 1
)

:: Instala dependências se necessário
if not exist "venv\" (
    echo Criando ambiente virtual...
    python -m venv venv
)

call venv\Scripts\activate.bat

pip show flask >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias...
    pip install -r requirements.txt
)

echo.
echo Iniciando servidor em http://localhost:5000
echo Pressione Ctrl+C para encerrar.
echo.

python app.py

pause
