# 🎬 Media Fixer

A Python-based media transcoder and fixer built on top of **FFmpeg**.  
Supports video, audio, and subtitle processing with GPU acceleration (NVENC), stream filtering, parallel transcoding, and safe temporary file handling.  

---

## ✨ Features
- 🔍 **Media discovery** using `ffprobe`
- ⚡ **Parallel transcoding** with configurable worker count
- 🎥 **Video codec control** (H.264, H.265, AV1, etc.)
- 🔊 **Audio codec control** + channel conversion (stereo/5.1)
- 💬 **Subtitle support** (convert between formats, drop unsupported)
- 🌍 **Language filtering** (keep only desired audio/subs with `--strip`)
- 📦 **Container conversion** (e.g., MKV → MP4 → WebM)
- 🖥 **GPU acceleration** (NVIDIA NVENC) with automatic CPU fallback
- 🛡 **Safe temp files** with `_tmp_` prefix
- 📂 **Preserves folder structure**
- 📝 **Error logging** with `mf-errors.log`

---
## Getting Started
curl -L https://raw.githubusercontent.com/YourUserName/YourRepo/main/media_fixer.py -o media_fixer.py && chmod +x media_fixer.py
python3 media_fixer.py --help

## 📦 Requirements
- [Python 3.8+](https://www.python.org/)
- [FFmpeg](https://ffmpeg.org/) with `ffprobe`
- Optional:
  - [tqdm](https://github.com/tqdm/tqdm) for progress bars  
  - NVIDIA GPU + CUDA-enabled FFmpeg build for hardware acceleration

Install tqdm:
```bash
pip install tqdm
🚀 Usage
bash
Copy
Edit
python mf.py [options]
Main Options
-f, --file <path> : Single media file to process

-d, --dir <path> : Directory to scan recursively

-o, --output <path> : Alternative output directory

-c, --container <ext> : Target container (mp4, mkv, webm, …)

-v, --video-codec <codec> : Target video codec (default: copy)

-a, --audio-codec <codec> : Target audio codec (default: copy)

-ch, --audio-channels 2|6 : Force stereo (2) or 5.1 (6)

-s, --subtitle-codec <codec> : Subtitle codec (copy, srt, mov_text, …)

-q, --quality <int> : CRF/Quality (18–28 for x264/x265, 0 = lossless)

Language Filtering
--strip : Keep only specified audio/subs language

--audio-lang <iso> : Target audio language (default: eng)

--subs-lang <iso> : Target subtitle language (default: eng)

Control & Debug
--probe : Show file info only (no transcoding)

--workers <n> : Number of concurrent workers (default: 4)

--dry-run : Show what would happen, no changes made

--no-replace : Do not overwrite source files (keep both)

--quiet : Suppress progress bars

--debug : Print extra debug info

--logfile <file> : Error log file (default: mf-errors.log)

🔧 Examples
Convert MKV to MP4 while keeping only English audio + subtitles
bash
Copy
Edit
python mf.py -f "movie.mkv" -c mp4 --strip --audio-lang eng --subs-lang eng
Transcode entire folder to H.265 MKV with CRF 23
bash
Copy
Edit
python mf.py -d ./Media --container mkv --video-codec libx265 -q 23
Downmix to stereo and re-encode audio as AAC
bash
Copy
Edit
python mf.py -f video.mkv -a aac -ch 2
Probe file streams
bash
Copy
Edit
python mf.py -f movie.mkv --probe
⚡ GPU Acceleration
If an NVIDIA GPU is detected and your FFmpeg build supports CUDA:

H.264 → h264_nvenc

H.265/HEVC → hevc_nvenc

If GPU initialization fails, the script automatically falls back to CPU (libx264/libx265).

📝 Error Handling
Errors are logged to mf-errors.log (configurable with --logfile)

Temporary files are prefixed with _tmp_

Original files are preserved unless explicitly replaced

📄 License
MIT License. Use at your own risk.

🙌 Credits
FFmpeg

tqdm

Python standard library