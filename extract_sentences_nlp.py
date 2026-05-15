import sys
import os
import re
import json
import subprocess
import whisper
from deep_translator import GoogleTranslator

# Merge consecutive Whisper segments if the gap between them is shorter
# than this — prevents splitting one thought across multiple clips.
MERGE_GAP_THRESHOLD = 0.6  # seconds
END_PADDING = 0.35         # seconds added after the last word so it doesn't cut off

SENTENCE_END = re.compile(r'[.!?。！？]\s*$')


def extract_audio(video_path: str, audio_path: str) -> None:
    subprocess.run(
        ["ffmpeg", "-i", video_path, "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1", audio_path, "-y"],
        capture_output=True, check=True,
    )


def transcribe(audio_path: str) -> list[dict]:
    print("Loading Whisper model (small)...")
    model = whisper.load_model("small")
    print("Transcribing...")
    result = model.transcribe(audio_path, word_timestamps=True, language="ko")
    return result["segments"]


def merge_segments(segments: list[dict]) -> list[dict]:
    """
    Merge consecutive Whisper segments whose gap is below MERGE_GAP_THRESHOLD.
    Preserves word-level timestamps so split_multisent can use them later.
    """
    if not segments:
        return []

    merged = []
    current = dict(segments[0])
    current["words"] = list(segments[0].get("words", []))

    for seg in segments[1:]:
        gap = seg["start"] - current["end"]
        if gap < MERGE_GAP_THRESHOLD:
            current["text"] = current["text"].rstrip() + " " + seg["text"].lstrip()
            current["end"] = seg["end"]
            current["words"].extend(seg.get("words", []))
        else:
            merged.append(current)
            current = dict(seg)
            current["words"] = list(seg.get("words", []))

    merged.append(current)
    return merged


def split_multisent(seg: dict) -> list[dict]:
    """
    If a merged segment contains multiple sentences (detected by sentence-ending
    punctuation), split it into separate segments using word-level timestamps.
    Returns a list of one or more segments.
    """
    words = seg.get("words", [])
    if not words:
        return [seg]

    groups: list[list[dict]] = []
    current: list[dict] = []

    for w in words:
        current.append(w)
        if SENTENCE_END.search(w["word"].strip()):
            groups.append(current)
            current = []

    if current:
        groups.append(current)

    # Only split if we found more than one sentence boundary
    if len(groups) <= 1:
        return [seg]

    result = []
    for group in groups:
        text = "".join(w["word"] for w in group).strip()
        if text:
            result.append({
                "text": text,
                "start": group[0]["start"],
                "end": group[-1]["end"],
                "words": group,
            })

    return result if len(result) > 1 else [seg]


def extract_clip(video_path: str, start: float, end: float, out_path: str) -> None:
    subprocess.run(
        ["ffmpeg", "-i", video_path, "-ss", str(start), "-to", str(end),
         "-vn", "-acodec", "aac", "-b:a", "128k", out_path, "-y"],
        capture_output=True, check=True,
    )


if __name__ == "__main__":
    video = sys.argv[1] if len(sys.argv) > 1 else (
        "downloads/[Korean Listening] Why it's hard to make friends in Korea 😭.mp4"
    )
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    out_dir = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(video) or ".", "sentences_nlp")
    difficulty = sys.argv[4] if len(sys.argv) > 4 else None
    os.makedirs(out_dir, exist_ok=True)

    audio_path = "/tmp/comprehendo_audio.wav"
    print("Extracting audio...")
    extract_audio(video, audio_path)

    segments = transcribe(audio_path)
    merged = merge_segments(segments)

    # Re-split any merged segment that contains multiple sentences
    sentences = [sub for seg in merged for sub in split_multisent(seg)]
    print(f"\nDetected {len(merged)} merged segments → {len(sentences)} after sentence split, extracting first {n}:\n")

    translator = GoogleTranslator(source="ko", target="en")

    records = []
    for i, sent in enumerate(sentences[:n], 1):
        filename = f"sentence_{i:02d}.m4a"
        out_path = os.path.join(out_dir, filename)
        extract_clip(video, sent["start"], sent["end"] + END_PADDING, out_path)
        korean = sent["text"].strip()
        english = translator.translate(korean)
        print(f"  [{i:2d}] {sent['start']:6.2f}s → {sent['end']:6.2f}s  |  {korean}")
        print(f"        {english}")
        records.append({
            "id": i,
            "korean": korean,
            "english": english,
            "audio_file": filename,
            "start": round(sent["start"], 3),
            "end": round(sent["end"], 3),
            "duration": round(sent["end"] - sent["start"], 3),
        })

    index_path = os.path.join(out_dir, "sentences.json")
    payload = {"sentence_count": len(records), "sentences": records}
    if difficulty:
        payload["difficulty"] = difficulty
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nSubtitle index written to {index_path}")
    print("\nDone.")
