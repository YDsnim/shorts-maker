import re
import urllib.request
import requests
from bs4 import BeautifulSoup

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}

# bp_thumbnail_resize("URL", "제목") 형태에서 URL 추출
_BP_RE = re.compile(r'bp_thumbnail_resize\("(https://[^"]+)"')


def _to_japanese(text: str) -> str:
    """한국어/영어 → 이라스토야 검색에 적합한 일본어 키워드 변환.
    Claude Haiku 사용 → 실패 시 Google Translate fallback."""
    try:
        import anthropic, os
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        client = anthropic.Anthropic(
            api_key=os.environ.get('CLAUDE_API_KEY', ''),
            base_url=os.environ.get('ANTHROPIC_BASE_URL', 'https://api.anthropic.com'),
        )
        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=30,
            messages=[{
                'role': 'user',
                'content': (
                    '이라스토야(いらすとや) 사이트 검색어로 쓸 일본어 키워드를 만들어줘.\n'
                    '규칙: 동사는 사전형(寝る/怒る/飲む 등), 사람은 男性/女性/人, 2~4단어로 짧게.\n'
                    '예) 잠자는 남자 → 寝る男性 / 화난 사람 → 怒る人 / 커피 마시는 사람 → コーヒーを飲む人\n'
                    f'입력: {text}\n'
                    '일본어 키워드만 출력(설명 없이):'
                ),
            }],
        )
        text_blocks = [b for b in msg.content if hasattr(b, 'text')]
        return text_blocks[0].text.strip() if text_blocks else text
    except Exception:
        # Claude 실패 시 Google Translate fallback
        try:
            resp = requests.get(
                'https://translate.googleapis.com/translate_a/single',
                params={'client': 'gtx', 'sl': 'auto', 'tl': 'ja', 'dt': 't', 'q': text},
                headers=_HEADERS, timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
            return ''.join(seg[0] for seg in data[0] if seg[0])
        except Exception:
            return text


def search_images(keyword: str, n: int = 3) -> list:
    """이라스토야 검색. 키워드를 일본어로 변환 후 검색. [{'thumb': url, 'full': url, 'title': str}] 반환"""
    jp_keyword = _to_japanese(keyword)
    url = f'https://www.irasutoya.com/search?q={requests.utils.quote(jp_keyword)}'
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=12)
        resp.raise_for_status()
    except Exception:
        return []

    soup    = BeautifulSoup(resp.text, 'html.parser')
    results = []

    # 실제 검색 결과는 #Blog1 안의 div#post 목록
    blog1 = soup.find(id='Blog1')
    if not blog1:
        return []

    for post in blog1.find_all('div', id='post'):
        # 이미지 URL: .boxim 안 script 태그에서 추출
        img_url = ''
        for sc in post.select('.boxim script'):
            m = _BP_RE.search(sc.string or '')
            if m:
                img_url = m.group(1)
                break
        if not img_url:
            continue

        # s72-c → s400 (썸네일), s0 (원본)
        thumb = re.sub(r's72-c', 's400', img_url)
        full  = re.sub(r's72-c', 's0',   img_url)

        # 제목: .boxmeta h2 a
        title_tag = post.select_one('.boxmeta h2 a')
        title = title_tag.get_text(strip=True) if title_tag else keyword

        results.append({'thumb': thumb, 'full': full, 'title': title})
        if len(results) >= n:
            break

    return results


def download_image(url: str, out_path: str) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        with open(out_path, 'wb') as f:
            f.write(r.read())
    return out_path
