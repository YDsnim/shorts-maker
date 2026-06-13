# =====================================================
# auto_pipeline/get_background.py
# Pexels API에서 배경 영상을 검색·다운로드합니다.
#
# Pexels: 무료 스톡 영상 사이트, 상업적 사용 가능
# API 키 발급: https://www.pexels.com/api (무료)
# 제한: 시간당 200요청, 월 20,000요청
# =====================================================

import random
import requests


def search_videos(keywords: list, api_key: str,
                  orientation: str = 'portrait') -> list:
    """
    Pexels API로 배경 영상을 검색합니다.

    keywords:    검색 키워드 목록 (영어 단어들, 앞 2개 사용)
    api_key:     Pexels API 키
    orientation: 'portrait'(세로, 숏츠에 적합) | 'landscape' | 'square'
    반환:        Pexels 영상 정보 목록
    """
    if not api_key:
        raise ValueError(
            "PEXELS_API_KEY가 설정되지 않았습니다.\n"
            "https://www.pexels.com/api 에서 무료 발급 후\n"
            "환경변수: export PEXELS_API_KEY=..."
        )

    # 앞 두 키워드를 합쳐서 검색 (더 많은 결과)
    query = ' '.join(keywords[:2])
    headers = {'Authorization': api_key}
    params = {
        'query':       query,
        'per_page':    10,
        'orientation': orientation,
        'size':        'large',
    }

    res = requests.get(
        'https://api.pexels.com/videos/search',
        headers=headers, params=params, timeout=30,
    )
    res.raise_for_status()
    videos = res.json().get('videos', [])

    # 세로형 결과가 없으면 방향 무관하게 재검색
    if not videos and orientation == 'portrait':
        params.pop('orientation')
        res = requests.get(
            'https://api.pexels.com/videos/search',
            headers=headers, params=params, timeout=30,
        )
        res.raise_for_status()
        videos = res.json().get('videos', [])

    # 그래도 없으면 첫 번째 키워드만으로 재시도
    if not videos and len(keywords) > 1:
        params['query'] = keywords[0]
        res = requests.get(
            'https://api.pexels.com/videos/search',
            headers=headers, params=params, timeout=30,
        )
        res.raise_for_status()
        videos = res.json().get('videos', [])

    return videos


def download_best_video(videos: list, output_path: str,
                        min_duration: float = 30.0) -> str:
    """
    검색된 목록에서 가장 적합한 영상을 골라 다운로드합니다.

    min_duration: 최소 필요 길이(초). 짧은 영상은 건너뜁니다.
    반환:         다운로드된 파일 경로
    """
    if not videos:
        raise RuntimeError("다운로드할 배경 영상이 없습니다. 다른 키워드를 시도해보세요.")

    # 음성보다 긴 영상만 후보로 추립니다
    candidates = [v for v in videos if v.get('duration', 0) >= min_duration]
    if not candidates:
        candidates = videos  # 길이 조건 충족 영상 없으면 전체 사용

    # 매번 같은 영상이 나오지 않도록 상위 5개 중 무작위 선택
    video = random.choice(candidates[:5])

    # 해상도가 가장 높은 파일 URL 선택
    video_files = sorted(
        video.get('video_files', []),
        key=lambda x: x.get('width', 0) * x.get('height', 0),
        reverse=True,
    )

    if not video_files:
        raise RuntimeError("다운로드 가능한 영상 파일 정보를 찾지 못했습니다.")

    url = video_files[0]['link']

    # 스트리밍 다운로드 (대용량 파일도 메모리 과부하 없이 처리)
    res = requests.get(url, stream=True, timeout=120)
    res.raise_for_status()

    with open(output_path, 'wb') as f:
        for chunk in res.iter_content(chunk_size=65536):
            f.write(chunk)

    return output_path


def download_scene_clips(scenes: list, api_key: str, tmp_dir: str,
                         min_duration: float = 8.0) -> list:
    """
    각 장면(scene)에 맞는 배경 영상을 개별 다운로드합니다.

    scenes:  [{'text': '...', 'keywords': ['word1'], 'highlight_words': [...]}, ...]
    반환:    ['tmp/scene_0.mp4', 'tmp/scene_1.mp4', ...]
    """
    paths = []
    prev_keywords = None

    for i, scene in enumerate(scenes):
        keywords = scene.get('keywords', ['background'])
        out_path = f'{tmp_dir}\\scene_{i}.mp4'

        try:
            videos = search_videos(keywords, api_key)
            # 이전 장면과 같은 키워드면 결과 리스트에서 다른 영상 선택
            if keywords == prev_keywords and videos:
                video_files = sorted(
                    videos[min(1, len(videos) - 1)].get('video_files', []),
                    key=lambda x: x.get('width', 0) * x.get('height', 0),
                    reverse=True,
                )
                if video_files:
                    url = video_files[0]['link']
                    res = requests.get(url, stream=True, timeout=120)
                    res.raise_for_status()
                    with open(out_path, 'wb') as f:
                        for chunk in res.iter_content(chunk_size=65536):
                            f.write(chunk)
                    paths.append(out_path)
                    prev_keywords = keywords
                    continue

            download_best_video(videos, out_path, min_duration=min_duration)
            paths.append(out_path)
        except Exception as e:
            print(f'[WARN] scene {i} 배경 다운로드 실패 ({keywords}): {e}')
            # 폴백: 'background' 키워드로 재시도
            try:
                fallback = search_videos(['background', 'nature'], api_key)
                download_best_video(fallback, out_path, min_duration=min_duration)
                paths.append(out_path)
            except Exception as e2:
                print(f'[WARN] scene {i} 폴백도 실패: {e2}')
                if paths:
                    paths.append(paths[-1])  # 이전 클립 재사용

        prev_keywords = keywords

    if not paths:
        raise RuntimeError('모든 장면의 배경 영상 다운로드에 실패했습니다.')

    return paths


def download_multiple_videos(videos: list, tmp_dir: str,
                              n: int = 3,
                              min_duration: float = 10.0) -> list:
    """
    검색된 목록에서 최대 n개의 서로 다른 영상을 다운로드합니다.

    반환: 다운로드된 파일 경로 리스트 (1개 이상 보장)
    """
    if not videos:
        raise RuntimeError("다운로드할 배경 영상이 없습니다. 다른 키워드를 시도해보세요.")

    candidates = [v for v in videos if v.get('duration', 0) >= min_duration]
    if not candidates:
        candidates = videos

    pool = candidates[:max(n * 2, 6)]
    random.shuffle(pool)
    selected = pool[:n]

    paths = []
    for i, video in enumerate(selected):
        video_files = sorted(
            video.get('video_files', []),
            key=lambda x: x.get('width', 0) * x.get('height', 0),
            reverse=True,
        )
        if not video_files:
            continue

        url = video_files[0]['link']
        out = f'{tmp_dir}\\bg_{i}.mp4'

        res = requests.get(url, stream=True, timeout=120)
        res.raise_for_status()

        with open(out, 'wb') as f:
            for chunk in res.iter_content(chunk_size=65536):
                f.write(chunk)

        paths.append(out)

    if not paths:
        raise RuntimeError("배경 영상 다운로드에 실패했습니다.")

    return paths
