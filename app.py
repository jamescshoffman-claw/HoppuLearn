import json
import os
import re
import shutil
import subprocess
import tempfile
import html as html_module
from pathlib import Path

import whisper as _whisper
from flask import Flask, render_template, jsonify, request, send_from_directory

app = Flask(__name__)

DATA_DIR = Path(__file__).parent / 'data'
DATA_DIR.mkdir(exist_ok=True)

DOWNLOADS_DIR = Path(__file__).parent / 'downloads'

YTDLP = shutil.which('yt-dlp') or '/opt/homebrew/bin/yt-dlp'

MERGE_GAP = 0.6   # seconds — gaps smaller than this are within one sentence
END_PAD   = 0.35  # seconds added after last word so clips don't cut off

_whisper_model = None


# ─── Utilities ────────────────────────────────────────────────────────────────

def extract_video_id(url_or_id):
    match = re.search(r'(?:v=|youtu\.be/|embed/)([a-zA-Z0-9_-]{11})', url_or_id)
    if match:
        return match.group(1)
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url_or_id.strip()):
        return url_or_id.strip()
    return None


def clean_text(text):
    text = html_module.unescape(text)
    text = text.replace('\n', ' ')
    return re.sub(r'\s+', ' ', text).strip()


# ─── yt-dlp subtitle fetching ─────────────────────────────────────────────────

