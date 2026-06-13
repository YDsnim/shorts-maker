# =====================================================
# auto_pipeline/generate_script.py
# Claude API로 유튜브 숏츠 대본을 자동 생성합니다.
#
# 반환값:
#   {
#     "titles":   ["제목1", "제목2", "제목3"],
#     "script":   "전체 대본 텍스트",
#     "scenes":   [
#       {"text": "장면 텍스트", "keywords": ["eng1", "eng2"], "highlight_words": ["핵심어"]},
#       ...
#     ]
#   }
#   scenes[].keywords: Pexels 배경영상 검색에 사용
#   scenes[].highlight_words: 자막에서 노란색 강조할 단어 (0~1개)
# =====================================================

import json
import re
import anthropic


SYSTEM_PROMPT = """# ROLE
당신은 유튜브 숏츠 전문 시나리오 작가다.
목표는 정보 전달이 아니다.
시청자가 스크롤을 멈추고,
마지막 문장까지 보게 만드는 것이다.
조회수보다 시청 유지율을 우선한다.

---

# ABSOLUTE RULE
대본을 작성하기 전에 반드시 생각하라.
"이 첫 문장을 들은 사람이 스크롤을 멈출 이유가 있는가?"
없다면 훅을 다시 작성하라.

---

# OUTPUT GOAL
시청자가
"어?" → "왜?" → "진짜?" → "그래서?" → "오..."
순서로 반응하게 만들어라.

---

# WRITING RULES
- 한국어만 사용
- 영어 사용 금지
- 문법 오류 금지
- 문어체 금지
- 말하듯 작성
- 짧은 문장 사용
- 같은 표현 반복 금지
- 같은 문장 구조 반복 금지
- 설명체 금지
- 교과서식 서술 금지
- AI 특유의 정리형 문장 금지

---

# LENGTH
- 60초 분량
- 220~320자
- 자막 기준 작성
- 한 문장은 최대 20자 내외

---

# STRUCTURE (필수 준수)
1. 훅 — 스크롤을 멈추게 하는 첫 문장
2. 흔한 실수/착각 — 대부분이 잘못 알고 있는 것
3. 궁금증 — "왜?" 를 만드는 장치
4. 이유 공개 — 예상 밖의 핵심 이유
5. 반전/의외 사실 — "진짜?" 반응
6. 짧은 결론 — "오..." 여운

나쁜 흐름
훅 → 설명 → 설명 → 설명 → 결론

좋은 흐름
훅 → 착각 → 궁금증 → 이유 공개 → 반전 → 결론

---

# MOST IMPORTANT RULE
사실을 바로 공개하지 마라.
궁금증을 먼저 만들고 정보는 나중에 공개하라.
결과를 먼저 보여주고 원인은 뒤에서 설명하라.

---

# HOOK RULE
훅은 아래 중 하나를 사용한다.
- 손해
- 실수
- 충격
- 반전
- 금기
- 비밀
- 숨겨진 사실

좋은 예시
- 대부분 반대로 알고 있습니다.
- 이것 때문에 망칩니다.
- 전문가들은 이렇게 안 합니다.
- 아무도 설명하지 않는 이유가 있습니다.
- 사실 정반대입니다.
- 의외로 이게 더 중요합니다.

---

# CURIOSITY RULE
3문장 이상 연속으로 설명하지 마라.
설명 후에는 반드시 새로운 궁금증을 만든다.

나쁜 예
A 설명
B 설명
C 설명
D 설명

좋은 예
A 설명
그런데 문제는 여기부터입니다.
B 설명
하지만 대부분 모릅니다.
C 설명
진짜 이유는 따로 있습니다.

---

# VALUE RULE
반드시 포함
- 이유
- 결과
- 실전 적용법

금지
- 사실만 말하기
- 정보 나열하기
- 위키백과 스타일 설명

---

# ENDING RULE
마지막 문장은 "그래서 도움이 됐다" 느낌을 줘야 한다.

금지
- 이상입니다
- 어떠셨나요
- 오늘은 여기까지
- 긴 구독 멘트

허용
- 한번 해보면 차이가 납니다.
- 바로 적용할 수 있습니다.
- 의외로 효과가 큽니다.
- 알고 있으면 꽤 유용합니다.

---

# ORIGINALITY RULE
대본 작성 전에
현재 주제에 대해 사람들이 이미 100번은 들어봤을 법한 표현을 모두 버려라.
가장 흔한 설명 방식을 피하고
가장 흥미로운 진입점을 찾아라.

---

# SELF REVIEW
작성 후 스스로 평가
1. 첫 문장이 스크롤을 멈추게 하는가
2. 중간에 결론이 너무 빨리 나오지 않았는가
3. 설명만 이어지는 구간이 있는가
4. 궁금증이 계속 유지되는가
5. 마지막까지 보게 만드는가
6. 흔한 AI 대본처럼 보이지 않는가

하나라도 아니오라면 다시 작성하라."""


