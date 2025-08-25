#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Media file fixer with transcoder and subtitle support.

Features:
• Media discovery (video, audio, subtitles)
• Parallel transcoding
• Optional container change
• Optional removal of non‑English subtitles
• Error logging
• Preserves folder structure
• Safe temp files with "_tmp_" prefix
"""

import concurrent.futures
import json
import subprocess
import sys
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Callable

# Safe tqdm import
tqdm: Optional[Callable] = None
try:
    from tqdm import tqdm as _tqdm
    tqdm = _tqdm
except ImportError:
    tqdm = None


# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #
def detect_nvidia_gpu() -> bool:
    """Return True if an NVIDIA GPU is available for NVENC encoding."""
    return shutil.which("nvidia-smi") is not None

def ffmpeg_available() -> bool:
    return subprocess.call(
        ["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ) == 0


def ffprobe_available() -> bool:
    return subprocess.call(
        ["ffprobe", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ) == 0


def get_media_files(root: Path, extensions: List[str]) -> List[Path]:
    return [p for p in root.rglob("*") if p.suffix.lower() in extensions]


def get_media_file(file_name: str, extensions: List[str]) -> List[Path]:
    file_path = Path(file_name)
    exts = [ext.lower().lstrip(".") for ext in extensions]
    if file_path.is_file() and file_path.suffix.lower().lstrip(".") in exts:
        return [file_path]
    return []


def probe_streams(file_path: Path) -> List[Dict]:
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(file_path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
    except Exception:
        return []

    streams = []
    for s in data.get("streams", []):
        stream_info = {
            "index": s.get("index"),
            "codec_type": s.get("codec_type"),
            "codec_name": s.get("codec_name"),
        }
        if "tags" in s and "language" in s["tags"]:
            stream_info["language"] = s["tags"]["language"].lower()
        else:
            stream_info["language"] = "und" # undefined
        streams.append(stream_info)
    return streams


def build_ffmpeg_cmd(
    input_path: Path,
    output_path: Path,
    quality: int,
    video_codec: str,
    audio_codec: str,
    audio_channels: int,
    subtitle_codec: str,
    strip: bool,
    audio_lang: str,
    subs_lang: str,
    streams: List[Dict],
    use_gpu: bool = True,
    debug: bool = False,
) -> List[str]:
    cmd = ["ffmpeg", "-y"]

    # GPU detection
    gpu_available = detect_nvidia_gpu() and use_gpu
    hwaccel_added = False

    # Try GPU, fallback to CPU
    if gpu_available:
        try:
            test_cmd = ["ffmpeg", "-hide_banner", "-hwaccel", "cuda", "-f", "lavfi", "-i", "nullsrc", "-t", "0.1", "-f", "null", "-"]
            subprocess.run(test_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            cmd += ["-hwaccel", "cuda"]
            hwaccel_added = True
            if video_codec.lower() in ("libx264", "h264"):
                video_codec = "h264_nvenc"
            elif video_codec.lower() in ("libx265", "h265", "hevc"):
                video_codec = "hevc_nvenc"
            print("⚙️  NVIDIA GPU detected; using NVENC for encoding.")
        except subprocess.CalledProcessError:
            print("⚠️  GPU detected but FFmpeg CUDA init failed, falling back to CPU.")
            gpu_available = False
    
    
    cmd += ["-i", str(input_path)]

    src_ext = input_path.suffix.lower()
    trg_ext = output_path.suffix.lower()
    map_args = []
    subs_codecs_per_stream = {}
    audio_streams_to_keep = []

    for s in streams:
        stype = s["codec_type"]
        idx = s["index"]
        lang = s.get("language", "und").lower()
        src_codec = s.get("codec_name")

        # ✅ Skip unsupported stream types (data, attachment, etc.)
        if stype not in ("video", "audio", "subtitle"):
            if debug:
                print(f"Skipping unsupported stream #{idx} ({stype})")
            continue

        keep_stream = True

        # Strip unwanted languages
        if strip:
            if stype == "audio" and lang != audio_lang.lower():
                keep_stream = False
            if stype == "subtitle" and lang != subs_lang.lower():
                keep_stream = False

        # Container compatibility checks for subtitles
        if keep_stream and stype == "subtitle":
            if trg_ext == ".mp4" and src_codec in ("pgssub", "dvd_subtitle", "hdmv_pgs_subtitle"):
                keep_stream = False
            elif trg_ext == ".avi":
                keep_stream = False
            elif trg_ext == ".webm" and src_codec not in ("srt", "subrip", "ass", "ssa", "webvtt"):
                keep_stream = False

        if keep_stream:
            map_args.append(f"0:{idx}")

            if stype == "audio":
                audio_streams_to_keep.append(idx)

            if stype == "subtitle":
                final_sub_codec = subtitle_codec
                if trg_ext != src_ext:
                    if trg_ext == ".mkv":
                        final_sub_codec = "srt" if src_codec == "mov_text" else "copy"
                    elif trg_ext == ".mp4":
                        if src_codec in ("srt", "subrip", "ass", "ssa"):
                            final_sub_codec = "mov_text"
                        elif src_codec == "mov_text":
                            final_sub_codec = "copy"
                    elif trg_ext == ".webm":
                        if src_codec in ("srt", "subrip", "ass", "ssa"):
                            final_sub_codec = "webvtt"
                        elif src_codec == "webvtt":
                            final_sub_codec = "copy"
                subs_codecs_per_stream[idx] = final_sub_codec

    # Add mapping arguments
    for m in map_args:
        cmd += ["-map", m]

    # Set codecs
    cmd += ["-c:v", video_codec]

    if audio_codec != "copy":
        cmd += ["-c:a", audio_codec]

    for idx, sub_c in subs_codecs_per_stream.items():
        cmd += [f"-c:s:{list(subs_codecs_per_stream.keys()).index(idx)}", sub_c]


    # CRF for NVENC or x264/x265
    if quality and video_codec.lower() in ("h264_nvenc", "hevc_nvenc", "libx264", "libx265"):
        cmd += ["-cq", str(quality)] if "nvenc" in video_codec else ["-crf", str(quality)]

    # Audio channel conversion
    if audio_channels in (2, 6):
        cmd += ["-ac", str(audio_channels)]

    # Append output
    cmd.append(str(output_path))

    if debug:
        print(f"\nDEBUG: GPU available: {gpu_available}, hwaccel_added: {hwaccel_added}")
        print(f"DEBUG: FFmpeg command:\n{' '.join(cmd)}\n")

    return cmd


def transcode_file(
    in_path: Path,
    out_path: Path,
    quality: int,
    video_codec: str,
    audio_codec: str,
    audio_channels: int,
    subtitle_codec: str,
    strip: bool,
    audio_lang: str,
    subs_lang: str,
    error_log: List[str],
    debug: bool = False
) -> bool:
    streams = probe_streams(in_path)
    if not streams:
        error_log.append(f"❌ {in_path}: could not probe streams\n")
        return False

    # Build FFmpeg command
    cmd = build_ffmpeg_cmd(
        input_path=in_path,
        output_path=out_path,
        quality=quality,
        video_codec=video_codec,
        audio_codec=audio_codec,
        audio_channels=audio_channels,
        subtitle_codec=subtitle_codec,
        strip=strip,
        audio_lang=audio_lang,
        subs_lang=subs_lang,
        streams=streams,
        debug=debug
    )

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else "No stderr output"
        error_log.append(f"❌ {in_path}: ffmpeg failed\n{stderr}\n")
        return False


# --------------------------------------------------------------------------- #
# Main logic
# --------------------------------------------------------------------------- #
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Media Fixer file transcoder tool.")
    parser.add_argument("-f", "--file", type=Path, help="Single file to transcode.")
    parser.add_argument("-d", "--dir", type=Path, help="Root folder to scan.")
    parser.add_argument("-o", "--output", type=Path, help="Copy transcoded files to alternative directory.")
    parser.add_argument("-q", "--quality", type=int, default=0, help="Target quality (CRF) - 18-28 for h264/h265; 0 for lossless")
    parser.add_argument("-c", "--container", type=str, default="", help="Target container - e.g. mp4 mkv webm..).")
    parser.add_argument("-v", "--video-codec", type=str, default="copy", help="Target video codec - e.g. h264 h265 av1 hevc..")
    parser.add_argument("-a", "--audio-codec", type=str, default="copy", help="Target audio codec - e.g., aac alac ac3 mp3 opus..")
    parser.add_argument("-ch", "--audio-channels", type=int, default="0", help="Target audio channels - 2 or 6 (for 5.1)")
    parser.add_argument("-s", "--subtitle-codec", type=str, default="copy", help="Target subtitle codec - e.g. subrip srt pgsub mov_text..")
    parser.add_argument("--strip", action="store_true", help="Keep only specific language. Defaults to English")
    parser.add_argument("--audio-lang", type=str, default="eng", help="Target audio language. Use with --strip")
    parser.add_argument("--subs-lang", type=str, default="eng", help="Target subtitle. Use with --strip")
    parser.add_argument("--no-replace", action="store_true", help="Keeps source files when different container type.")
    parser.add_argument("--probe", action="store_true", help="Get file info only.")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent workers.")
    parser.add_argument("--logfile", type=Path, default=Path("mf-errors.log"), help="Error log file.")
    parser.add_argument("--dry-run", action="store_true", help="Do not transcode; only show what would happen.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output.")
    parser.add_argument("--debug", action="store_true", help="Print out some extra stuff.")

    args = parser.parse_args()

    if args.dir is None and args.file is None:
        sys.exit("❌ Must specify --file or --dir; or --help for details.")
    if args.dir and not args.dir.is_dir():
        sys.exit("❌ --dir must be a directory.")
    if args.file and not args.file.is_file():
        sys.exit("❌ --file must be a file.")

    media_exts = [".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm"]
    files: List[Path] = []
    if args.dir:
        files = get_media_files(args.dir, media_exts)
    elif args.file:
        files = get_media_file(args.file, media_exts)

    if not files:
        sys.exit("❌ No media files found.")

    # Probe mode
    if args.probe:
        for fp in files:
            info = probe_streams(fp)
            print(f"\nFile: {fp}")
            if not info:
                print("  ❌ Could not probe streams.")
                continue
            for s in info:
                lang = s.get("language", "und")
                if s["codec_type"] == "video":
                    print(f"  Stream {s['index']}: {s['codec_type']} - {s['codec_name']}")
                else:   
                    print(f"  Stream {s['index']}: {s['codec_type']} - {s['codec_name']} (lang: {lang})")
        sys.exit(0) 

    # Prepare output paths
    tfiles: List[Path] = []
    out_paths: List[Path] = []

    for fp in files:
        info = probe_streams(fp)
        container = fp.suffix.lstrip(".").lower()
        has_video = next((s for s in info if s["codec_type"] == "video"), None)
        has_audio = next((s for s in info if s["codec_type"] == "audio"), None)
        has_subtitles = next((s for s in info if s["codec_type"] == "subtitle"), None)

        # Reset to copy if same as file
        if has_video and args.video_codec.lower() == has_video["codec_name"].lower():
            args.video_codec = "copy"
        if has_audio and args.audio_codec.lower() == has_audio["codec_name"].lower():
            args.audio_codec = "copy"
        if has_subtitles and args.subtitle_codec.lower() == has_subtitles["codec_name"].lower():
            args.subtitle_codec = "copy"

        needs_transcode = False
        if args.video_codec != "copy" and has_video:
            needs_transcode = True
        if args.audio_codec != "copy" and has_audio:
            needs_transcode = True
        if args.subtitle_codec != "copy" and has_subtitles:
            needs_transcode = True
        if args.container and args.container.lower() != container:
            needs_transcode = True
        if args.quality > 0:
            needs_transcode = True
        if args.audio_channels > 0:
            needs_transcode = True
        if args.strip == True:
            needs_transcode = True

        if needs_transcode:
            tfiles.append(fp)
            # Build temp output path with _tmp_ prefix
            filename = fp.name
            tmp_filename = "_tmp_" + filename
            if args.output:
                rel = fp.relative_to(args.dir) if args.dir else Path(fp.name)
                out_fp = args.output / rel.parent / tmp_filename
            else:
                out_fp = fp.parent / tmp_filename
            if args.container:
                new_ext = args.container if args.container.startswith(".") else f".{args.container}"
                out_fp = out_fp.with_suffix(new_ext.lower())
            out_fp.parent.mkdir(parents=True, exist_ok=True)
            out_paths.append(out_fp)

    if args.dry_run:
        print(f"Dry run: {len(tfiles)} files would be transcoded.")
        sys.exit(0)
    if not tfiles:
        print("No files need transcoding. Exiting.")
        sys.exit(0)

    # Parallel transcoding
    worker_cnt = args.workers if args.workers > 0 else 1
    use_tqdm = tqdm is not None and not args.quiet
    loop_kwargs = {"desc": "Transcoding", "total": len(tfiles)}

    _tqdm_safe: Callable = tqdm if tqdm is not None else (lambda x, **kwargs: x)

    errors: List[str] = []
    success_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_cnt) as executor:
        futures = {}
        for in_fp, out_fp in zip(tfiles, out_paths):
            in_path = Path(in_fp)
            out_path = Path(out_fp)

            # Temp filename already prepended, ensure parent exists
            out_path.parent.mkdir(parents=True, exist_ok=True)

            futures[executor.submit(
                transcode_file,
                in_path=in_path,
                out_path=out_path,
                quality=args.quality,
                video_codec=args.video_codec,
                audio_codec=args.audio_codec,
                audio_channels=args.audio_channels,
                subtitle_codec=args.subtitle_codec,
                strip=args.strip,
                audio_lang=args.audio_lang,
                subs_lang=args.subs_lang,
                error_log=errors
            )] = (in_path, out_path)


        iterable = concurrent.futures.as_completed(futures)
        if use_tqdm:
            iterable = _tqdm_safe(iterable, **loop_kwargs)

        for fut in concurrent.futures.as_completed(futures):
            in_path, tmp_path = futures[fut]
            try:
                if not fut.result():
                    continue  # skip failed transcodes

                # Determine final output path
                clean_path = tmp_path.with_name(tmp_path.name.replace("_tmp_", "", 1))
                print(f"-> Transcoded file: {in_path} -> {clean_path}")

                if args.no_replace:
                    tmp_path.rename(clean_path)
                else:
                    if in_path.exists():
                        in_path.unlink()
                    tmp_path.rename(clean_path)

                success_count += 1

            except Exception as e:
                errors.append(f"{in_path}: {e}")

    print(f"\n✅ Transcoding complete: {success_count}/{len(tfiles)} succeeded.")

    if errors:
        err_file = args.logfile
        err_file.parent.mkdir(parents=True, exist_ok=True)
        err_file.write_text("\n".join(errors), encoding="utf-8")
        print(f"❌ Errors logged to: {err_file}")

    if success_count == 0:
        sys.exit("❌ All transcoding failed. See error log.")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    if not ffmpeg_available():
        sys.exit("❌ ffmpeg not found in PATH.")
    if not ffprobe_available():
        sys.exit("❌ ffprobe not found in PATH.")
    if tqdm is None:
        print("⚠ tqdm not installed – progress bars disabled.")
        print("   pip install tqdm")
    main()