def fetch_subs_with_ytdlp(video_id):
    """Download Korean + English subtitles via yt-dlp with Chrome cookies.
    Returns (ko_vtt_path, en_vtt_path) — either may be None if unavailable."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            YTDLP,
            '--cookies-from-browser', 'chrome',
            '--write-sub',        # manually created subs
            '--write-auto-sub',   # auto-generated subs
            '--sub-lang', 'ko,en',
            '--skip-download',
            '--sub-format', 'vtt',
            '-o', os.path.join(tmpdir, '%(id)s'),
            f'https://www.youtube.com/watch?v={video_id}',
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        ko_path = en_path = None
        for fname in os.listdir(tmpdir):
            full = os.path.join(tmpdir, fname)
            if fname.endswith('.ko.vtt') or fname.endswith('.ko-orig.vtt'):
                ko_path = full
            elif fname.endswith('.en.vtt') or fname.endswith('.en-orig.vtt'):
                en_path = full

        ko_data = open(ko_path).read() if ko_path else None
        en_data = open(en_path).read() if en_path else None

    return ko_data, en_data, result.stderr


def parse_vtt(vtt_text):
    """Parse WebVTT into list of {text, start, duration} dicts."""
    if not vtt_text:
        return []
    segs = []
    lines = vtt_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Look for timestamp lines like "00:00:00.320 --> 00:00:06.080"
        m = re.match(
            r'(\d+):(\d+):(\d+)[.,](\d+)\s+-->\s+(\d+):(\d+):(\d+)[.,](\d+)',
            line
        )
        if m:
            def to_sec(h, m, s, ms):
                return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000
            start = to_sec(m.group(1), m.group(2), m.group(3), m.group(4))
            end = to_sec(m.group(5), m.group(6), m.group(7), m.group(8))
            duration = end - start
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip():
                raw = lines[i].strip()
                # Remove VTT positioning tags like <00:00:00.000><c>...</c>
                raw = re.sub(r'<[^>]+>', '', raw)
                raw = clean_text(raw)
                if raw:
                    text_lines.append(raw)
                i += 1
            text = ' '.join(text_lines)
            if text and duration > 0:
                segs.append({'text': text, 'start': start, 'duration': duration})
        else:
            i += 1
    return segs


def build_sentences_from_english(en_segs, ko_segs):
    """Use English sentence boundaries; collect Korean text by timestamp overlap."""
    sentences = []
    for i, en in enumerate(en_segs):
        en_end = en['start'] + en['duration']
        window_start = en['start'] - 0.6
        window_end = en_end + 0.6
        ko_words = [
            k['text'] for k in ko_segs
            if window_start <= (k['start'] + k['duration'] / 2) < window_end and k['text']
        ]
        sentences.append({
            'id': i,
            'korean': ' '.join(ko_words),
            'english': en['text'],
            'start': en['start'],
            'duration': en['duration'],
        })
    has_korean = [s for s in sentences if s['korean']]
    return has_korean if has_korean else sentences


def merge_segments(segs, gap_threshold=1.0):
    """Merge short auto-generated segments into sentences."""
    if not segs:
        return []
    result, cur = [], dict(segs[0])
    for s in segs[1:]:
        gap = s['start'] - (cur['start'] + cur['duration'])
        if gap <= gap_threshold:
            cur['text'] = (cur['text'] + ' ' + s['text']).strip()
            cur['duration'] = (s['start'] + s['duration']) - cur['start']
        else:
            if cur['text']:
                result.append(cur)
            cur = dict(s)
    if cur['text']:
        result.append(cur)
    return result


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/sessions')
def list_sessions():
    sessions = []
    for d in DATA_DIR.iterdir():
        cache = d / 'sentences.json'
        if cache.exists():
            data = json.loads(cache.read_text())
            sessions.append({
                'video_id': d.name,
                'sentence_count': data.get('sentence_count', len(data.get('sentences', []))),
            })
    return jsonify({'sessions': sessions})


@app.route('/api/transcript', methods=['POST'])
def get_transcript():
    data = request.get_json()
    url = (data or {}).get('url', '').strip()
    video_id = extract_video_id(url)

    if not video_id:
        return jsonify({'error': 'Could not extract a video ID from the URL.'}), 400

    # Check disk cache first
    cache_file = DATA_DIR / f'{video_id}.json'
    if cache_file.exists():
        sentences = json.loads(cache_file.read_text())
        return jsonify({'video_id': video_id, 'sentence_count': len(sentences), 'sentences': sentences})

    # Download subtitles via yt-dlp
    try:
        ko_vtt, en_vtt, stderr = fetch_subs_with_ytdlp(video_id)
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Timed out downloading subtitles.'}), 504
    except Exception as e:
        return jsonify({'error': f'Failed to run yt-dlp: {e}'}), 500

    if not ko_vtt:
        # Check if it's a rate-limit or error
        if '429' in stderr or 'Too Many Requests' in stderr:
            return jsonify({'error': 'YouTube is rate-limiting requests. Try again in a few minutes.'}), 429
        return jsonify({'error': 'No Korean subtitles found for this video.'}), 404

    ko_segs = parse_vtt(ko_vtt)
    en_segs = parse_vtt(en_vtt) if en_vtt else []

    if not ko_segs:
        return jsonify({'error': 'Korean subtitles were empty or could not be parsed.'}), 404

    if en_segs:
        sentences = build_sentences_from_english(en_segs, ko_segs)
    else:
        ko_merged = merge_segments(ko_segs)
        sentences = [
            {'id': i, 'korean': s['text'], 'english': '', 'start': s['start'], 'duration': s['duration']}
            for i, s in enumerate(ko_merged) if s['text']
        ]

    # Cache to disk
    cache_file.write_text(json.dumps(sentences, ensure_ascii=False))

    return jsonify({'video_id': video_id, 'sentence_count': len(sentences), 'sentences': sentences})


# ─── Whisper pipeline helpers ─────────────────────────────────────────────────

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = _whisper.load_model('base')
    return _whisper_model


def download_video(video_id: str, out_path: str) -> None:
    subprocess.run(
        [
            YTDLP,
            '--cookies-from-browser', 'chrome',
            '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            '--merge-output-format', 'mp4',
            '-o', out_path,
            f'https://www.youtube.com/watch?v={video_id}',
        ],
        check=True,
        capture_output=True,
    )


def extract_wav(video_path: str, wav_path: str) -> None:
    subprocess.run(
        ['ffmpeg', '-i', video_path, '-vn', '-acodec', 'pcm_s16le',
         '-ar', '16000', '-ac', '1', wav_path, '-y'],
        capture_output=True, check=True,
    )


def transcribe_audio(wav_path: str) -> list:
    model = get_whisper_model()
    result = model.transcribe(wav_path, word_timestamps=True, language='ko')
    return result['segments']


def merge_whisper_segments(segments: list) -> list:
    if not segments:
        return []
    merged = []
    current = dict(segments[0])
    for seg in segments[1:]:
        gap = seg['start'] - current['end']
        if gap < MERGE_GAP:
            current['text'] = current['text'].rstrip() + ' ' + seg['text'].lstrip()
            current['end'] = seg['end']
        else:
            merged.append(current)
            current = dict(seg)
    merged.append(current)
    return merged


def match_english_to_segment(start: float, end: float, en_segs: list) -> str:
    seen, texts = set(), []
    for seg in en_segs:
        seg_end = seg['start'] + seg['duration']
        if seg['start'] < end + 0.3 and seg_end > start - 0.3:
            t = seg['text'].strip()
            if t and t not in seen:
                texts.append(t)
                seen.add(t)
    return ' '.join(texts)


def extract_audio_clip(video_path: str, start: float, end: float, out_path: str) -> None:
    subprocess.run(
        ['ffmpeg', '-i', video_path,
         '-ss', str(start), '-to', str(end + END_PAD),
         '-vn', '-acodec', 'aac', '-b:a', '128k', out_path, '-y'],
        capture_output=True, check=True,
    )


# ─── Process route (download + transcribe + extract clips) ────────────────────

@app.route('/api/process', methods=['POST'])
def process_video():
    data = request.get_json()
    url = (data or {}).get('url', '').strip()
    video_id = extract_video_id(url)

    if not video_id:
        return jsonify({'error': 'Could not extract a video ID from the URL.'}), 400

    video_dir = DATA_DIR / video_id
    cache_file = video_dir / 'sentences.json'

    if cache_file.exists():
        return jsonify(json.loads(cache_file.read_text()))

    video_dir.mkdir(exist_ok=True)

    # 1. Download video
    video_path = str(video_dir / 'video.mp4')
    if not Path(video_path).exists():
        try:
            download_video(video_id, video_path)
        except subprocess.CalledProcessError as e:
            return jsonify({'error': 'Failed to download video. Check yt-dlp and Chrome cookies.'}), 500

    # 2. Fetch English subtitles (best-effort)
    try:
        _, en_vtt, _ = fetch_subs_with_ytdlp(video_id)
        en_segs = parse_vtt(en_vtt) if en_vtt else []
    except Exception:
        en_segs = []

    # 3. Whisper transcription
    wav_path = str(video_dir / 'audio.wav')
    extract_wav(video_path, wav_path)
    raw_segments = transcribe_audio(wav_path)
    merged = merge_whisper_segments(raw_segments)

    # 4. Extract audio clips + build sentence list
    clips_dir = video_dir / 'sentences'
    clips_dir.mkdir(exist_ok=True)

    sentences = []
    for i, seg in enumerate(merged, 1):
        clip_name = f'sentence_{i:02d}.m4a'
        clip_path = str(clips_dir / clip_name)
        extract_audio_clip(video_path, seg['start'], seg['end'], clip_path)
        english = match_english_to_segment(seg['start'], seg['end'], en_segs)
        sentences.append({
            'id': i,
            'korean': seg['text'].strip(),
            'english': english,
            'audio_url': f'/audio/{video_id}/{clip_name}',
            'start': seg['start'],
            'end': seg['end'],
            'duration': seg['end'] - seg['start'],
        })

    result = {'video_id': video_id, 'sentence_count': len(sentences), 'sentences': sentences}
    cache_file.write_text(json.dumps(result, ensure_ascii=False))
    return jsonify(result)


@app.route('/audio/<video_id>/<filename>')
def serve_audio(video_id, filename):
    audio_dir = DATA_DIR / video_id / 'sentences'
    return send_from_directory(str(audio_dir), filename)


# ─── Local pre-processed datasets ─────────────────────────────────────────────

@app.route('/api/local-sets')
def list_local_sets():
    sets = []
    if DOWNLOADS_DIR.exists():
        for d in sorted(DOWNLOADS_DIR.iterdir()):
            if not d.is_dir():
                continue
            cache = d / 'sentences.json'
            if not cache.exists():
                continue
            data = json.loads(cache.read_text(encoding='utf-8'))
            sentences = data.get('sentences', data) if isinstance(data, dict) else data
            sets.append({
                'name': d.name,
                'sentence_count': len(sentences),
                'difficulty': data.get('difficulty') if isinstance(data, dict) else None,
            })
    return jsonify({'sets': sets})


@app.route('/api/local-sets/<name>/sentences')
def get_local_set(name):
    set_dir = DOWNLOADS_DIR / name
    cache = set_dir / 'sentences.json'
    if not cache.exists():
        return jsonify({'error': 'Dataset not found.'}), 404
    data = json.loads(cache.read_text(encoding='utf-8'))
    sentences = data.get('sentences', data) if isinstance(data, dict) else data
    for s in sentences:
        if 'audio_file' in s and 'audio_url' not in s:
            s['audio_url'] = f'/audio/local/{name}/{s["audio_file"]}'
    return jsonify({'name': name, 'sentence_count': len(sentences), 'sentences': sentences})


@app.route('/audio/local/<name>/<filename>')
def serve_local_audio(name, filename):
    return send_from_directory(str(DOWNLOADS_DIR / name), filename)


if __name__ == '__main__':
    app.run(debug=True, port=5001)
