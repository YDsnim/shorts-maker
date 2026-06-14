# =====================================================
# auto_pipeline/assemble.py
# 음성 + 배경 영상 + Whisper 자막을 조합해 최종 숏츠를 만듭니다.
# =====================================================

import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from modules.subtitle import build_ass_file, burn_subtitles
from modules.banner   import (generate_banner_png, generate_title_overlay_png,
                               generate_source_overlay_png, generate_custom_layers_png)
from modules.template import get_template

MAX_SUBTITLE_CHARS = 15


def assemble_stages(voice_path: str, bg_paths,
                    output_path: str, duration: float,
                    jobs: dict, job_id: str,
                    srt_save_path: str = None,
                    scenes: list = None,
                    title: str = None,
                    template: str = 'namnam',
                    use_tts: bool = True,
                    overlay_specs: list = None,
                    positions: dict = None,
                    styles: dict = None,
                    source_text: str = '',
                    use_subtitle: bool = True,
                    custom_layers: list = None,
                    text_overlays: list = None) -> None:
    tmp = tempfile.mkdtemp()
    positions     = positions     or {}
    styles        = styles        or {}
    custom_layers = custom_layers or []
    text_overlays = text_overlays or []

    try:
        # ── 1. 배경 영상 준비 ────────────────────────────
        jobs[job_id].update({'pct': 42, 'msg': '🎬 배경 영상 자르는 중...'})
        trimmed = os.path.join(tmp, 'trimmed.mp4')

        if template == 'silver_crown':
            _build_silver_crown_bg(bg_paths, duration, template, tmp, trimmed, positions)
        else:
            # namnam 및 기본: 단색 배경 + 영상 창 삽입
            _build_namnam_bg(bg_paths, duration, template, tmp, trimmed, positions)

        # ── 2. 음성 합치기 ────────────────────────────────
        jobs[job_id].update({'pct': 55, 'msg': '🔊 음성 합치는 중...'})
        merged = os.path.join(tmp, 'merged.mp4')

        if use_tts:
            # TTS 음성 + 원본 소스 오디오 동시 믹싱 (TTS 1.5배, 원본 0.5배)
            source_for_audio = bg_paths[0] if isinstance(bg_paths, list) else bg_paths
            try:
                _run_ffmpeg([
                    'ffmpeg',
                    '-i', trimmed,
                    '-i', voice_path,
                    '-i', source_for_audio,
                    '-filter_complex',
                    '[1:a][2:a]amix=inputs=2:duration=first:weights=1.5 0.5[aout]',
                    '-map', '0:v:0',
                    '-map', '[aout]',
                    '-c:v', 'copy', '-c:a', 'aac',
                    '-shortest',
                    '-y', merged,
                ])
            except RuntimeError:
                # 원본에 오디오 트랙이 없으면 TTS만 사용
                _run_ffmpeg([
                    'ffmpeg',
                    '-i', trimmed, '-i', voice_path,
                    '-map', '0:v:0', '-map', '1:a:0',
                    '-c:v', 'copy', '-c:a', 'aac',
                    '-shortest', '-y', merged,
                ])
        else:
            # TTS 없음 — voice_path = 소스에서 추출한 원본 오디오
            _run_ffmpeg([
                'ffmpeg',
                '-i', trimmed,
                '-i', voice_path,
                '-map', '0:v:0',
                '-map', '1:a:0',
                '-c:v', 'copy', '-c:a', 'aac',
                '-shortest',
                '-y', merged,
            ])

        # ── 3. Whisper 자막 타이밍 생성 + 소각 ──────────────
        srt_path = os.path.join(tmp, 'subtitles.srt')
        if use_subtitle:
            jobs[job_id].update({'pct': 65, 'msg': '📝 자막 타이밍 생성 중 (Whisper)...'})
            ass_path = os.path.join(tmp, 'subtitles.ass')
            _generate_subtitles(
                voice_path, ass_path, srt_path, scenes or [], template,
                positions=positions, styles=styles,
            )
            jobs[job_id].update({'pct': 88, 'msg': '✍️ 자막 영상에 굽는 중...'})
            subtitled = os.path.join(tmp, 'subtitled.mp4')
            burn_subtitles(merged, ass_path, subtitled)
        else:
            jobs[job_id].update({'pct': 88, 'msg': '⏭️ 자막 생략...'})
            subtitled = merged
            ass_path  = None

        # ── 5. 템플릿 합성 ────────────────────────────────
        jobs[job_id].update({'pct': 94, 'msg': '🎨 템플릿 합성 중...'})
        templated = os.path.join(tmp, 'templated.mp4')
        _apply_template(subtitled, title or '', template, tmp, templated,
                        positions, styles, source_text, custom_layers)

        # ── 6. 오버레이 합성 ──────────────────────────────
        intermediate = os.path.join(tmp, 'intermediate.mp4')
        if overlay_specs:
            jobs[job_id].update({'pct': 96, 'msg': '🎨 이미지 오버레이 적용 중...'})
            _apply_irasutoya_overlays(templated, overlay_specs, duration, intermediate)
        else:
            shutil.copy2(templated, intermediate)

        if text_overlays:
            jobs[job_id].update({'pct': 98, 'msg': '✏️ 텍스트 오버레이 적용 중...'})
            _apply_text_overlays(intermediate, text_overlays, output_path)
        else:
            shutil.copy2(intermediate, output_path)


        if srt_save_path and use_subtitle and os.path.exists(srt_path):

            shutil.copy2(srt_path, srt_save_path)

        jobs[job_id].update({'pct': 100, 'done': True})

    except Exception as e:
        jobs[job_id].update({'done': True, 'error': str(e)})
        raise
    finally:

        shutil.rmtree(tmp, ignore_errors=True)