def generate_script(topic: str, api_key: str, model: str = 'claude-haiku-4-5-20251001') -> dict:
    """
    주어진 주제로 60초 분량 숏츠 대본과 장면별 배경영상 키워드를 생성합니다.

    topic:   숏츠 주제
    api_key: Claude API 키
    model:   사용할 Claude 모델

    반환: {'titles': [...], 'script': '...', 'scenes': [{text, keywords, highlight_words}, ...]}
    """
    if not api_key:
        raise ValueError(
            "CLAUDE_API_KEY가 설정되지 않았습니다.\n"
            "환경변수: export CLAUDE_API_KEY=sk-ant-..."
        )

    import os
    base_url = os.environ.get('ANTHROPIC_BASE_URL')
    client = anthropic.Anthropic(api_key=api_key, **({"base_url": base_url} if base_url else {}))

    prompt = f"""주제: {topic}

대본을 작성하기 전에 먼저 스스로 평가하라.
"이 영상을 처음 보는 시청자가 첫 문장을 듣고 스크롤을 멈출 확률이 높은가?"
아니라면 훅을 다시 작성하라.

아래 형식의 JSON만 출력해줘 (다른 설명 없이):
{{
  "titles": ["제목1", "제목2", "제목3"],
  "script": "최종 대본 전체",
  "scenes": [
    {{"text": "장면1 문장(1~2문장)", "keywords": ["영어키워드1", "영어키워드2"], "highlight_words": ["핵심단어"]}},
    {{"text": "장면2 문장", "keywords": ["영어키워드3"], "highlight_words": []}},
    ...
  ]
}}

scenes 규칙:
- 전체 대본을 5~8개 장면으로 분할 (장면 = 1~2문장)
- keywords: Pexels 배경영상 검색용 영어 단어 1~2개 (장면 내용과 어울리는 시각적 이미지)
- highlight_words: 해당 장면에서 가장 핵심이 되는 단어 1개 (없으면 빈 배열). 모든 단어를 강조하지 말 것.

titles: 영상 제목 후보 3개 (한국어, 클릭을 유도하는 제목)
script: 위 규칙을 모두 적용한 최종 대본 전체 텍스트"""

    message = client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': prompt}]
    )

    text_block = next((b for b in message.content if hasattr(b, 'text') and b.text), None)
    if text_block is None:
        raise RuntimeError(f'Claude 응답에 텍스트 블록이 없습니다. blocks={[type(b).__name__ for b in message.content]}')
    raw = text_block.text.strip()

    json_match = re.search(r'\{[\s\S]*\}', raw)
    if json_match:
        raw = json_match.group(0)

    try:
        result = json.loads(raw)
        if 'titles' not in result or not result['titles']:
            result['titles'] = []
        if 'script' not in result:
            result['script'] = raw
        # scenes 유효성 확인
        if 'scenes' not in result or not isinstance(result['scenes'], list) or not result['scenes']:
            result['scenes'] = []
            result['keywords'] = ['background', 'abstract', 'nature']
        else:
            # 각 scene 필드 보정
            for s in result['scenes']:
                if 'keywords' not in s or not s['keywords']:
                    s['keywords'] = ['background']
                if 'highlight_words' not in s:
                    s['highlight_words'] = []
        return result
    except json.JSONDecodeError:
        return {
            'titles':   [],
            'script':   raw,
            'scenes':   [],
            'keywords': ['background', 'abstract', 'nature'],
        }
