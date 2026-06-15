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

:: Whisper medium 모델 자동 삭제 (large-v3-turbo로 교체됨)
set MEDIUM_PATH=%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-medium
if exist "%MEDIUM_PATH%" (
    echo  Whisper medium 모델 삭제 중...
    rmdir /s /q "%MEDIUM_PATH%"
    echo  삭제 완료.
)

:: 앱 실행
python app.py
pause