def _concat_scene_clips(bg_paths: list, scenes: list,
                        duration: float, tmp: str, out_path: str) -> None:
    """
    각 장면 클립을 글자 수 비율에 맞게 개별 trim+crop 후 concat합니다.
    결과를 out_path에 직접 씁니다 (stream_loop 없음).
    """
    total_chars = sum(len(s.get('text', '')) for s in scenes) or 1
    scene_trimmed = []

    for i, (clip, scene) in enumerate(zip(bg_paths, scenes)):
        scene_dur = max((len(scene.get('text', '')) / total_chars) * duration, 1.5)
        out = os.path.join(tmp, f'scene_{i}_trim.mp4')
        try:
            _run_ffmpeg([
                'ffmpeg', '-stream_loop', '-1', '-i', clip,
                '-t', str(scene_dur),
                '-vf', 'scale=1080:1920:force_original_aspect_ratio=increase,'
                       'crop=1080:1920',
                '-r', '30',          # 프레임 레이트 통일 (concat 호환성)
                '-c:v', 'libx264', '-an',
                '-y', out,
            ])
            scene_trimmed.append(out)
        except Exception as e:
            print(f'[WARN] scene {i} trim 실패, 건너뜀: {e}')

    if not scene_trimmed:
        raise RuntimeError('모든 장면 클립 처리에 실패했습니다.')

    if len(scene_trimmed) == 1:

        shutil.copy2(scene_trimmed[0], out_path)
        return

    # 모든 scene_N_trim.mp4는 이미 1080×1920 / 30fps → 단순 concat 가능
    inputs = []
    for p in scene_trimmed:
        inputs += ['-i', p]
    n = len(scene_trimmed)
    filter_str = ''.join(f'[{i}:v]' for i in range(n)) + f'concat=n={n}:v=1[v]'
    _run_ffmpeg([
        'ffmpeg', *inputs,
        '-filter_complex', filter_str,
        '-map', '[v]',
        '-c:v', 'libx264', '-an',
        '-y', out_path,
    ])


def _simple_concat(paths: list, tmp: str, out_name: str = 'concat_bg.mp4') -> str:
    """여러 클립을 1080×1920으로 스케일 후 concat합니다."""
    out = os.path.join(tmp, out_name)
    inputs = []
    for p in paths:
        inputs += ['-i', p]
    n = len(paths)
    scale_parts = [
        f'[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,'
        f'crop=1080:1920[v{i}]'
        for i in range(n)
    ]
    concat_str = ''.join(f'[v{i}]' for i in range(n)) + f'concat=n={n}:v=1[v]'
    filter_str = ';'.join(scale_parts) + ';' + concat_str
    _run_ffmpeg([
        'ffmpeg', *inputs,
        '-filter_complex', filter_str,
        '-map', '[v]',
        '-c:v', 'libx264', '-an',
        '-y', out,
    ])
    return out


