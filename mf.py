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

import os
import concurrent.futures
import json
import subprocess
import sys
import shutil
import argparse
from pathlib import Path
from typing import List, Optional, Dict, Callable


_NVENC_FORMATS = None


# Safe tqdm import
tqdm: Optional[Callable] = None
try:
    from tqdm import tqdm as _tqdm
    tqdm = _tqdm
except ImportError:
    tqdm = None



# --------------------------------------------------------------------------- #
# VERSION NO
version = "0.1"
# --------------------------------------------------------------------------- #


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

def nvenc_supported_pix_fmts():
    """Detect and cache NVENC-supported pixel formats."""
    global _NVENC_FORMATS
    if _NVENC_FORMATS is not None:
        return _NVENC_FORMATS

    fmts = set()
    try:
        out = subprocess.check_output(
            ["ffmpeg", "-hide_banner", "-h", "encoder=hevc_nvenc"],
            text=True, stderr=subprocess.STDOUT
        )
        for line in out.splitlines():
            if "Supported pixel formats" in line:
                # Example: "Supported pixel formats: nv12 yuv420p p010le"
                fmts.update(line.split(":")[1].split())
    except Exception as e:
        print(f"⚠️ WARNING: Could not query NVENC formats ({e}). Assuming nv12 only.")
        fmts = {"nv12"}

    _NVENC_FORMATS = fmts
    print(f"INFO: NVENC supported pixel formats detected: {_NVENC_FORMATS}")
    return _NVENC_FORMATS


