import sys
import yt_dlp

def download(url: str, output_dir: str = ".") -> None:
    opts = {
        "outtmpl": f"{output_dir}/%(title)s.%(ext)s",
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "cookiesfrombrowser": ("chrome",),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 download.py <youtube_url> [output_dir]")
        sys.exit(1)
    url = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    download(url, out)
