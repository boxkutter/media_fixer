# The Media Fixer (mf)

A Python tool to **fix and transcode media files** in your library with support for:
- 📂 Preserving folder structure  
- 🎞 Video & audio transcoding (with quality control via CRF)  
- 🌍 Optional removal of non-English streams  
- 📝 Subtitle handling (conversion & stripping)  
- ⚡ Parallel processing for speed  
- 🛡 Safe temporary files (`_tmp_` prefix) to avoid overwrites  
- 🛠 Detailed error logging  

---

## Features
- Automatically detects media streams (video, audio, subtitles) using `ffprobe`.
- Supports container conversion (MP4, MKV, AVI, etc.).
- Removes or strips non-English audio and subtitles.
- Can **replace originals** or create new output files.
- Runs multiple transcodes concurrently with progress bars (if [`tqdm`](https://github.com/tqdm/tqdm) is installed).
- Produces error logs (`transcode-errors.log`) for failed conversions.

---

## Requirements
- Python **3.8+**
- [`ffmpeg`](https://ffmpeg.org/download.html) (must be in `$PATH`)
- [`ffprobe`](https://ffmpeg.org/download.html) (comes with ffmpeg)
- (optional) [`tqdm`](https://pypi.org/project/tqdm/) for progress bars  

Install Python dependencies:
```bash
pip install tqdm
Installation
Clone this repo and make the script executable:

bash
Copy
Edit
git clone https://github.com/yourname/media-fixer.git
cd media-fixer
chmod +x mediafix.py
Usage
Run against a single file:

bash
Copy
Edit
./mediafix.py -f "Movies/Inception.mkv" -v libx265 -a aac -q 23 --replace
Run against a directory (recursive):

bash
Copy
Edit
./mediafix.py -d "Shows/" -c mp4 -q 20 --strip --replace
Dry-run (show what would happen, no transcoding):

bash
Copy
Edit
./mediafix.py -d "Movies/" --dry-run
Probe file streams (no transcoding):

bash
Copy
Edit
./mediafix.py -f "Episode.mkv" --probe
Options
Option	Description
-f, --file	Single media file to transcode
-d, --dir	Directory to scan (recursive)
-o, --output	Output directory (default: alongside input)
-c, --container	Target container format (mp4, mkv, etc.)
-v, --video-codec	Video codec (copy, libx264, libx265, etc.)
-a, --audio-codec	Audio codec (copy, aac, ac3, etc.)
-s, --subtitle-codec	Subtitle codec (copy, srt, mov_text)
-q, --quality	CRF quality (lower = better quality, larger file). Default: 0 (copy). Recommended: 20 (high), 23 (default), 28 (smaller)
-e, --remove-non-english	Remove non-English subtitles only
--strip	Remove non-English audio and subtitles
--replace	Replace input file (safe: uses _tmp_ prefix until success)
--probe	Print stream info only (no transcoding)
--workers	Number of concurrent jobs (default: 4)
--logfile	Error log file (default: transcode-errors.log)
--quiet	Disable progress output
--dry-run	Show actions but don’t transcode

Examples
Convert MKV to MP4 with H.265 and AAC:
bash
Copy
Edit
./mediafix.py -f "movie.mkv" -c mp4 -v libx265 -a aac -q 23
Strip all non-English audio & subtitles, keep container:
bash
Copy
Edit
./mediafix.py -d "Shows/" --strip --replace
Re-encode only video, keep original audio/subs:
bash
Copy
Edit
./mediafix.py -f "clip.avi" -v libx264 -a copy -s copy
Convert a whole library, preserving folder structure:
bash
Copy
Edit
./mediafix.py -d "MediaLibrary/" -c mp4 -v libx265 -a aac --replace
Notes
Temp files are prefixed with _tmp_ to avoid overwriting. They are renamed after success.

If --replace is not specified, new files will be created alongside originals.

If transcoding fails, originals are never deleted.

Errors are logged to transcode-errors.log.

Quality Control (-q option)

You can use the -q option to reduce large video files to smaller but good-quality outputs.
This option maps to ffmpeg's CRF (Constant Rate Factor) setting.

Lower values = higher quality (and larger file size).

Higher values = smaller files (but more quality loss).

Typical range: 18–28.

18–20 → Near lossless, very high quality

21–23 → Good balance of quality and size

24–28 → Smallest size, noticeable quality loss

Example:

python videoprocessor.py input.mkv -q 23

Recommended Codec + CRF Presets

Here are some common setups you can use with the -q option:

Codec	Example Command	When to Use
libx264	-v libx264 -q 20	Best for compatibility (works everywhere).
libx265	-v libx265 -q 23	Best for small file sizes, but slower to encode.
libvpx-vp9	-v libvpx-vp9 -q 30	Open-source, good quality, smaller than H.264.
libaom-av1	-v libaom-av1 -q 28	Cutting-edge, best compression, but very slow.

👉 Tip: If unsure, use H.264 (libx264 -q 20) for compatibility or H.265 (libx265 -q 23) for smaller files.


License
MIT License © 2025 B0xKutter