_whisper_model = None

def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        try:
            _whisper_model = WhisperModel('medium', device='cuda', compute_type='float32')
        except Exception:
            _whisper_model = WhisperModel('medium', device='cpu', compute_type='int8')
    return _whisper_model


def _generate_subtitles(voice_path: str, ass_path: str,
                        srt_path: str, scenes: list,
                        tpl_key: str = 'namnam',
                        positions: dict = None,
                        styles: dict = None) -> list:
    model = _get_whisper_model()
    segments, _info = model.transcribe(
        voice_path, language='ko',
        vad_filter=True,
        vad_parameters={'min_silence_duration_ms': 300},
    )
    seg_list = list(segments)

    blocks = _split_segments(seg_list)
    _apply_highlights(blocks, scenes)
    build_ass_file(blocks, ass_path, tpl_key, positions=positions, styles=styles)
    _write_srt(blocks, srt_path)
    return seg_list


def _split_segments(segments: list) -> list:
    blocks = []
    PUNCT = set('。.!?，,！？')

    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue

        if len(text) <= MAX_SUBTITLE_CHARS:
            blocks.append({'start': seg.start, 'end': seg.end,
                           'text': text, 'highlight': None})
            continue

        parts = _split_by_punct(text, PUNCT)
        seg_dur = seg.end - seg.start
        total_chars = len(text) or 1
        cursor_start = seg.start

        for j, part in enumerate(parts):
            part_dur = (len(part) / total_chars) * seg_dur
            part_end = cursor_start + part_dur
            blocks.append({'start': cursor_start, 'end': part_end,
                           'text': part, 'highlight': None})
            cursor_start = part_end

        if blocks:
            blocks[-1]['end'] = seg.end

    return blocks


def _split_by_punct(text: str, punct: set) -> list:
    parts = []
    buf = ''

    for ch in text:
        buf += ch
        if ch in punct and buf.strip():
            parts.append(buf.strip())
            buf = ''
        elif len(buf) >= MAX_SUBTITLE_CHARS:
            parts.append(buf.strip())
            buf = ''

    if buf.strip():
        parts.append(buf.strip())

    return [p for p in parts if p]


def _apply_highlights(blocks: list, scenes: list) -> None:
    all_highlights = []
    for scene in scenes:
        for hw in scene.get('highlight_words', []):
            if hw:
                all_highlights.append(hw)

    for block in blocks:
        for hw in all_highlights:
            if hw in block['text']:
                block['highlight'] = hw
                break


