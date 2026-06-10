@echo off
chcp 65001 > nul
echo.
echo  숏츠 메이커를 시작합니다...
echo.

:: 패키지 설치 확인
python -c "import flask" 2>nul || (
    echo  Flask가 없습니다. 설치 중...
    pip install -r requirements.txt
)

:: 앱 실행
python app.py
pause
