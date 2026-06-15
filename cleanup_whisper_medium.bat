@echo off
echo Whisper medium 모델 삭제 중...
set MODEL_PATH=%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-medium
if exist "%MODEL_PATH%" (
    rmdir /s /q "%MODEL_PATH%"
    echo 삭제 완료!
) else (
    echo medium 모델이 없거나 이미 삭제됨.
)
pause