def _write_srt(blocks: list, srt_path: str) -> None:
    def sec_to_srt(s: float) -> str:
        h  = int(s // 3600)
        m  = int((s % 3600) // 60)
        sc = int(s % 60)
        ms = int((s % 1) * 1000)
        return f"{h:02d}:{m:02d}:{sc:02d},{ms:03d}"

    with open(srt_path, 'w', encoding='utf-8') as f:
        for i, block in enumerate(blocks, 1):
            f.write(f"{i}\n")
            f.write(f"{sec_to_srt(block['start'])} --> {sec_to_srt(block['end'])}\n")
            f.write(f"{block['text']}\n\n")


def _build_namnam_bg(bg_paths, duration: float,
                     tpl_key: str, tmp: str, out_path: str,
                     positions: dict = None) -> None:
    """단색 배경(#111) + 영상을 배너 아래(y=240)에 삽입"""
    tpl     = get_template(tpl_key)
    pos     = positions or {}
    video_y = pos.get('video_y', tpl.get('video_y', 240))
    r, g, b = tpl.get('bg_color', (17, 17, 17))
    bg_hex  = f'#{r:02x}{g:02x}{b:02x}'

    raw = bg_paths[0] if isinstance(bg_paths, list) else bg_paths

    scaled = os.path.join(tmp, 'nm_vid.mp4')
    _run_ffmpeg([
        'ffmpeg', '-stream_loop', '-1', '-i', raw,
        '-t', str(duration),
        '-vf', 'scale=1080:-2',
        '-r', '30', '-c:v', 'libx264', '-an',
        '-y', scaled,
    ])

    _run_ffmpeg([
        'ffmpeg',
        '-f', 'lavfi', '-i', f'color=c={bg_hex}:s=1080x1920:r=30',
        '-i', scaled,
        '-filter_complex',
        f'[0:v][1:v]overlay=0:{video_y}:shortest=1[v]',
        '-map', '[v]',
        '-t', str(duration),
        '-r', '30', '-c:v', 'libx264', '-an',
        '-y', out_path,
    ])


def _build_silver_crown_bg(bg_paths, duration: float,
                           tpl_key: str, tmp: str, out_path: str,
                           positions: dict = None) -> None:
    """PNG 배경 + 영상을 video_y에 삽입해 1080×1920 영상 생성"""
    tpl     = get_template(tpl_key)
    pos     = positions or {}
    bg_png  = tpl['bg_png']
    video_y = pos.get('video_y', tpl['video_y'])

    raw = bg_paths[0] if isinstance(bg_paths, list) else bg_paths

    # 영상을 가로 1080px로 스케일 (세로 비율 유지, 짝수 보정)
    scaled = os.path.join(tmp, 'sc_vid.mp4')
    _run_ffmpeg([
        'ffmpeg', '-stream_loop', '-1', '-i', raw,
        '-t', str(duration),
        '-vf', 'scale=1080:-2',
        '-r', '30', '-c:v', 'libx264', '-an',
        '-y', scaled,
    ])

    # PNG 배경(루프) + 스케일된 영상 overlay
    _run_ffmpeg([
        'ffmpeg',
        '-loop', '1', '-i', bg_png,
        '-i', scaled,
        '-filter_complex',
        f'[0:v]scale=1080:1920[bg];[bg][1:v]overlay=0:{video_y}:shortest=1[v]',
        '-map', '[v]',
        '-t', str(duration),
        '-r', '30', '-c:v', 'libx264', '-an',
        '-y', out_path,
    ])


def _apply_template(subtitled: str, title: str, tpl_key: str, tmp: str, output_path: str,
                    positions: dict = None, styles: dict = None,
                    source_text: str = '', custom_layers: list = None) -> None:

    pos           = positions     or {}
    sty           = styles        or {}
    custom_layers = custom_layers or []

    if tpl_key == 'silver_crown':
        cur = subtitled

        if title:
            title_png = os.path.join(tmp, 'title.png')
            generate_title_overlay_png(title, title_png, 'silver_crown',
                                       positions=pos, styles=sty)
            with_title = os.path.join(tmp, 'with_title.mp4')
            _run_ffmpeg([
                'ffmpeg', '-i', cur, '-i', title_png,
                '-filter_complex', '[0:v][1:v]overlay=0:0',
                '-c:a', 'copy', '-y', with_title,
            ])
            cur = with_title

        source_png = os.path.join(tmp, 'source.png')
        generate_source_overlay_png(source_png, 'silver_crown',
                                    positions=pos, styles=sty,
                                    custom_text=source_text or None)
        next_path = os.path.join(tmp, 'after_source.mp4') if custom_layers else output_path
        _run_ffmpeg([
            'ffmpeg', '-i', cur, '-i', source_png,
            '-filter_complex', '[0:v][1:v]overlay=0:0',
            '-c:a', 'copy', '-y', next_path,
        ])
        cur = next_path

    else:  # namnam (기본)
        if title:
            banner_png = os.path.join(tmp, 'banner.png')
            generate_banner_png(title, banner_png, 'namnam', styles=sty)
            next_path = os.path.join(tmp, 'after_banner.mp4') if custom_layers else output_path
            _run_ffmpeg([
                'ffmpeg', '-i', subtitled, '-i', banner_png,
                '-filter_complex', '[0:v][1:v]overlay=0:0',
                '-c:a', 'copy', '-y', next_path,
            ])
            cur = next_path
        else:
            cur = subtitled
            if not custom_layers:
                shutil.copy2(subtitled, output_path)
                return

    # 커스텀 텍스트 레이어 오버레이 (N개 → 투명 PNG 1장)
    if custom_layers:
        cl_png = os.path.join(tmp, 'custom_layers.png')
        generate_custom_layers_png(custom_layers, cl_png)
        _run_ffmpeg([
            'ffmpeg', '-i', cur, '-i', cl_png,
            '-filter_complex', '[0:v][1:v]overlay=0:0',
            '-c:a', 'copy', '-y', output_path,
        ])


def _apply_irasutoya_overlays(video_path: str, overlay_specs: list,
                              total_duration: float, out_path: str) -> None:
    """각 spec의 anchor 텍스트 위치 비율로 삽입 시간을 추정해 PNG 오버레이 적용."""
    if not overlay_specs:
        shutil.copy2(video_path, out_path)
        return

    # anchor 텍스트를 모두 이어붙인 전체 텍스트 기준으로 비율 추정
    all_anchors = ' '.join(s.get('anchor', '') for s in overlay_specs)
    total_chars = max(len(all_anchors), 1)

    timed = []
    cursor = 0
    for spec in overlay_specs:
        anchor   = spec.get('anchor', '')
        img_path = spec.get('path', '')
        dur      = float(spec.get('duration', 3))
        if not img_path or not os.path.exists(img_path):
            cursor += len(anchor)
            continue
        cursor    += len(anchor)
        start_t    = (cursor / total_chars) * total_duration
        timed.append({'path': img_path, 'start': start_t, 'dur': dur})

    if not timed:
        shutil.copy2(video_path, out_path)
        return

    # ffmpeg filter_complex 구성
    inputs = ['-i', video_path]
    for t in timed:
        inputs += ['-i', t['path']]

    filter_parts = []
    prev = '0:v'
    for i, t in enumerate(timed):
        idx   = i + 1
        s, e  = t['start'], t['start'] + t['dur']
        scale = 'scale=400:-1'   # 이미지 너비 400px
        # 화면 하단 중앙, 배너 아래 약 300px
        x, y  = '(W-w)/2', '(H-h)*0.65'
        label = f'ov{i}'
        filter_parts.append(f'[{idx}:v]{scale}[img{i}]')
        filter_parts.append(
            f'[{prev}][img{i}]overlay={x}:{y}:'
            f"enable='between(t,{s:.2f},{e:.2f})'[{label}]"
        )
        prev = label

    _run_ffmpeg([
        'ffmpeg', *inputs,
        '-filter_complex', ';'.join(filter_parts),
        '-map', f'[{prev}]',
        '-map', '0:a',
        '-c:a', 'copy',
        '-y', out_path,
    ])


def _apply_text_overlays(input_path: str, text_overlays: list, output_path: str) -> None:
    """사용자가 추가한 텍스트 오브젝트를 ffmpeg drawtext로 영상에 합성한다."""
    if not text_overlays:
        shutil.copy2(input_path, output_path)
        return

    font_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', 'fonts', 'Pretendard-ExtraBold.otf')
    ).replace('\\', '/')

    filters = []
    for ov in text_overlays:
        text = (ov.get('text') or '').strip()
        if not text:
            continue
        # drawtext 특수문자 이스케이프
        text = text.replace('\\', '\\\\').replace("'", "\\'").replace(':', '\\:')
        x     = int(ov.get('x', 540))
        y     = int(ov.get('y', 960))
        size  = int(ov.get('font_size', 50))
        color = (ov.get('color') or 'ffffff').lstrip('#')
        filters.append(
            f"drawtext=fontfile='{font_path}':text='{text}'"
            f":x={x}-text_w/2:y={y}-text_h/2"
            f":fontsize={size}:fontcolor=#{color}"
            f":borderw=4:bordercolor=black"
        )

    if not filters:
        shutil.copy2(input_path, output_path)
        return

    _run_ffmpeg([
        'ffmpeg', '-i', input_path,
        '-vf', ','.join(filters),
        '-c:a', 'copy', '-y', output_path,
    ])


def _run_ffmpeg(cmd: list) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode != 0:
        err = result.stderr.strip().splitlines()[-10:]
        raise RuntimeError('\n'.join(err))
