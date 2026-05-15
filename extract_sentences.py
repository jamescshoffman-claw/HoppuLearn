import re
import subprocess
import sys
import os

SENTENCE_BREAK_THRESHOLD = 0.6  # seconds — pauses >= this are sentence boundaries


def detect_silences(video_path: str, duration_limit: float = 300) -> list[tuple[float, float]]:
    result = subprocess.run(
        [
            "ffmpeg", "-i", video_path,
            "-t", str(duration_limit),
            "-vn",
            "-af", "silencedetect=noise=-20dB:d=0.3",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    output = result.stderr
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", output)]
    ends   = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", output)]
    # pair them up; drop any trailing unpaired start
    return list(zip(starts, ends[:len(starts)]))


def silences_to_sentences(silences: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Convert silence list into (sentence_start, sentence_end) pairs."""
    sentences = []
    speech_start = None

    for s_start, s_end in silences:
        gap = s_end - s_start

        if speech_start is None:
            # First silence is the leading quiet before any speech
            speech_start = s_end
            continue

        if gap >= SENTENCE_BREAK_THRESHOLD:
            # This pause is long enough to mark a sentence boundary
            sentences.append((speech_start, s_start))
            speech_start = s_end

    return sentences


def extract_clip(video_path: str, start: float, end: float, out_path: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-i", video_path,
            "-ss", str(start),
            "-to", str(end),
            "-vn",
            "-acodec", "aac",
            "-b:a", "128k",
            out_path,
            "-y",
        ],
        capture_output=True,
        check=True,
    )


if __name__ == "__main__":
    video = sys.argv[1] if len(sys.argv) > 1 else (
        "downloads/[Korean Listening] Why it's hard to make friends in Korea 😭.mp4"
    )
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    out_dir = os.path.join(os.path.dirname(video) or ".", "sentences")
    os.makedirs(out_dir, exist_ok=True)

    print("Detecting silences...")
    silences = detect_silences(video)

    sentences = silences_to_sentences(silences)[:n]
    print(f"Found {len(sentences)} sentences, extracting {n}...\n")

    for i, (start, end) in enumerate(sentences, 1):
        out_path = os.path.join(out_dir, f"sentence_{i:02d}.m4a")
        extract_clip(video, start, end, out_path)
        print(f"  [{i:2d}] {start:6.2f}s → {end:6.2f}s  →  {out_path}")

    print("\nDone.")
