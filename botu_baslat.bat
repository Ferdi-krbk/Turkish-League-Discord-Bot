@echo off
title Turkish Super League Bot Starter
color 0b
echo ======================================================
echo    TURKIYE SUPER LIGI SIMULASYON BOTU - BASLATICI
echo ======================================================
echo.

:: Python kontrolü
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [HATA] Python bilgisayarda yuklu degil! 
    echo Lutfen https://www.python.org/ adresinden Python 3.10 veya ustu bir surum yukleyin.
    echo Yuklerken "Add Python to PATH" kutucugunu isaretlemeyi unutmayin.
    pause
    exit
)

echo [SISTEM] Gerekli kutuphaneler kontrol ediliyor...
echo Bu islem ilk seferde biraz surebilir, lutfen bekleyin.
pip install -r requirements.txt --quiet

if %errorlevel% neq 0 (
    echo [UYARI] Kutuphaneler yuklenirken bir sorun yasandi. 
    echo Internet baglantinizi kontrol edin.
)

echo.
echo [OK] Her sey hazir! Bot simdi aciliyor...
echo.
python main.py
pause