def detect_bit_depth(input_path: Path, video_stream_index: int = 0, force_8bit: bool = False, force_10bit: bool = False):
    """
    Detect bit depth with ffprobe and pick best NVENC-compatible format.
    Returns (is_10bit, is_12bit, chosen_fmt).
    """

    nvenc_formats = nvenc_supported_pix_fmts()

    if force_8bit:
        print("⚠️ WARNING: --force-8bit enabled. Skipping detection, forcing nv12.")
        return False, False, "nv12"

    elif force_10bit:
        if "p010le" in nvenc_formats:
            print("⚠️ WARNING: --force-10bit enabled. Skipping detection, forcing p010le.")
            #return True, False, "p010le"
        else:
            print("⚠️ WARNING: --force-10bit requested but GPU lacks 10-bit NVENC. Downgrading to nv12.")
            #return False, False, "nv12"
    print("8 bit: {force_8bit}   10 bit: {force_10bit}   ")
    exit(0)
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error",
            "-select_streams", f"v:{video_stream_index}",
            "-show_entries", "stream=pix_fmt",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(input_path)
        ], text=True).strip()

        if not out:
            print("⚠️ WARNING: ffprobe returned no pix_fmt. Falling back to nv12.")
            return False, False, "nv12"

        pix_fmt = out.lower()
        is_10bit = "10" in pix_fmt
        is_12bit = "12" in pix_fmt

        # Pick compatible format
        if is_12bit:
            print("⚠️ WARNING: 12-bit input detected. NVENC does not support 12-bit.")
            if "p010le" in nvenc_formats:
                chosen_fmt = "p010le"
            else:
                print("⚠️ WARNING: GPU lacks 10-bit NVENC. Downgrading to nv12 (8-bit).")
                chosen_fmt = "nv12"
        elif is_10bit:
            if "p010le" in nvenc_formats:
                chosen_fmt = "p010le"
            else:
                print("⚠️ WARNING: 10-bit input but GPU lacks 10-bit NVENC. Downgrading to nv12.")
                chosen_fmt = "nv12"
        else:
            chosen_fmt = "nv12"

        print(f"DEBUG: ffprobe pix_fmt={pix_fmt}, chosen_fmt={chosen_fmt}")
        return is_10bit, is_12bit, chosen_fmt

    except subprocess.CalledProcessError:
        print("⚠️ WARNING: ffprobe failed. Falling back to nv12.")
        return False, False, "nv12"
    
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
    force_8bit = False,
    force_10bit = False,
) -> List[str]:
    cmd = ["ffmpeg", "-y"]
    hw_type = "cpu"

    # Detect input video stream
    # Find first video stream (if any)
    video_stream = next((s for s in streams if s["codec_type"] == "video"), None)

    # --- robust pix_fmt + bit-depth detection using ffprobe JSON output ---
    input_pix_fmt = None
    bit_depth = None
    

    if video_stream:
        is_10bit, is_12bit, chosen_fmt = detect_bit_depth(
            input_path,
            video_stream['index'],
            force_8bit=force_8bit and not force_10bit,
            force_10bit=force_10bit
        )
    else:
        is_10bit, is_12bit, chosen_fmt = False, False, "nv12"



    # Detect GPU type
    if use_gpu:
        if shutil.which("nvidia-smi"):
            hw_type = "nvidia"
        elif shutil.which("vainfo"):
            hw_type = "intel"

    # Input file
    cmd += ["-i", str(input_path)]

 # ---------------- Video handling ----------------
    # Only set up video options if user requested a transcode (not "copy")
    if video_codec.lower() != "copy" and video_stream:
        requested = video_codec.lower()
        vf_filters: List[str] = []
        extra_pre_codec_opts: List[str] = []  # used for e.g. -vf before codec or pix_fmt fallback

        # NVENC path
        if hw_type == "nvidia":
            if requested in ("h264", "libx264"):
                codec_to_use = "h264_nvenc"
            elif requested in ("hevc", "h265", "libx265"):
                codec_to_use = "hevc_nvenc"
            else:
                codec_to_use = requested

            # Force chosen pixel format
            if chosen_fmt:
                vf_filters.append(f"format={chosen_fmt}")
                if debug:
                    print(f"DEBUG: Forcing format={chosen_fmt} for NVENC")

            if vf_filters:
                extra_pre_codec_opts += ["-vf", ",".join(vf_filters)]
            cmd += extra_pre_codec_opts + ["-c:v", codec_to_use]

        # Intel VAAPI path
        elif hw_type == "intel":
            if requested in ("h264", "libx264"):
                codec_to_use = "h264_vaapi"
                # for VAAPI target prefer nv12 + hwupload for h264
                vf_filters.append("format=nv12,hwupload")
            elif requested in ("hevc", "h265", "libx265"):
                codec_to_use = "hevc_vaapi"
                # keep p010 for 10-bit source if available; but if we must downconvert to 8-bit use nv12,hwupload
                if is_10bit or is_12bit:
                    # convert to p010 then hwupload — many VAAPI drivers support p010
                    vf_filters.append("format=p010,hwupload")
                else:
                    vf_filters.append("format=nv12,hwupload")
            else:
                codec_to_use = requested

            if vf_filters:
                cmd += ["-vf", ",".join(vf_filters)]
            cmd += ["-c:v", codec_to_use]
            if quality > 0:
                cmd += ["-global_quality", str(quality)]

        # CPU path (software encoders)
        else:
            if requested in ("h264", "libx264"):
                codec_to_use = "libx264"
                # libx264 expects 8-bit for typical profiles. Downconvert if needed.
                if is_10bit or is_12bit:
                    # force yuv420p 8-bit
                    vf_filters.append("format=yuv420p")
                    if debug:
                        print("DEBUG: Input >8-bit detected — adding format=yuv420p for libx264")
                cmd += (["-vf", ",".join(vf_filters)] if vf_filters else []) + ["-c:v", codec_to_use]
                if quality > 0:
                    cmd += ["-crf", str(quality)]
            elif requested in ("hevc", "h265", "libx265"):
                codec_to_use = "libx265"
                cmd += (["-vf", ",".join(vf_filters)] if vf_filters else []) + ["-c:v", codec_to_use]
                if quality > 0:
                    cmd += ["-crf", str(quality)]
            else:
                # fallback — honor user's string
                cmd += (["-vf", ",".join(vf_filters)] if vf_filters else []) + ["-c:v", requested]


    # ---------------- Audio ---------------- #
    if audio_codec.lower() != "copy":
        cmd += ["-c:a", audio_codec]
        if audio_channels in (2, 6):
            cmd += ["-ac", str(audio_channels)]

    # ---------------- Stream mapping ---------------- #
    map_args = []
    subs_codecs_per_stream = {}
    for s in streams:
        stype = s["codec_type"]
        idx = s["index"]
        lang = s.get("language", "und").lower()
        src_codec = s.get("codec_name")
        keep_stream = True

        if strip:
            if stype == "audio" and lang != audio_lang.lower():
                keep_stream = False
            if stype == "subtitle" and lang != subs_lang.lower():
                keep_stream = False

        if keep_stream and stype == "subtitle":
            trg_ext = output_path.suffix.lower()
            final_sub_codec = None

            if trg_ext == ".mp4":
                # MP4 only supports mov_text (text-based subs).
                if src_codec in ("subrip", "srt", "ass", "ssa", "mov_text"):
                    final_sub_codec = "mov_text"
                else:
                    # Drop unsupported bitmap subs like PGS, VobSub
                    keep_stream = False

            elif trg_ext == ".mkv":
                # MKV supports pretty much anything – copy directly
                final_sub_codec = "copy"

            elif trg_ext == ".webm":
                # WebM only supports WebVTT (and sometimes SRT)
                if src_codec in ("webvtt", "srt", "subrip"):
                    final_sub_codec = "webvtt"
                else:
                    keep_stream = False

            if keep_stream and final_sub_codec:
                subs_codecs_per_stream[idx] = final_sub_codec

        if keep_stream:
            map_args.append(f"0:{idx}")

    for m in map_args:
        cmd += ["-map", m]

    for idx, sub_c in subs_codecs_per_stream.items():
        cmd += [f"-c:s:{list(subs_codecs_per_stream.keys()).index(idx)}", sub_c]

    # for mp4 maybe add this in?
    # cmd.append("-movflags +faststart")

    # Output path
    cmd.append(str(output_path))

    # Debug info
    if debug:
        print("\nDEBUG: Hardware type:", hw_type)
        print("DEBUG: Input file:", input_path)
        print("DEBUG: Output file:", output_path)
        print("DEBUG: FFmpeg command:\n", " ".join(cmd), "\n")

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
    debug: bool = False,
    force_8bit = False,
    force_10bit = False
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
        debug=debug,
        force_8bit=force_8bit,
        force_10bit=force_10bit,
    )

    try:
        #subprocess.run(cmd, check=True, capture_output=True)
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
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
    parser.add_argument("-ch", "--audio-channels", type=int, default=0, help="Target audio channels - 2 or 6 (for 5.1)")
    parser.add_argument("-s", "--subtitle-codec", type=str, default="copy", help="Target subtitle codec - e.g. subrip srt pgsub mov_text..")
    parser.add_argument("--strip", action="store_true", help="Keep only specific language. Defaults to English")
    parser.add_argument("--audio-lang", type=str, default="eng", help="Target audio language. Use with --strip")
    parser.add_argument("--subs-lang", type=str, default="eng", help="Target subtitle. Use with --strip")
    parser.add_argument("--no-replace", action="store_true", help="Keeps source files when different container type.")
    parser.add_argument("-pb", "--probe", action="store_true", help="Get file info only.")
    parser.add_argument("-ls", "--list", action="store_true", help="Show root directory content.")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent workers.")
    parser.add_argument("--logfile", type=Path, default=Path("mf-errors.log"), help="Error log file.")
    parser.add_argument("--dry-run", action="store_true", help="Do not transcode; only show what would happen.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output.")
    parser.add_argument("--debug", action="store_true", help="Print out some extra stuff.")
    parser.add_argument("--version", action="store_true", help="Show script version no.")
    parser.add_argument("--force-8bit", action="store_true", help="Force nv12 (skip detection)")
    parser.add_argument("--force-10bit", action="store_true", help="Force p010le if supported (skip detection)")

    args = parser.parse_args()

    if args.version:
        print(f"Media Fixer version {version}")
        # check: ffmpeg -encoders | grep nvenc
        sys.exit(0)

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

            #ffprobe -loglevel error -show_entries stream=pix_fmt -of csv=p=0 input.mp4
            out = subprocess.check_output([
                "ffprobe", "-v", "error",
                "-select_streams", f"{fp}",
                "-show_entries", "stream=pix_fmt",
                str(fp)
            ], text=True).strip()
            print(out)

            

        sys.exit(0)

    # List mode
    if args.list:
        print(f"Media files in {args.dir if args.dir else args.file.parent}:")
        for fp in files:
            print(f" - {fp.relative_to(args.dir) if args.dir else fp.name}")
        sys.exit(0)

    # Prepare output paths
    tfiles: List[Path] = []
    out_paths: List[Path] = []

    for fp in files:
        info = probe_streams(fp)
        container = fp.suffix.lstrip(".").lower()
        has_video = any(s["codec_type"] == "video" for s in info)
        has_audio = any(s["codec_type"] == "audio" for s in info)
        has_subtitles = any(s["codec_type"] == "subtitle" for s in info)

        needs_transcode = (
            (args.video_codec != "copy" and has_video) or
            (args.audio_codec != "copy" and has_audio) or
            (args.subtitle_codec != "copy" and has_subtitles) or
            (args.container and args.container.lower() != container) or
            (args.quality > 0) or
            (args.audio_channels > 0) or
            args.strip
        )
        if needs_transcode:
            tfiles.append(fp)
            # Build temp output path with _tmp_ prefix
            tmp_filename = "_tmp_" + fp.name
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

    # ----------------------------
    # Parallel transcoding with progress
    # ----------------------------
    worker_cnt = args.workers if args.workers > 0 else 1
    use_tqdm = tqdm is not None and not args.quiet

    # Safe tqdm wrapper
    def tqdm_safe(iterable, *args, **kwargs):
        if tqdm is None:
            return iterable
        else:
            return tqdm(iterable, *args, **kwargs)

    errors: List[str] = []
    success_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_cnt) as executor:
        # Submit all tasks
        futures = {
            executor.submit(
                transcode_file,
                in_path=in_fp,
                out_path=out_fp,
                quality=args.quality,
                video_codec=args.video_codec,
                audio_codec=args.audio_codec,
                audio_channels=args.audio_channels,
                subtitle_codec=args.subtitle_codec,
                strip=args.strip,
                audio_lang=args.audio_lang,
                subs_lang=args.subs_lang,
                error_log=errors,
                debug=args.debug,
                force_8bit=args.force_8bit,
                force_10bit=args.force_10bit
            ): (in_fp, out_fp)
            for in_fp, out_fp in zip(tfiles, out_paths)
        }

        # Wrap as_completed with tqdm_safe
        iterable = concurrent.futures.as_completed(futures)
        if use_tqdm:
            iterable = tqdm_safe(iterable, desc="Transcoding", total=len(tfiles))

        for fut in iterable:
            in_path, tmp_path = futures[fut]
            try:
                if not fut.result():
                    continue  # skip failed transcodes

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

    # ----------------------------
    # Summary
    # ----------------------------
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