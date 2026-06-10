# =====================================================
# modules/ai_helper.py
# 미래 확장용 AI 기능 모듈 (현재 비어있음)
#
# 나중에 추가할 기능:
#   - Claude API: 자막 자동 생성, 대본 작성, 태그 추천
#   - 이미지 생성 API: 썸네일 자동 제작
#   - Whisper: 영상 속 말소리 → 자막 자동 추출
# =====================================================

# ── Claude API 연동 예시 (미구현) ──────────────────
# import anthropic
#
# def generate_script(topic: str) -> str:
#     """Claude로 숏츠 대본 생성"""
#     client = anthropic.Anthropic(api_key=config.CLAUDE_API_KEY)
#     message = client.messages.create(
#         model="claude-opus-4-8",
#         max_tokens=1024,
#         messages=[{"role": "user", "content": f"유튜브 숏츠 대본 작성: {topic}"}]
#     )
#     return message.content[0].text
#
# ── 이미지 생성 API 연동 예시 (미구현) ───────────────
# def generate_thumbnail(prompt: str) -> str:
#     """AI로 썸네일 이미지 생성"""
#     pass


def placeholder():
    """AI 기능이 추가되기 전까지 빈 함수입니다."""
    return {"status": "준비 중"}
