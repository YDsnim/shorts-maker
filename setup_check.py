"""
setup_check.py - 실행 전 환경 확인 스크립트
python setup_check.py 로 실행하세요
"""

import subprocess
import sys
import importlib

OK   = "[OK]"
FAIL = "[XX]"
WARN = "[!!]"

def check(label, ok, hint=""):
    mark = OK if ok else FAIL
    print(f"  {mark} {label}")
    if not ok and hint:
        print(f"       → {hint}")
    return ok

all_ok = True

print("\n─── 숏츠 메이커 환경 확인 ───\n")

# ffmpeg
try:
    r = subprocess.run(['ffmpeg', '-version'], capture_output=True)
    ok = r.returncode == 0
except FileNotFoundError:
    ok = False
all_ok &= check(
    "ffmpeg",
    ok,
    "https://www.gyan.dev/ffmpeg/builds/ 에서 ffmpeg를 설치하고 PATH에 추가해주세요"
)

# ffprobe
try:
    r = subprocess.run(['ffprobe', '-version'], capture_output=True)
    ok = r.returncode == 0
except FileNotFoundError:
    ok = False
all_ok &= check("ffprobe (ffmpeg에 포함)", ok)

# Python 패키지
for pkg, pip_name in [
    ("flask",    "flask"),
    ("edge_tts", "edge-tts"),
]:
    try:
        importlib.import_module(pkg)
        ok = True
    except ImportError:
        ok = False
    all_ok &= check(
        f"Python 패키지: {pip_name}",
        ok,
        f"pip install {pip_name}"
    )

print()
if all_ok:
    print(f"{OK} 모든 환경 준비 완료! python app.py 를 실행하세요.\n")
else:
    print(f"{FAIL} 위 항목을 설치 후 다시 확인해주세요.\n")
