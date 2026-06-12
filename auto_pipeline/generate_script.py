# =====================================================
# auto_pipeline/generate_script.py
# Claude API로 유튜브 숏츠 대본을 자동 생성합니다.
#
# 반환값:
#   {
#     "script":   "대본 텍스트",
#     "keywords": ["영어 키워드1", "영어 키워드2", "영어 키워드3"]
#   }
#   keywords는 Pexels 배경영상 검색에 사용됩니다.
#
# 비용: claude-haiku 기준 편당 약 1~2원
# =====================================================

import json
import anthropic


def generate_script(topic: str, api_key: str, model: str = 'claude-haiku-4-5-20251001') -> dict:
    """
    주어진 주제로 60초 분량 숏츠 대본과 배경영상 검색 키워드를 생성합니다.

    topic:   숏츠 주제 (예: '한국인이 모르는 심리학 사실 5가지')
    api_key: Claude API 키
    model:   사용할 Claude 모델 (기본: haiku - 저렴하고 빠름)

    반환: {'script': '...', 'keywords': ['word1', 'word2', 'word3']}
    """
    if not api_key:
        raise ValueError(
            "CLAUDE_API_KEY가 설정되지 않았습니다.\n"
            "환경변수: export CLAUDE_API_KEY=sk-ant-..."
        )

    client = anthropic.Anthropic(api_key=api_key)

    # Claude에게 대본 + Pexels 검색 키워드를 JSON으로 함께 요청합니다
    prompt = f"""다음 주제로 유튜브 숏츠 대본을 작성해줘.
주제: {topic}

아래 형식의 JSON만 출력해줘 (다른 설명 없이):
{{
  "script": "대본 내용",
  "keywords": ["영어 키워드1", "영어 키워드2", "영어 키워드3"]
}}

대본 작성 조건:
- 한국어 작성, 60초 낭독 분량 (200~250자)
- 첫 3초 강한 훅: "당신은 이걸 몰랐을 겁니다..." 식으로 시작
- 짧은 문장 위주 (한 문장에 20자 이내, 자막에 어울리게)
- 마지막은 구독 유도 멘트로 마무리
- 문어체 금지, 말하는 것처럼 자연스럽게

keywords 조건:
- Pexels 배경영상 검색에 쓸 영어 단어 3개
- 주제와 어울리는 시각적 이미지 (예: 심리학 → brain, mind, thinking)"""

    message = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()

    # Claude가 ```json ... ``` 형식으로 감쌀 때 벗겨냅니다
    if '```' in raw:
        parts = raw.split('```')
        for p in parts:
            p = p.strip()
            if p.startswith('json'):
                p = p[4:].strip()
            if p.startswith('{'):
                raw = p
                break

    try:
        result = json.loads(raw)
        # 필드 검증: 누락된 경우 기본값 보충
        if 'script' not in result:
            result['script'] = raw
        if 'keywords' not in result or not result['keywords']:
            result['keywords'] = ['background', 'abstract', 'nature']
        return result
    except json.JSONDecodeError:
        # JSON 파싱 실패 시 전체 텍스트를 대본으로 사용
        return {
            'script':   raw,
            'keywords': ['background', 'abstract', 'nature'],
        }
