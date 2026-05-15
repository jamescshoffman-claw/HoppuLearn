import sys
import json
import subprocess
import tempfile
import os

def get_transcript(video_id: str, lang: str = "en") -> list[dict]:
    """
    Returns a list of dicts: [{"start": float, "duration": float, "text": str}, ...]
    Uses yt-dlp with Chrome cookies to bypass auth requirements.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [
                "yt-dlp",
                "--cookies-from-browser", "chrome",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs", lang,
                "--skip-download",
                "--sub-format", "json3",
                "-o", os.path.join(tmpdir, "%(id)s.%(ext)s"),
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True,
            text=True,
        )

        sub_file = os.path.join(tmpdir, f"{video_id}.{lang}.json3")
        if not os.path.exists(sub_file):
            # Try auto-generated suffix
            sub_file = os.path.join(tmpdir, f"{video_id}.{lang}-orig.json3")
        if not os.path.exists(sub_file):
            raise FileNotFoundError(
                f"No subtitle file found for lang '{lang}'.\n"
                f"yt-dlp stderr:\n{result.stderr}"
            )

        with open(sub_file) as f:
            data = json.load(f)

    segments = []
    for event in data.get("events", []):
        segs = event.get("segs", [])
        text = "".join(s.get("utf8", "") for s in segs).strip()
        if text and text != "\n":
            segments.append({
                "start": event["tStartMs"] / 1000,
                "duration": event.get("dDurationMs", 0) / 1000,
                "text": text,
            })
    return segments


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 transcript.py <video_id_or_url> [lang]")
        print("  lang defaults to 'en'")
        sys.exit(1)

    video_id = sys.argv[1]
    if "watch?v=" in video_id:
        video_id = video_id.split("watch?v=")[1].split("&")[0]

    lang = sys.argv[2] if len(sys.argv) > 2 else "en"
    segments = get_transcript(video_id, lang)

    for seg in segments:
        print(f"[{seg['start']:.1f}s] {seg['text']}")
