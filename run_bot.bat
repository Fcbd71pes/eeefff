@echo off
REM eFootball Bot - Windows Batch File
REM এই ফাইলটি ডাবল-ক্লিক করে বোট চালান

cls
echo.
echo ========================================
echo   eFootball Tournament Bot
echo ========================================
echo.

REM চেক করুন Python ইনস্টল আছে কিনা
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Error: Python ইনস্টল নেই!
    echo Python ডাউনলোড করুন: https://www.python.org
    pause
    exit /b 1
)

echo ✓ Python আছে
echo.

REM প্যাকেজ ইনস্টল করুন (প্রথমবার)
echo ডিপেন্ডেন্সি চেক করছি...
python -c "import telegram" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo প্যাকেজ ইনস্টল করছি...
    python -m pip install -r requirements.txt
)

echo.
echo ========================================
echo   বোট শুরু হচ্ছে...
echo ========================================
echo.

REM বোট চালান
python bot.py

pause
