"""
╔══════════════════════════════════════════════════════════════════╗
║        🎬 PRO VIDEO EDITOR  +  AUTO BATCH PROCESSOR             ║
║        Desktop GUI  |  Scene Detection  |  Batch Processing     ║
║        By Nadeem  —  v2.0.0                                      ║
╚══════════════════════════════════════════════════════════════════╝

Requirements:
    pip install customtkinter moviepy pillow imageio-ffmpeg rich

FFmpeg is bundled via imageio-ffmpeg — no manual install needed.
"""

# ─── Standard Library ────────────────────────────────────────────
import os
import re
import sys
import json
import random
import shutil
import tempfile
import threading
import subprocess
import signal
import datetime
import time
import webbrowser
import urllib.parse
import urllib.request
import http.server
import socketserver
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

# ─── Third-party ─────────────────────────────────────────────────
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

try:
    import imageio_ffmpeg as _iio_ff
    _BUNDLED_FFMPEG = _iio_ff.get_ffmpeg_exe()
except Exception:
    _BUNDLED_FFMPEG = None

# ════════════════════════════════════════════════════════════════
#  FFmpeg / FFprobe RESOLVER
#  Priority: 1) imageio-ffmpeg bundled  2) system PATH  3) common paths
# ════════════════════════════════════════════════════════════════
def _resolve_bin(name: str) -> Optional[str]:
    """Find an executable, return its path or None."""
    # 1. Bundled ffmpeg from imageio-ffmpeg (only works for 'ffmpeg')
    if name == "ffmpeg" and _BUNDLED_FFMPEG:
        try:
            r = subprocess.run([_BUNDLED_FFMPEG, "-version"],
                               capture_output=True, timeout=5)
            if r.returncode == 0:
                return _BUNDLED_FFMPEG
        except Exception:
            pass

    # 2. Derive ffprobe from bundled ffmpeg path
    if name == "ffprobe" and _BUNDLED_FFMPEG:
        candidate = str(Path(_BUNDLED_FFMPEG).parent / "ffprobe")
        for c in [candidate, candidate + ".exe",
                  str(Path(_BUNDLED_FFMPEG).parent / "ffprobe.exe")]:
            try:
                r = subprocess.run([c, "-version"], capture_output=True, timeout=5)
                if r.returncode == 0:
                    return c
            except Exception:
                pass

    # 3. System PATH
    found = shutil.which(name)
    if found:
        return found

    # 4. Common Windows install locations
    if os.name == "nt":
        win_dirs = [
            r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "ffmpeg", "bin"),
            os.path.join(os.environ.get("USERPROFILE", ""), "ffmpeg", "bin"),
        ]
        for d in win_dirs:
            for exe in [name, name + ".exe"]:
                p = os.path.join(d, exe)
                if os.path.isfile(p):
                    return p
    return None


FFMPEG_BIN  = _resolve_bin("ffmpeg")
FFPROBE_BIN = _resolve_bin("ffprobe")


_CANCEL_EVENT = threading.Event()
_ACTIVE_PROCS_LOCK = threading.Lock()
_ACTIVE_PROCS: list[subprocess.Popen] = []


def _register_proc(proc: subprocess.Popen) -> None:
    with _ACTIVE_PROCS_LOCK:
        _ACTIVE_PROCS.append(proc)


def _unregister_proc(proc: subprocess.Popen) -> None:
    with _ACTIVE_PROCS_LOCK:
        try:
            _ACTIVE_PROCS.remove(proc)
        except ValueError:
            pass


def cancel_all_processes() -> None:
    _CANCEL_EVENT.set()
    with _ACTIVE_PROCS_LOCK:
        procs = list(_ACTIVE_PROCS)
    for p in procs:
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass
    for p in procs:
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════
#  SETTINGS  (settings.json)
# ════════════════════════════════════════════════════════════════
SETTINGS_PATH = Path("settings.json")

# Defaults — will be overwritten by settings.json if present
SETTINGS: dict = {
    "trim_end_seconds":   4.0,
    "scene_threshold":    0.35,
    "fade_seconds":       0.35,
    "min_scene_seconds":  0.75,
    "random_transitions": True,
    "transitions":        ["fade","wipe","slide","smoothleft","smoothright","circleopen"],
    "crop_left":          120,
    "crop_top":           82,
    "crop_right":         0,
    "crop_bottom":        0,
    "logo": {
        "enabled": False,
        "path":    "Input/logo.png",
        "x":       "20",
        "y":       "H-h-20",
        "width":   160,
        "opacity": 1.0,
    },
    "ending": {
        "enabled": False,
        "path":    "Input/ending.mp4",
    },
    "pending_dir": "E:/Pythons/Youtube/Pending",
    "done_dir":    "E:/Pythons/Youtube/Done",
    # ── Automation / Drive / Sheet ──────────────────────────────
    "apps_script_url":  "",          # Google Apps Script Web App URL
    "drive_folder_id":  "1iYR7cw9kihjJSYQnpBBCqFEJ7oWQDb00",  # Drive folder
    "auto_watch":       False,       # Watch Pending folder automatically
    "upload_to_drive":  True,        # Upload processed video to Drive
    "update_sheet":     True,        # Update sheet after upload
    "oauth_token":      "",          # Stored OAuth access token
    "oauth_expiry":     0,           # Token expiry timestamp
    # ── Main Tab ────────────────────────────────────────────────
    "main": {
        "scan_dir":       r"C:\Users\NADEEM\Downloads",
        "logo_enabled":   True,
        "logo_path":      r"e:\Pythons\AutoMagicAI\Logo\logo.png",
        "logo_x":         "10",
        "logo_y":         "10",
        "logo_width":     120,
        "logo_opacity":   1.0,
        "trim_enabled":   True,
        "trim_seconds":   4,
        "quality_profile":"4",
        "ending_enabled": False,
        "ending_path":    "",
        "delete_source":  False,
        "upload_drive":   True,
        "drive_folder_id":"1iYR7cw9kihjJSYQnpBBCqFEJ7oWQDb00",
    },
}

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".flv", ".wmv"}


def load_settings() -> None:
    global SETTINGS
    if not SETTINGS_PATH.exists():
        save_settings()
        return
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _deep_merge(SETTINGS, data)
    except Exception:
        pass


def save_settings() -> None:
    try:
        SETTINGS_PATH.write_text(json.dumps(SETTINGS, indent=2), encoding="utf-8")
    except Exception:
        pass


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ════════════════════════════════════════════════════════════════
#  YOUTUBE EXPORT PROFILES  (from Script 1)
# ════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Profile:
    label:         str
    height:        int
    fps:           int
    crf:           int
    audio_bitrate: str


YOUTUBE_PROFILES: dict[str, Profile] = {
    "1": Profile("2160p (4K)",   2160, 30, 23, "160k"),
    "2": Profile("1440p (2K)",   1440, 30, 23, "160k"),
    "3": Profile("1080p (FHD)",  1080, 30, 23, "128k"),
    "4": Profile("720p (HD)",     720, 30, 23, "128k"),
    "5": Profile("480p (SD)",     480, 30, 24, "128k"),
}


# ════════════════════════════════════════════════════════════════
#  LOW-LEVEL FFmpeg HELPERS
# ════════════════════════════════════════════════════════════════
def _run_capture(cmd: list, cancel_event: Optional[threading.Event] = None,
                 line_callback=None) -> tuple:
    """Run a command and return (returncode, stdout, stderr)."""
    proc: Optional[subprocess.Popen] = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1)
        _register_proc(proc)
        out_lines: list[str] = []
        err_lines: list[str] = []
        ce = cancel_event or _CANCEL_EVENT
        while True:
            if ce.is_set() and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            o = proc.stdout.readline() if proc.stdout else ""
            e = proc.stderr.readline() if proc.stderr else ""
            if o:
                out_lines.append(o)
                if line_callback:
                    line_callback(o.rstrip("\n"))
            if e:
                err_lines.append(e)
                if line_callback:
                    line_callback(e.rstrip("\n"))
            if not o and not e:
                if proc.poll() is not None:
                    break
        if proc.stdout:
            try:
                rest = proc.stdout.read()
                if rest:
                    out_lines.append(rest)
            except Exception:
                pass
        if proc.stderr:
            try:
                rest = proc.stderr.read()
                if rest:
                    err_lines.append(rest)
            except Exception:
                pass
        return proc.returncode, "".join(out_lines), "".join(err_lines)
    except FileNotFoundError as e:
        return -1, "", str(e)
    finally:
        if proc is not None:
            try:
                _unregister_proc(proc)
            except Exception:
                pass


def run_ffmpeg(cmd: list, progress_callback=None,
              cancel_event: Optional[threading.Event] = None,
              line_callback=None) -> tuple:
    """Run ffmpeg with optional progress callback(pct 0-100).
       Replaces 'ffmpeg' token with resolved FFMPEG_BIN automatically."""
    if not FFMPEG_BIN:
        return False, "FFmpeg not found. Install FFmpeg or run: pip install imageio-ffmpeg"
    if cmd and cmd[0] in ("ffmpeg", "ffmpeg.exe"):
        cmd = [FFMPEG_BIN] + cmd[1:]

    # If filters are used, ffmpeg must re-encode video. Default to a faster preset
    # when the caller didn't provide explicit video encoding settings.
    has_filter = ("-vf" in cmd) or ("-filter_complex" in cmd)
    has_vcodec = ("-c:v" in cmd) or ("-c" in cmd)
    if has_filter and not has_vcodec:
        try:
            out_i = len(cmd) - 1
            cmd = cmd[:out_i] + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"] + cmd[out_i:]
        except Exception:
            pass

    proc: Optional[subprocess.Popen] = None
    try:
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE,
                                stdout=subprocess.PIPE, universal_newlines=True,
                                bufsize=1)
        _register_proc(proc)
        duration_sec = None
        ce = cancel_event or _CANCEL_EVENT
        err_lines: List[str] = []
        for line in proc.stderr:
            err_lines.append(line)
            if line_callback:
                try:
                    line_callback(line.rstrip("\n"))
                except Exception:
                    pass
            if ce.is_set() and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=1.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            if duration_sec is None:
                m = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)', line)
                if m:
                    h, mi, s = m.groups()
                    duration_sec = int(h)*3600 + int(mi)*60 + float(s)
            if progress_callback and duration_sec:
                m = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
                if m:
                    h, mi, s = m.groups()
                    elapsed = int(h)*3600 + int(mi)*60 + float(s)
                    pct = min(100, int(elapsed / duration_sec * 100))
                    progress_callback(pct)
        proc.wait()
        if progress_callback:
            progress_callback(100)
        if proc.returncode == 0:
            return True, ""
        tail = "".join(err_lines[-80:])
        return False, tail.strip() or "FFmpeg failed."
    except Exception as e:
        return False, str(e)
    finally:
        if proc is not None:
            try:
                _unregister_proc(proc)
            except Exception:
                pass


def get_video_info(path: str) -> Optional[dict]:
    """Return dict with duration, width, height, fps, size — or None on failure."""
    if not os.path.exists(path):
        return None
    info = {
        "path":     path,
        "filename": os.path.basename(path),
        "duration": 0.0,
        "width":    0,
        "height":   0,
        "fps":      0.0,
        "size":     os.path.getsize(path),
    }
    try:
        if FFPROBE_BIN:
            cmd = [FFPROBE_BIN, "-v", "quiet", "-print_format", "json",
                   "-show_streams", "-show_format", path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            data = json.loads(result.stdout) if result.stdout.strip() else {}
        else:
            # Fallback: parse ffmpeg stderr
            result = subprocess.run(
                [FFMPEG_BIN or "ffmpeg", "-hide_banner", "-i", path],
                capture_output=True, text=True, timeout=15)
            data = {"_raw": (result.stderr or "") + (result.stdout or "")}

        if "format" in data:
            info["duration"] = float(data["format"].get("duration", 0))
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["width"]  = stream.get("width",  0)
                info["height"] = stream.get("height", 0)
                fps_str = stream.get("r_frame_rate", "0/1")
                try:
                    n, d = fps_str.split("/")
                    info["fps"] = round(float(n) / float(d), 2) if float(d) else 0
                except Exception:
                    pass
                break
        # Fallback parsing from raw text
        raw = data.get("_raw", "")
        if raw:
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", raw)
            if m:
                h, mi, s = m.groups()
                info["duration"] = int(h)*3600 + int(mi)*60 + float(s)
            m = re.search(r",\s*(\d+)x(\d+)[,\s]", raw)
            if m:
                info["width"], info["height"] = int(m.group(1)), int(m.group(2))
            m = re.search(r"(\d+(?:\.\d+)?)\s*fps", raw)
            if m:
                info["fps"] = float(m.group(1))
        return info
    except Exception:
        return info  # return partial info rather than nothing


def probe_duration_and_audio(path: Path) -> tuple:
    """Return (duration_seconds, has_audio)."""
    ff = FFMPEG_BIN or "ffmpeg"
    rc, out, err = _run_capture([ff, "-hide_banner", "-loglevel", "info",
                                   "-i", str(path), "-f", "null", "-"])
    text = out + "\n" + err
    duration = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        h, mi, s = m.groups()
        duration = int(h)*3600 + int(mi)*60 + float(s)
    return duration, ("Audio:" in text)


def format_duration(secs: float) -> str:
    secs = int(secs)
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def format_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


# ════════════════════════════════════════════════════════════════
#  SCENE DETECTION  (from Script 1)
# ════════════════════════════════════════════════════════════════
def detect_scene_changes(path: Path, threshold: float) -> list:
    ff = FFMPEG_BIN or "ffmpeg"
    rc, out, err = _run_capture([
        ff, "-hide_banner", "-loglevel", "info", "-i", str(path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-an", "-f", "null", "-",
    ])
    text = out + "\n" + err
    times = []
    for m in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", text):
        try:
            t = float(m.group(1))
            if t > 0:
                times.append(t)
        except ValueError:
            pass
    deduped = []
    for t in sorted(times):
        if not deduped or abs(t - deduped[-1]) > 0.2:
            deduped.append(t)
    return deduped


def build_segments(scene_changes: list, end_time: float, min_len: float) -> list:
    cuts = sorted(set([0.0] + [t for t in scene_changes if 0 < t < end_time] + [end_time]))
    segs = [(cuts[i], cuts[i+1]) for i in range(len(cuts)-1)
            if cuts[i+1] - cuts[i] >= min_len]
    return segs or [(0.0, end_time)]


# ════════════════════════════════════════════════════════════════
#  BATCH RENDERING ENGINE  (from Script 1, adapted)
# ════════════════════════════════════════════════════════════════
def _pick_transition() -> str:
    # If no transitions are checked or random is off → always use fade as safe default
    active = SETTINGS.get("transitions", [])
    if not SETTINGS.get("random_transitions", True) or not active:
        return "fade"
    picked = random.choice(active)
    if picked == "wipe":
        return random.choice(["wipeleft","wiperight","wipeup","wipedown"])
    if picked == "slide":
        return random.choice(["slideleft","slideright","slideup","slidedown"])
    return picked


_XFADE_TRANSITIONS = {
    "fade",
    "wipeleft", "wiperight", "wipeup", "wipedown",
    "slideleft", "slideright", "slideup", "slidedown",
    "smoothleft", "smoothright",
    "circleopen",
}


def _sanitize_transition_name(name: str) -> str:
    name = (name or "").strip()
    name = name.strip("\"'[]{}()")
    name = re.sub(r"[^a-zA-Z0-9_]+", "", name)
    name = name.lower()
    return name


def _pick_safe_transition() -> str:
    t = _sanitize_transition_name(_pick_transition())
    return t if t in _XFADE_TRANSITIONS else "fade"


def render_with_transitions(input_path: Path, output_path: Path,
                             profile: Profile, segments: list,
                             has_audio: bool, progress_cb=None) -> tuple:
    """Render kept segments with xfade transitions. Returns (ok, error_msg)."""
    if not segments:
        return False, "No segments provided."

    cl      = SETTINGS.get("crop_left",   0)
    ct      = SETTINGS.get("crop_top",    0)
    cr      = SETTINGS.get("crop_right",  0)
    cb      = SETTINGS.get("crop_bottom", 0)
    # FFmpeg crop: w = iw - left - right,  h = ih - top - bottom,  x = left,  y = top
    base_vf = f"crop=iw-{cl}-{cr}:ih-{ct}-{cb}:{cl}:{ct},scale=-2:{profile.height}"
    fade    = SETTINGS["fade_seconds"]
    logo    = SETTINGS["logo"]
    add_logo = logo["enabled"] and logo["path"] and Path(logo["path"]).exists()
    ff      = FFMPEG_BIN or "ffmpeg"

    output_parent = output_path.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="pvf_", dir=str(output_parent.resolve())))

    try:
        seg_files = []
        total = len(segments)
        for i, (a, b) in enumerate(segments):
            seg_out = tmp_dir / f"seg_{i:03d}.mp4"
            if progress_cb:
                progress_cb(int(i / total * 60))

            if add_logo:
                lw = logo["width"]; lx = logo["x"]; ly = logo["y"]
                lo = logo["opacity"]
                logo_f = (f"[1:v]scale={lw}:-1,format=rgba"
                          + (f",colorchannelmixer=aa={lo}" if lo < 1.0 else "")
                          + "[logo]")
                fc = (f"{logo_f};"
                      f"[0:v]{base_vf},trim=start={a}:end={b},"
                      f"setpts=PTS-STARTPTS,fps={profile.fps},format=yuv420p,settb=AVTB[base];"
                      f"[base][logo]overlay=x={lx}:y={ly}[v]"
                      + (f";[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a]" if has_audio else ""))
                cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
                       "-i", str(input_path), "-i", logo["path"],
                       "-filter_complex", fc, "-map", "[v]"]
            else:
                fc = (f"[0:v]{base_vf},trim=start={a}:end={b},"
                      f"setpts=PTS-STARTPTS,fps={profile.fps},format=yuv420p,settb=AVTB[v]"
                      + (f";[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a]" if has_audio else ""))
                cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
                       "-i", str(input_path), "-filter_complex", fc, "-map", "[v]"]

            cmd += (["-map", "[a]"] if has_audio else ["-an"])
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(profile.crf),
                    "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart"]
            if has_audio:
                cmd += ["-c:a", "aac", "-b:a", profile.audio_bitrate, "-ar", "48000"]
            cmd.append(str(seg_out))

            rc, _, err = _run_capture(cmd)
            if rc != 0:
                return False, err
            seg_files.append(seg_out)

        # Merge with transitions
        current = seg_files[0]
        cur_dur, _ = probe_duration_and_audio(current)

        for i in range(1, len(seg_files)):
            nxt     = seg_files[i]
            nxt_dur, _ = probe_duration_and_audio(nxt)
            offset  = max(0.0, cur_dur - fade)
            trans   = _pick_safe_transition()
            merged  = tmp_dir / f"merge_{i:03d}.mp4"

            fc_parts = [f"[0:v][1:v]xfade=transition={trans}:duration={fade}:offset={offset}[v]"]
            if has_audio:
                fc_parts.append(f"[0:a][1:a]acrossfade=d={fade}[a]")

            cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
                   "-i", str(current), "-i", str(nxt),
                   "-filter_complex", ";".join(fc_parts), "-map", "[v]"]
            cmd += (["-map", "[a]"] if has_audio else ["-an"])
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(profile.crf),
                    "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart"]
            if has_audio:
                cmd += ["-c:a", "aac", "-b:a", profile.audio_bitrate, "-ar", "48000"]
            cmd.append(str(merged))

            rc, _, err = _run_capture(cmd)
            if rc != 0 and trans != "fade":
                err_l = (err or "").lower()
                if (
                    "not yet implemented" in err_l
                    or "trailing garbage" in err_l
                    or "error parsing" in err_l
                    or "invalid argument" in err_l
                ):
                    fc_parts = [f"[0:v][1:v]xfade=transition=fade:duration={fade}:offset={offset}[v]"]
                    if has_audio:
                        fc_parts.append(f"[0:a][1:a]acrossfade=d={fade}[a]")
                    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
                           "-i", str(current), "-i", str(nxt),
                           "-filter_complex", ";".join(fc_parts), "-map", "[v]"]
                    cmd += (["-map", "[a]"] if has_audio else ["-an"])
                    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(profile.crf),
                            "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart"]
                    if has_audio:
                        cmd += ["-c:a", "aac", "-b:a", profile.audio_bitrate, "-ar", "48000"]
                    cmd.append(str(merged))
                    rc, _, err = _run_capture(cmd)
            if rc != 0:
                return False, err

            current  = merged
            cur_dur  = max(0.0, cur_dur + nxt_dur - fade)
            if progress_cb:
                progress_cb(60 + int(i / len(seg_files) * 35))

        if output_path.exists():
            output_path.unlink()
        try:
            current.replace(output_path)
        except OSError:
            shutil.move(str(current), str(output_path))

        if progress_cb:
            progress_cb(100)
        return True, ""

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def concat_ending(main_path: Path, ending_path: Path,
                  output_path: Path, profile: Profile) -> tuple:
    """Append ending video to main. Returns (ok, error_msg)."""
    ff = FFMPEG_BIN or "ffmpeg"
    _, main_audio = probe_duration_and_audio(main_path)
    _, end_audio  = probe_duration_and_audio(ending_path)
    with_audio    = main_audio and end_audio

    parts = [
        f"[0:v]fps={profile.fps},format=yuv420p,settb=AVTB[v0]",
        f"[1:v]scale=-2:{profile.height},fps={profile.fps},format=yuv420p,settb=AVTB[v1]",
    ]
    if with_audio:
        parts += [
            "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[a0]",
            "[1:a]aformat=sample_rates=48000:channel_layouts=stereo[a1]",
            "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]",
        ]
    else:
        parts.append("[v0][v1]concat=n=2:v=1:a=0[v]")

    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(main_path), "-i", str(ending_path),
           "-filter_complex", ";".join(parts), "-map", "[v]"]
    cmd += (["-map", "[a]"] if with_audio else ["-an"])
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(profile.crf),
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart"]
    if with_audio:
        cmd += ["-c:a", "aac", "-b:a", profile.audio_bitrate, "-ar", "48000"]
    cmd.append(str(output_path))

    rc, _, err = _run_capture(cmd)
    return (rc == 0), err


# ════════════════════════════════════════════════════════════════
#  GOOGLE OAUTH  (browser-based, same account as dashboard)
#  Uses Drive + Sheets scopes. Token stored in settings.json
# ════════════════════════════════════════════════════════════════
OAUTH_CLIENT_ID     = "165516915479-27ks2km5q9sbod00uvsdmda3vfgf0toa.apps.googleusercontent.com"
OAUTH_CLIENT_SECRET = ""   # Not needed for PKCE / implicit flow via browser
OAUTH_REDIRECT_PORT = 9876
OAUTH_SCOPES        = "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/userinfo.email"

_oauth_token_cache: dict = {}   # {access_token, expiry}


def get_oauth_token() -> Optional[str]:
    """Return a valid OAuth token from cache/settings, or None if not authed."""
    # Check in-memory cache first
    token = _oauth_token_cache.get("access_token", "")
    expiry = _oauth_token_cache.get("expiry", 0)
    if token and time.time() < expiry - 60:
        return token
    # Check settings
    token = SETTINGS.get("oauth_token", "")
    expiry = SETTINGS.get("oauth_expiry", 0)
    if token and time.time() < expiry - 60:
        _oauth_token_cache["access_token"] = token
        _oauth_token_cache["expiry"]       = expiry
        return token
    return None


def set_oauth_token(token: str, expires_in: int = 3600) -> None:
    """Store token in memory and settings."""
    expiry = time.time() + expires_in
    _oauth_token_cache["access_token"] = token
    _oauth_token_cache["expiry"]       = expiry
    SETTINGS["oauth_token"]  = token
    SETTINGS["oauth_expiry"] = expiry
    save_settings()


def start_oauth_flow(on_success=None, on_error=None) -> None:
    """
    Open browser for Google OAuth. Starts a local server on port 9876 to
    receive the redirect with the auth code, then exchanges for access token.
    Calls on_success(token) or on_error(msg) on the main thread via callbacks.
    """
    import secrets, hashlib, base64

    # ── PKCE code verifier / challenge ──────────────────────────
    code_verifier  = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()

    redirect_uri = f"http://localhost:{OAUTH_REDIRECT_PORT}"
    params = {
        "client_id":             OAUTH_CLIENT_ID,
        "redirect_uri":          redirect_uri,
        "response_type":         "code",
        "scope":                 OAUTH_SCOPES,
        "access_type":           "offline",
        "code_challenge":        code_challenge,
        "code_challenge_method": "S256",
        "prompt":                "consent",
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

    result_holder = [None]   # ["token"] or ["error:msg"]
    done_event    = threading.Event()

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args): pass   # silence server logs

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            qs     = urllib.parse.parse_qs(parsed.query)
            code   = qs.get("code", [None])[0]
            error  = qs.get("error", [None])[0]

            if error:
                result_holder[0] = f"error:{error}"
                self._respond("<h2>Auth failed. Close this tab.</h2>")
            elif code:
                # Exchange code for token
                try:
                    token_data = urllib.parse.urlencode({
                        "code":          code,
                        "client_id":     OAUTH_CLIENT_ID,
                        "redirect_uri":  redirect_uri,
                        "grant_type":    "authorization_code",
                        "code_verifier": code_verifier,
                    }).encode()
                    req  = urllib.request.Request(
                        "https://oauth2.googleapis.com/token",
                        data=token_data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"}
                    )
                    resp = urllib.request.urlopen(req, timeout=15)
                    td   = json.loads(resp.read().decode())
                    result_holder[0] = td.get("access_token", "")
                    expires_in = int(td.get("expires_in", 3600))
                    set_oauth_token(result_holder[0], expires_in)
                    self._respond("<h2 style='color:green'>✅ Signed in! You can close this tab.</h2>")
                except Exception as e:
                    result_holder[0] = f"error:{e}"
                    self._respond("<h2 style='color:red'>Token exchange failed. Close tab.</h2>")
            else:
                self._respond("<h2>No code received.</h2>")
            done_event.set()

        def _respond(self, body: str):
            html = f"<html><body style='font-family:sans-serif;padding:40px'>{body}</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())

    def server_thread():
        with socketserver.TCPServer(("", OAUTH_REDIRECT_PORT), _Handler) as srv:
            srv.timeout = 120   # wait max 2 min for redirect
            srv.handle_request()
        # Process result
        r = result_holder[0] or "error:timeout"
        if r.startswith("error:"):
            if on_error: on_error(r[6:])
        else:
            if on_success: on_success(r)
        done_event.set()

    threading.Thread(target=server_thread, daemon=True).start()
    webbrowser.open(auth_url)


# ════════════════════════════════════════════════════════════════
#  GOOGLE DRIVE UPLOAD  (resumable for large files)
# ════════════════════════════════════════════════════════════════
def drive_upload_file(local_path: Path, folder_id: str,
                      on_progress=None) -> Optional[str]:
    """
    Upload a file to Google Drive. Returns shareable URL or None on failure.
    on_progress(pct 0-100) called during upload.
    """
    token = get_oauth_token()
    if not token:
        raise RuntimeError("Not signed in to Google. Use Automation tab → Sign In.")

    file_size = local_path.stat().st_size
    mime_type = "video/mp4"

    # ── Initiate resumable upload session ──────────────────────
    meta = json.dumps({
        "name":    local_path.name,
        "parents": [folder_id] if folder_id else [],
    }).encode()

    init_req = urllib.request.Request(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
        data=meta,
        headers={
            "Authorization":         f"Bearer {token}",
            "Content-Type":          "application/json",
            "X-Upload-Content-Type": mime_type,
            "X-Upload-Content-Length": str(file_size),
        },
        method="POST"
    )
    resp = urllib.request.urlopen(init_req, timeout=30)
    upload_url = resp.headers.get("Location")
    if not upload_url:
        raise RuntimeError("Drive did not return upload URL.")

    # ── Upload in chunks ────────────────────────────────────────
    CHUNK = 5 * 1024 * 1024   # 5 MB chunks
    offset = 0
    file_id = None

    with open(local_path, "rb") as f:
        while offset < file_size:
            chunk_data = f.read(CHUNK)
            end_byte   = offset + len(chunk_data) - 1
            headers    = {
                "Content-Range":  f"bytes {offset}-{end_byte}/{file_size}",
                "Content-Type":   mime_type,
            }
            req  = urllib.request.Request(upload_url, data=chunk_data,
                                          headers=headers, method="PUT")
            try:
                r    = urllib.request.urlopen(req, timeout=120)
                body = json.loads(r.read().decode())
                file_id = body.get("id")
                offset  = file_size
                if on_progress: on_progress(100)
            except urllib.error.HTTPError as e:
                if e.code == 308:   # Resume Incomplete
                    rng = e.headers.get("Range", f"bytes=0-{end_byte}")
                    offset = int(rng.split("-")[1]) + 1
                    if on_progress: on_progress(int(offset / file_size * 100))
                else:
                    raise RuntimeError(f"Drive upload error {e.code}: {e.read().decode()}")

    if not file_id:
        raise RuntimeError("Upload finished but no file ID returned.")

    # ── Make file publicly readable ─────────────────────────────
    perm_data = json.dumps({"role": "reader", "type": "anyone"}).encode()
    perm_req  = urllib.request.Request(
        f"https://www.googleapis.com/drive/v3/files/{file_id}/permissions",
        data=perm_data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST"
    )
    urllib.request.urlopen(perm_req, timeout=15)

    return f"https://drive.google.com/file/d/{file_id}/view"


def drive_get_or_create_subfolder(token: str, parent_id: str, name: str) -> Optional[str]:
    """
    Find a folder named `name` inside `parent_id`, or create it.
    Returns the folder ID, or None on failure.
    """
    # Search for existing folder
    q = urllib.parse.urlencode({
        "q":      f"name='{name}' and mimeType='application/vnd.google-apps.folder'"
                  f" and '{parent_id}' in parents and trashed=false",
        "fields": "files(id,name)",
    })
    try:
        req  = urllib.request.Request(
            f"https://www.googleapis.com/drive/v3/files?{q}",
            headers={"Authorization": f"Bearer {token}"}
        )
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode())
        files = data.get("files", [])
        if files:
            return files[0]["id"]
    except Exception:
        pass
    # Not found — create it
    try:
        meta = json.dumps({
            "name":     name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents":  [parent_id],
        }).encode()
        req  = urllib.request.Request(
            "https://www.googleapis.com/drive/v3/files",
            data=meta,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode())
        return data.get("id")
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════
#  APPS SCRIPT — save Drive URL + set status to Ready
# ════════════════════════════════════════════════════════════════
def sheet_save_video_url(story_title: str, drive_url: str,
                         script_url: str) -> bool:
    """
    POST to Apps Script to save Drive Video URL and set status → Ready.
    Returns True on success.
    """
    if not script_url:
        return False
    payload = json.dumps({
        "action":     "saveFileUrl",
        "storyTitle": story_title,
        "urlField":   "videoUrl",
        "url":        drive_url,
    }).encode()
    try:
        req  = urllib.request.Request(
            script_url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=20)
        return True
    except Exception:
        return False


def sheet_fetch_stories(script_url: str) -> List[dict]:
    """Fetch stories list from Apps Script. Returns list of story dicts."""
    if not script_url:
        return []
    try:
        url  = f"{script_url}?action=getStories"
        req  = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode())
        return data.get("stories", [])
    except Exception:
        return []


# ════════════════════════════════════════════════════════════════
#  THEME CONSTANTS
# ════════════════════════════════════════════════════════════════
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_VERSION  = "3.0.0"
ACCENT       = "#1f6feb"
BG_DARK      = "#0d1117"
BG_CARD      = "#161b22"
BG_SIDEBAR   = "#21262d"
TEXT_PRIMARY = "#e6edf3"
TEXT_MUTED   = "#8b949e"
SUCCESS      = "#238636"
WARNING      = "#d29922"
DANGER       = "#da3633"
PURPLE       = "#6e40c9"


# ════════════════════════════════════════════════════════════════
#  SCENE SELECTION DIALOG  (GUI version of Script 1's CLI prompt)
# ════════════════════════════════════════════════════════════════
class SceneSelectDialog(ctk.CTkToplevel):
    """Shows detected scenes and lets user pick which to keep."""

    def __init__(self, parent, segments: list):
        super().__init__(parent)
        self.title("🎬 Select Scenes to Keep")
        self.geometry("520x420")
        self.resizable(False, False)
        self.configure(fg_color=BG_DARK)
        self.grab_set()

        self.segments = segments
        self.result   = None          # list of kept (start, end) tuples
        self._vars    = []

        ctk.CTkLabel(self, text="🎬 Select Scenes to Keep",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(pady=(14, 4))
        ctk.CTkLabel(self, text="Uncheck scenes you want to REMOVE from the output.",
                     font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack()

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG_CARD, height=280)
        scroll.pack(fill="x", padx=16, pady=10)

        # Header row
        hdr = ctk.CTkFrame(scroll, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 4))
        for txt, w in [("Keep", 50), ("Scene #", 60), ("Start", 90),
                       ("End", 90), ("Duration", 90)]:
            ctk.CTkLabel(hdr, text=txt, width=w,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=TEXT_MUTED).pack(side="left", padx=4)

        for i, (a, b) in enumerate(segments):
            var = tk.BooleanVar(value=True)
            self._vars.append(var)
            row = ctk.CTkFrame(scroll, fg_color=BG_SIDEBAR, corner_radius=6)
            row.pack(fill="x", pady=2)
            ctk.CTkCheckBox(row, text="", variable=var, width=50,
                            checkbox_width=18, checkbox_height=18).pack(side="left", padx=6)
            for txt, w in [(f"#{i+1}", 60), (f"{a:.2f}s", 90),
                           (f"{b:.2f}s", 90), (f"{b-a:.2f}s", 90)]:
                ctk.CTkLabel(row, text=txt, width=w,
                             font=ctk.CTkFont(size=11),
                             text_color=TEXT_PRIMARY).pack(side="left", padx=4)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=10)
        ctk.CTkButton(btn_row, text="✅ Keep Selected", width=160, height=36,
                      fg_color=SUCCESS, hover_color="#196129",
                      command=self._confirm).pack(side="left", padx=8)
        ctk.CTkButton(btn_row, text="🔁 Keep All", width=120, height=36,
                      command=self._keep_all).pack(side="left", padx=8)

        self.wait_window(self)

    def _confirm(self):
        self.result = [seg for seg, var in zip(self.segments, self._vars) if var.get()]
        if not self.result:
            self.result = list(self.segments)
        self.destroy()

    def _keep_all(self):
        for v in self._vars:
            v.set(True)
        self._confirm()


# ════════════════════════════════════════════════════════════════
#  SETTINGS EDITOR DIALOG
# ════════════════════════════════════════════════════════════════
class SettingsDialog(ctk.CTkToplevel):
    """Edit settings.json inside the GUI."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("⚙️ Settings — settings.json")
        self.geometry("600x520")
        self.configure(fg_color=BG_DARK)
        self.grab_set()

        ctk.CTkLabel(self, text="⚙️ Batch Processor Settings",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(pady=(14, 4))
        ctk.CTkLabel(self, text="Changes are saved to settings.json automatically.",
                     font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack()

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG_CARD, height=380)
        scroll.pack(fill="both", expand=True, padx=16, pady=8)

        self._entries = {}
        self._build_settings_fields(scroll)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=10)
        ctk.CTkButton(btn_row, text="💾 Save Settings", width=160, height=36,
                      fg_color=SUCCESS, hover_color="#196129",
                      command=self._save).pack(side="left", padx=8)
        ctk.CTkButton(btn_row, text="✖ Close", width=120, height=36,
                      command=self.destroy).pack(side="left", padx=8)

    def _field(self, parent, label, key_path, placeholder=""):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=label, width=200, anchor="w",
                     font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack(side="left")
        e = ctk.CTkEntry(row, placeholder_text=placeholder, width=300)
        # Resolve current value
        keys = key_path.split(".")
        val = SETTINGS
        for k in keys:
            val = val.get(k, "") if isinstance(val, dict) else ""
        e.insert(0, str(val))
        e.pack(side="left", padx=8)
        self._entries[key_path] = e

    def _build_settings_fields(self, parent):
        sections = [
            ("🤖 Auto Batch", [
                ("Trim end (seconds)",     "trim_end_seconds",    "4.0"),
                ("Scene threshold (0–1)",  "scene_threshold",     "0.35"),
                ("Fade seconds",           "fade_seconds",        "0.35"),
                ("Min scene seconds",      "min_scene_seconds",   "0.75"),
                ("Random transitions",     "random_transitions",  "true/false"),
                ("Transitions (comma-sep)","transitions",         "fade,wipe,slide"),
                ("Crop left (px)",         "crop_left",           "120"),
                ("Crop top (px)",          "crop_top",            "82"),
                ("Pending folder",         "pending_dir",         "Pending"),
                ("Done folder",            "done_dir",            "Done"),
            ]),
            ("🖼️ Logo", [
                ("Enabled (true/false)",   "logo.enabled",  "false"),
                ("Logo file path",         "logo.path",     "Input/logo.png"),
                ("X position",             "logo.x",        "W-w-20"),
                ("Y position",             "logo.y",        "20"),
                ("Width (px)",             "logo.width",    "160"),
                ("Opacity (0–1)",          "logo.opacity",  "1.0"),
            ]),
            ("🎬 Ending Video", [
                ("Enabled (true/false)",   "ending.enabled", "false"),
                ("Ending file path",       "ending.path",    "Input/ending.mp4"),
            ]),
        ]
        for section_title, fields in sections:
            ctk.CTkLabel(parent, text=section_title,
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=ACCENT).pack(anchor="w", pady=(10, 2))
            for label, key, ph in fields:
                self._field(parent, label, key, ph)

    def _save(self):
        for key_path, entry in self._entries.items():
            val_str = entry.get().strip()
            keys    = key_path.split(".")
            node    = SETTINGS
            for k in keys[:-1]:
                node = node.setdefault(k, {})
            last_k = keys[-1]
            # Type coercion
            orig = node.get(last_k)
            if isinstance(orig, bool) or val_str.lower() in ("true", "false"):
                node[last_k] = val_str.lower() == "true"
            elif isinstance(orig, int):
                try:
                    node[last_k] = int(val_str)
                except ValueError:
                    pass
            elif isinstance(orig, float):
                try:
                    node[last_k] = float(val_str)
                except ValueError:
                    pass
            elif isinstance(orig, list):
                node[last_k] = [x.strip() for x in val_str.split(",") if x.strip()]
            else:
                node[last_k] = val_str
        save_settings()
        messagebox.showinfo("✅ Saved", "Settings saved to settings.json")


# ════════════════════════════════════════════════════════════════
#  MAIN APPLICATION WINDOW
# ════════════════════════════════════════════════════════════════
class VideoEditorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🎬 Pro Video Editor v3.0 — Bright Little Stories")
        self.geometry("1320x820")
        self.minsize(1100, 700)
        self.configure(fg_color=BG_DARK)
        # Start maximized — open full screen on launch
        self.after(0, lambda: self.state("zoomed"))

        # App state
        self.loaded_files  = []
        self.selected_file = None
        self.logo_path     = tk.StringVar()
        self.intro_path    = tk.StringVar()
        self.outro_path    = tk.StringVar()
        self.output_dir    = tk.StringVar(value=r"C:\Users\NADEEM\Downloads")
        self.cancel_event  = threading.Event()

        self._build_ui()
        self._check_ffmpeg_on_start()

        self.bind_all("<Control-c>", self._on_cancel)
        try:
            signal.signal(signal.SIGINT, lambda *_: self._on_cancel())
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────
    def _check_ffmpeg_on_start(self):
        if not FFMPEG_BIN:
            messagebox.showerror(
                "FFmpeg Not Found",
                "FFmpeg was not found.\n\n"
                "Fix options:\n"
                "  1. pip install imageio-ffmpeg  (easiest)\n"
                "  2. Install FFmpeg from https://ffmpeg.org and add to PATH\n\n"
                "Restart the app after fixing."
            )

    # ════════════════════════════════════════════════════════
    #  UI SKELETON
    # ════════════════════════════════════════════════════════
    def _on_cancel(self, event=None):
        """Cancel all running processes."""
        cancel_all_processes()
    
    def _build_ui(self):
        self._build_topbar()
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)
        self._build_sidebar(main)
        self._build_content(main)
        self._build_log_panel()

    # ── Top Bar ──────────────────────────────────────────────
    def _build_topbar(self):
        bar = ctk.CTkFrame(self, fg_color=BG_CARD, height=56, corner_radius=0)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        ctk.CTkLabel(bar, text="🎬  Pro Video Editor",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(side="left", padx=20)
        ctk.CTkLabel(bar, text=f"v{APP_VERSION}",
                     font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack(side="left", padx=4)

        # FFmpeg status indicator
        ff_status = "✅ FFmpeg Ready" if FFMPEG_BIN else "❌ FFmpeg Missing"
        ff_color  = SUCCESS if FFMPEG_BIN else DANGER
        ctk.CTkLabel(bar, text=ff_status,
                     font=ctk.CTkFont(size=10), text_color=ff_color).pack(side="left", padx=16)

        # ── RIGHT SIDE — pack RIGHT-to-LEFT so PROCESS lands far right ──

        # ▶ PROCESS — biggest button, top-right corner, always visible
        self.topbar_process_btn = ctk.CTkButton(
            bar, text="▶  PROCESS",
            width=160, height=42,
            fg_color="#1f6feb", hover_color="#1558c0",
            font=ctk.CTkFont(size=16, weight="bold"),
            corner_radius=6,
            command=self._batch_run)
        self.topbar_process_btn.pack(side="right", padx=10, pady=6)

        # Separator line between PROCESS and other buttons
        ctk.CTkFrame(bar, width=2, height=36, fg_color="#30363d").pack(side="right", padx=4)

        ctk.CTkButton(bar, text="⛔ Stop", width=90, height=34,
                      fg_color=DANGER, hover_color="#b62324",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=self._on_cancel).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="⚙ Settings", width=110, height=34,
                      fg_color=BG_SIDEBAR, hover_color="#30363d",
                      command=lambda: SettingsDialog(self)).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="📁 Output", width=110, height=34,
                      fg_color=BG_SIDEBAR, hover_color="#30363d",
                      command=self._pick_output_dir).pack(side="right", padx=4)
        ctk.CTkLabel(bar, textvariable=self.output_dir,
                     font=ctk.CTkFont(size=10), text_color=TEXT_MUTED).pack(side="right", padx=4)

    # ── Sidebar ──────────────────────────────────────────────
    def _build_sidebar(self, parent):
        side = ctk.CTkFrame(parent, fg_color=BG_SIDEBAR, width=265, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_propagate(False)

        ctk.CTkLabel(side, text="VIDEO FILES",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_MUTED).pack(pady=(16, 4), padx=16, anchor="w")

        btn_row = ctk.CTkFrame(side, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=4)
        ctk.CTkButton(btn_row, text="➕ Add Video", height=32,
                      command=self._add_videos).pack(side="left", fill="x", expand=True, padx=2)
        ctk.CTkButton(btn_row, text="🗑", width=36, height=32,
                      fg_color=DANGER, hover_color="#b91c1c",
                      command=self._remove_selected).pack(side="left", padx=2)

        list_frame = ctk.CTkFrame(side, fg_color=BG_DARK, corner_radius=8)
        list_frame.pack(fill="both", expand=True, padx=12, pady=6)
        self.file_listbox = tk.Listbox(
            list_frame, bg=BG_DARK, fg=TEXT_PRIMARY,
            selectbackground=ACCENT, selectforeground="white",
            borderwidth=0, highlightthickness=0,
            font=("Segoe UI", 10), activestyle="none"
        )
        self.file_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self.file_listbox.bind("<<ListboxSelect>>", self._on_file_select)

        self.info_panel = ctk.CTkFrame(side, fg_color=BG_CARD, corner_radius=8)
        self.info_panel.pack(fill="x", padx=12, pady=(0, 8))
        self.info_text = ctk.CTkLabel(self.info_panel, text="Select a file to see info",
                                       font=ctk.CTkFont(size=10), text_color=TEXT_MUTED,
                                       justify="left", wraplength=220)
        self.info_text.pack(padx=10, pady=8, anchor="w")

        ctk.CTkLabel(side, text="PROGRESS",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_MUTED).pack(padx=16, anchor="w")
        self.progress_bar = ctk.CTkProgressBar(side, height=8)
        self.progress_bar.pack(fill="x", padx=12, pady=(4, 2))
        self.progress_bar.set(0)
        self.progress_label = ctk.CTkLabel(side, text="Ready",
                                            font=ctk.CTkFont(size=10), text_color=TEXT_MUTED)
        self.progress_label.pack(padx=16, pady=(0, 12), anchor="w")

    # ── Content / Tabs ────────────────────────────────────────
    def _build_content(self, parent):
        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(content, fg_color=BG_CARD,
                                    segmented_button_fg_color=BG_SIDEBAR,
                                    segmented_button_selected_color=ACCENT)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=12)

        for name, builder in [
            ("🚀 Main",            self._build_main_tab),
            ("☁️ Automation",      self._build_automation_tab),
            ("✂️ Trim / Split",    self._build_trim_tab),
            ("🔗 Merge",           self._build_merge_tab),
            ("📝 Text & Subtitles",self._build_text_tab),
            ("🖼️ Logo",            self._build_logo_tab),
            ("🎨 Filters",         self._build_filters_tab),
            ("🔊 Audio",           self._build_audio_tab),
            ("📐 Crop & Resize",   self._build_crop_tab),
            ("🎬 Intro / Outro",   self._build_intro_outro_tab),
            ("📤 Export",          self._build_export_tab),
        ]:
            self.tabs.add(name)
            builder(self.tabs.tab(name))

    # ════════════════════════════════════════════════════════
    #  TAB 0 — MAIN  (watermark fix + Drive upload pipeline)
    # ════════════════════════════════════════════════════════
    def _build_main_tab(self, parent):
        ms = SETTINGS.get("main", {})

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # ── Row 1: Folder Scanner ─────────────────────────────
        scan_card = self._card(scroll, "📂 Downloads Folder — Scan for Videos (Recursive)")

        scan_row = ctk.CTkFrame(scan_card, fg_color="transparent")
        scan_row.pack(fill="x", pady=4)
        self.main_folder_var = tk.StringVar(
            value=ms.get("scan_dir", r"C:\Users\NADEEM\Downloads"))
        ctk.CTkEntry(scan_row, textvariable=self.main_folder_var, width=380,
                     placeholder_text=r"C:\Users\NADEEM\Downloads"
                     ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(scan_row, text="📁 Browse", width=90, height=32,
                      command=lambda: self._browse_dir(self.main_folder_var)
                      ).pack(side="left", padx=4)
        ctk.CTkButton(scan_row, text="🔍 Scan", width=90, height=32,
                      fg_color=ACCENT, hover_color="#1558c0",
                      command=self._main_scan).pack(side="left", padx=4)
        self.main_scan_status = ctk.CTkLabel(
            scan_card, text="No scan yet — click Scan to load videos",
            font=ctk.CTkFont(size=10), text_color=TEXT_MUTED)
        self.main_scan_status.pack(anchor="w", pady=(2, 0))

        # ── Row 2: Options (Logo | Trim | Export | End Screen) ─
        opts_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        opts_frame.pack(fill="x", padx=16, pady=6)

        # ── Logo Overlay card ─────────────────────────────────
        logo_card = ctk.CTkFrame(opts_frame, fg_color=BG_SIDEBAR, corner_radius=10)
        logo_card.pack(side="left", fill="y", padx=(0, 6), ipadx=8, ipady=6)
        ctk.CTkLabel(logo_card, text="🖼️ Logo Overlay",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_MUTED).pack(anchor="w", padx=12, pady=(10, 4))
        self.main_logo_en = tk.BooleanVar(value=ms.get("logo_enabled", True))
        ctk.CTkCheckBox(logo_card, text="Enable", variable=self.main_logo_en,
                        font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12)

        lp_row = ctk.CTkFrame(logo_card, fg_color="transparent")
        lp_row.pack(fill="x", padx=12, pady=(4, 2))
        ctk.CTkLabel(lp_row, text="Logo PNG:", width=70, anchor="w",
                     font=ctk.CTkFont(size=10), text_color=TEXT_MUTED).pack(side="left")
        self.main_logo_path_var = tk.StringVar(
            value=ms.get("logo_path", r"e:\Pythons\AutoMagicAI\Logo\logo.png"))
        ctk.CTkEntry(lp_row, textvariable=self.main_logo_path_var,
                     width=200, font=ctk.CTkFont(size=10)).pack(side="left", padx=4)
        ctk.CTkButton(lp_row, text="…", width=30,
                      command=lambda: self._browse_file(
                          self.main_logo_path_var,
                          [("PNG/JPG", "*.png *.jpg *.jpeg")]))\
            .pack(side="left")

        xy_row = ctk.CTkFrame(logo_card, fg_color="transparent")
        xy_row.pack(fill="x", padx=12, pady=3)
        for lbl, attr, default in [
            ("X:",   "main_logo_x",   ms.get("logo_x", "10")),
            ("Y:",   "main_logo_y",   ms.get("logo_y", "10")),
            ("W px:","main_logo_w",   str(ms.get("logo_width", 120))),
        ]:
            ctk.CTkLabel(xy_row, text=lbl, width=30, anchor="w",
                         font=ctk.CTkFont(size=10), text_color=TEXT_MUTED).pack(side="left")
            e = ctk.CTkEntry(xy_row, width=50, font=ctk.CTkFont(size=11))
            e.insert(0, default)
            e.pack(side="left", padx=(0, 8))
            setattr(self, attr, e)

        # ── Trim End card ─────────────────────────────────────
        trim_card = ctk.CTkFrame(opts_frame, fg_color=BG_SIDEBAR, corner_radius=10)
        trim_card.pack(side="left", fill="y", padx=(0, 6), ipadx=8, ipady=6)
        ctk.CTkLabel(trim_card, text="✂️ Trim End",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_MUTED).pack(anchor="w", padx=12, pady=(10, 4))
        self.main_trim_en = tk.BooleanVar(value=ms.get("trim_enabled", True))
        ctk.CTkCheckBox(trim_card, text="Enable", variable=self.main_trim_en,
                        font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12)
        trim_secs_row = ctk.CTkFrame(trim_card, fg_color="transparent")
        trim_secs_row.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(trim_secs_row, text="Cut last:",
                     font=ctk.CTkFont(size=10), text_color=TEXT_MUTED).pack(side="left")
        self.main_trim_secs = ctk.CTkComboBox(
            trim_secs_row,
            values=["2", "3", "4", "5", "6", "7", "8", "10"],
            width=70)
        self.main_trim_secs.set(str(ms.get("trim_seconds", 4)))
        self.main_trim_secs.pack(side="left", padx=6)
        ctk.CTkLabel(trim_secs_row, text="sec",
                     font=ctk.CTkFont(size=10), text_color=TEXT_MUTED).pack(side="left")

        # ── Export Quality card ───────────────────────────────
        qual_card = ctk.CTkFrame(opts_frame, fg_color=BG_SIDEBAR, corner_radius=10)
        qual_card.pack(side="left", fill="y", padx=(0, 6), ipadx=8, ipady=6)
        ctk.CTkLabel(qual_card, text="📤 Export Quality",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_MUTED).pack(anchor="w", padx=12, pady=(10, 4))
        profile_names = [f"{k}: {p.label}" for k, p in YOUTUBE_PROFILES.items()]
        self.main_quality_var = ctk.CTkComboBox(
            qual_card, values=profile_names, width=180)
        saved_q = ms.get("quality_profile", "4")
        match = next((n for n in profile_names if n.startswith(saved_q + ":")), profile_names[3])
        self.main_quality_var.set(match)
        self.main_quality_var.pack(padx=12, pady=(0, 6))

        # ── End Screen card ───────────────────────────────────
        end_card = ctk.CTkFrame(opts_frame, fg_color=BG_SIDEBAR, corner_radius=10)
        end_card.pack(side="left", fill="y", ipadx=8, ipady=6)
        ctk.CTkLabel(end_card, text="🎬 End Screen",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_MUTED).pack(anchor="w", padx=12, pady=(10, 4))
        self.main_end_en = tk.BooleanVar(value=ms.get("ending_enabled", False))
        ctk.CTkCheckBox(end_card, text="Append ending video", variable=self.main_end_en,
                        font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12)
        end_row = ctk.CTkFrame(end_card, fg_color="transparent")
        end_row.pack(fill="x", padx=12, pady=4)
        self.main_end_path_var = tk.StringVar(value=ms.get("ending_path", ""))
        ctk.CTkEntry(end_row, textvariable=self.main_end_path_var,
                     placeholder_text="Path to ending.mp4", width=200,
                     font=ctk.CTkFont(size=10)).pack(side="left", padx=(0, 4))
        ctk.CTkButton(end_row, text="…", width=30,
                      command=lambda: self._browse_file(
                          self.main_end_path_var,
                          [("Video", "*.mp4 *.mov *.mkv")]))\
            .pack(side="left")

        # ── Row 3: Post-Process Options ───────────────────────
        post_card = self._card(scroll, "⚙️ Post-Process Options")
        post_row = ctk.CTkFrame(post_card, fg_color="transparent")
        post_row.pack(fill="x", pady=2)

        self.main_delete_var = tk.BooleanVar(value=ms.get("delete_source", False))
        ctk.CTkCheckBox(post_row, text="🗑️ Delete source after processing",
                        variable=self.main_delete_var,
                        font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 24))

        self.main_drive_var = tk.BooleanVar(value=ms.get("upload_drive", True))
        ctk.CTkCheckBox(post_row, text="☁️ Upload to Google Drive",
                        variable=self.main_drive_var,
                        font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 12))

        drive_id_row = ctk.CTkFrame(post_card, fg_color="transparent")
        drive_id_row.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(drive_id_row, text="Drive Root Folder ID:",
                     font=ctk.CTkFont(size=10), text_color=TEXT_MUTED,
                     width=150, anchor="w").pack(side="left")
        self.main_drive_id_var = tk.StringVar(
            value=ms.get("drive_folder_id",
                         SETTINGS.get("drive_folder_id", "")))
        ctk.CTkEntry(drive_id_row, textvariable=self.main_drive_id_var,
                     placeholder_text="Google Drive Folder ID",
                     width=280, font=ctk.CTkFont(size=10)).pack(side="left", padx=6)
        ctk.CTkLabel(drive_id_row,
                     text="Mirrors local subfolder: Downloads/ABC → Drive/ABC",
                     font=ctk.CTkFont(size=9), text_color=TEXT_MUTED).pack(side="left", padx=8)

        # ── Row 4: Video Progress List ────────────────────────
        list_card_outer = ctk.CTkFrame(scroll, fg_color=BG_SIDEBAR, corner_radius=10)
        list_card_outer.pack(fill="both", expand=True, padx=16, pady=6)

        list_hdr = ctk.CTkFrame(list_card_outer, fg_color="transparent")
        list_hdr.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(list_hdr, text="📋 VIDEO LIST",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_MUTED).pack(side="left")
        self.main_count_label = ctk.CTkLabel(
            list_hdr, text="",
            font=ctk.CTkFont(size=10), text_color=TEXT_MUTED)
        self.main_count_label.pack(side="left", padx=12)

        btn_row2 = ctk.CTkFrame(list_card_outer, fg_color="transparent")
        btn_row2.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkButton(btn_row2, text="Select All", width=90, height=26,
                      command=lambda: self.main_listbox.selection_set(0, "end")
                      ).pack(side="left", padx=2)
        ctk.CTkButton(btn_row2, text="Select None", width=90, height=26,
                      command=lambda: self.main_listbox.selection_clear(0, "end")
                      ).pack(side="left", padx=2)

        list_frame = ctk.CTkFrame(list_card_outer, fg_color=BG_DARK, corner_radius=8)
        list_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        self.main_listbox = tk.Listbox(
            list_frame, bg=BG_DARK, fg=TEXT_PRIMARY,
            selectbackground=ACCENT, borderwidth=0,
            highlightthickness=0, font=("Consolas", 10),
            height=10, selectmode="extended",
        )
        sb = tk.Scrollbar(list_frame, orient="vertical",
                          command=self.main_listbox.yview)
        self.main_listbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.main_listbox.pack(fill="both", expand=True, padx=4, pady=4)

        # ── Bottom Action Buttons ─────────────────────────────
        act_row = ctk.CTkFrame(scroll, fg_color="transparent")
        act_row.pack(fill="x", padx=16, pady=(4, 8))

        ctk.CTkButton(act_row, text="⛔ STOP", width=100, height=42,
                      fg_color=DANGER, hover_color="#b91c1c",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._on_cancel).pack(side="left", padx=4)

        self.main_run_btn = ctk.CTkButton(
            act_row, text="▶ PROCESS ALL", width=200, height=42,
            fg_color="#1f6feb", hover_color="#1558c0",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._main_run, state="disabled")
        self.main_run_btn.pack(side="right", padx=4)

        self.main_overall_bar = ctk.CTkProgressBar(
            scroll, height=10, progress_color=ACCENT)
        self.main_overall_bar.pack(fill="x", padx=16, pady=(0, 4))
        self.main_overall_bar.set(0)

        self.main_status_label = ctk.CTkLabel(
            scroll, text="Scan a folder to get started.",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED)
        self.main_status_label.pack(anchor="w", padx=16, pady=(0, 6))

        # Internal state
        self._main_files: list[dict] = []   # [{path, subfolder, status, label}]

    # ════════════════════════════════════════════════════════
    #  MAIN TAB — KEPT FOR BACKWARD COMPAT (old batch tab)
    # ════════════════════════════════════════════════════════
    def _build_batch_tab(self, parent):  # kept but not used — replaced by _build_main_tab
        pass

    # ════════════════════════════════════════════════════════
    #  MAIN TAB — SCAN ENGINE
    # ════════════════════════════════════════════════════════
    def _main_scan(self) -> None:
        """Recursively walks the Downloads folder and loads all video files."""
        root = Path(self.main_folder_var.get().strip())
        if not root.exists():
            try:
                root.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        if not root.exists():
            self.main_scan_status.configure(
                text=f"Folder not found: {root}", text_color=DANGER)
            return

        # Collect all video files recursively
        found = []
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                # Determine subfolder name relative to root
                rel    = p.relative_to(root)
                parts  = rel.parts
                subfolder = parts[0] if len(parts) > 1 else ""
                found.append({
                    "path":      p,
                    "subfolder": subfolder,
                    "status":    "pending",
                    "error":     "",
                })

        self._main_files = found

        # Update listbox
        self.main_listbox.delete(0, "end")
        for entry in found:
            sz = format_size(entry["path"].stat().st_size)
            sub = f"[{entry['subfolder']}]  " if entry["subfolder"] else ""
            self.main_listbox.insert(
                "end",
                f"  ⏳ Pending   {sub}{entry['path'].name}   {sz}")

        n = len(found)
        self.main_count_label.configure(text=f"{n} video(s) found")
        self.main_scan_status.configure(
            text=f"Scanned: {root}  —  {n} video(s) found",
            text_color=SUCCESS if n else WARNING)
        if n:
            self.main_run_btn.configure(state="normal")
        else:
            self.main_run_btn.configure(state="disabled")
        # Save scan_dir to settings
        SETTINGS.setdefault("main", {})["scan_dir"] = str(root)
        save_settings()

    # ────────────────────────────────────────────────────────
    def _main_update_item(self, idx: int, status: str, extra: str = "") -> None:
        """Update a single row in the video list with a coloured status prefix."""
        icons = {
            "pending":    "  ⏳ Pending   ",
            "processing": "  🔄 Processing",
            "done":       "  ✅ Done      ",
            "failed":     "  ❌ Failed    ",
            "skipped":    "  ⏭ Skipped   ",
        }
        entry = self._main_files[idx]
        entry["status"] = status
        sz  = format_size(entry["path"].stat().st_size
                          if entry["path"].exists() else 0)
        sub = f"[{entry['subfolder']}]  " if entry["subfolder"] else ""
        pfx = icons.get(status, f"  {status}  ")
        line = f"{pfx}  {sub}{entry['path'].name}   {sz}"
        if extra:
            line += f"  — {extra}"

        def _do():
            self.main_listbox.delete(idx)
            self.main_listbox.insert(idx, line)
            # Colour the row
            colors = {"done": SUCCESS, "failed": DANGER,
                      "processing": WARNING, "skipped": TEXT_MUTED}
            self.main_listbox.itemconfig(idx, fg=colors.get(status, TEXT_PRIMARY))
        self.after(0, _do)

    # ════════════════════════════════════════════════════════
    #  MAIN TAB — PROCESSING ENGINE
    # ════════════════════════════════════════════════════════
    def _main_run(self) -> None:
        if not FFMPEG_BIN:
            messagebox.showerror("FFmpeg Not Found",
                "FFmpeg is required.\nRun: pip install imageio-ffmpeg")
            return
        if not self._main_files:
            messagebox.showwarning("No Videos", "Scan a folder first.")
            return

        # Which indices to process?
        sel = list(self.main_listbox.curselection())
        indices = sel if sel else list(range(len(self._main_files)))

        # Read settings from UI
        do_logo   = self.main_logo_en.get()
        logo_path = self.main_logo_path_var.get().strip()
        logo_x    = self.main_logo_x.get().strip() or "10"
        logo_y    = self.main_logo_y.get().strip() or "10"
        try:
            logo_w = int(self.main_logo_w.get().strip() or "120")
        except ValueError:
            logo_w = 120

        do_trim   = self.main_trim_en.get()
        try:
            trim_sec = int(self.main_trim_secs.get())
        except ValueError:
            trim_sec = 4

        key_str   = self.main_quality_var.get().split(":")[0].strip()
        profile   = YOUTUBE_PROFILES.get(key_str, YOUTUBE_PROFILES["4"])

        do_ending  = self.main_end_en.get()
        ending_path = self.main_end_path_var.get().strip()

        do_delete = self.main_delete_var.get()
        do_drive  = self.main_drive_var.get()
        drive_root = self.main_drive_id_var.get().strip()

        # Persist settings
        ms = SETTINGS.setdefault("main", {})
        ms.update({
            "logo_enabled":   do_logo,
            "logo_path":      logo_path,
            "logo_x":         logo_x,
            "logo_y":         logo_y,
            "logo_width":     logo_w,
            "trim_enabled":   do_trim,
            "trim_seconds":   trim_sec,
            "quality_profile":key_str,
            "ending_enabled": do_ending,
            "ending_path":    ending_path,
            "delete_source":  do_delete,
            "upload_drive":   do_drive,
            "drive_folder_id":drive_root,
            "scan_dir":       self.main_folder_var.get().strip(),
        })
        save_settings()

        _CANCEL_EVENT.clear()
        self.main_run_btn.configure(state="disabled", text="⏳ Running...")
        self.main_overall_bar.set(0)

        def worker():
            total = len(indices)
            ok_count = fail_count = 0
            for n, idx in enumerate(indices):
                if _CANCEL_EVENT.is_set():
                    self._main_update_item(idx, "skipped", "cancelled")
                    continue
                self.after(0, self.main_status_label.configure,
                           {"text": f"[{n+1}/{total}] {self._main_files[idx]['path'].name}"})
                self.after(0, self.main_overall_bar.set, n / total)
                ok = self._main_process_one(
                    idx, profile,
                    do_logo, logo_path, logo_x, logo_y, logo_w,
                    do_trim, trim_sec,
                    do_ending, ending_path,
                    do_delete, do_drive, drive_root)
                if ok:
                    ok_count += 1
                else:
                    fail_count += 1

            self.after(0, self.main_overall_bar.set, 1.0)
            summary = f"Done — {ok_count} OK, {fail_count} failed."
            self.after(0, self.main_status_label.configure, {"text": summary})
            self.after(0, self.main_run_btn.configure,
                       {"state": "normal", "text": "▶ PROCESS ALL"})
            self.after(0, lambda: messagebox.showinfo("Batch Complete", summary))

        threading.Thread(target=worker, daemon=True).start()

    # ────────────────────────────────────────────────────────
    def _main_process_one(
        self, idx: int, profile: "Profile",
        do_logo: bool, logo_path: str, logo_x: str, logo_y: str, logo_w: int,
        do_trim: bool, trim_sec: int,
        do_ending: bool, ending_path: str,
        do_delete: bool, do_drive: bool, drive_root: str,
    ) -> bool:
        """
        Process one video:
          1. Trim last N seconds  (if enabled)
          2. Logo overlay at (x,y)  (if enabled)
          3. Encode to chosen profile
          4. Replace source (optionally delete original)
          5. Append ending (if enabled)
          6. Upload to Drive with subfolder mirroring  (if enabled)
        Returns True on success.
        """
        entry = self._main_files[idx]
        src   = entry["path"]

        self._main_update_item(idx, "processing")
        self._log(f"[MAIN] Processing: {src.name}")
        ff = FFMPEG_BIN or "ffmpeg"

        try:
            duration, has_audio = probe_duration_and_audio(src)
            if duration <= 0:
                raise RuntimeError("Could not determine video duration.")

            # ── Output goes to same folder as source ─────────
            tmp_out = src.with_suffix(".___proc___.mp4")
            if tmp_out.exists():
                tmp_out.unlink()

            # ── Build filter_complex ──────────────────────────
            end_t = max(0.01, duration - trim_sec) if do_trim else duration

            # Video filter chain starting point
            if do_logo and logo_path and Path(logo_path).exists():
                logo_f = (f"[1:v]scale={logo_w}:-1,format=rgba[logo]")
                vf_chain = (
                    f"[0:v]trim=start=0:end={end_t},"
                    f"setpts=PTS-STARTPTS,"
                    f"scale=-2:{profile.height},"
                    f"fps={profile.fps},"
                    f"format=yuv420p,settb=AVTB[base];"
                    f"{logo_f};"
                    f"[base][logo]overlay=x={logo_x}:y={logo_y}[v]"
                )
                if has_audio:
                    vf_chain += f";[0:a]atrim=start=0:end={end_t},asetpts=PTS-STARTPTS[a]"
                cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
                       "-i", str(src), "-i", logo_path,
                       "-filter_complex", vf_chain, "-map", "[v]"]
            else:
                vf_chain = (
                    f"[0:v]trim=start=0:end={end_t},"
                    f"setpts=PTS-STARTPTS,"
                    f"scale=-2:{profile.height},"
                    f"fps={profile.fps},"
                    f"format=yuv420p,settb=AVTB[v]"
                )
                if has_audio:
                    vf_chain += f";[0:a]atrim=start=0:end={end_t},asetpts=PTS-STARTPTS[a]"
                cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
                       "-i", str(src),
                       "-filter_complex", vf_chain, "-map", "[v]"]

            cmd += (["-map", "[a]"] if has_audio else ["-an"])
            cmd += ["-c:v", "libx264", "-preset", "veryfast",
                    "-crf", str(profile.crf),
                    "-pix_fmt", "yuv420p", "-profile:v", "high",
                    "-movflags", "+faststart"]
            if has_audio:
                cmd += ["-c:a", "aac", "-b:a", profile.audio_bitrate, "-ar", "48000"]
            cmd.append(str(tmp_out))

            rc, _, err = _run_capture(cmd, cancel_event=_CANCEL_EVENT)
            if rc != 0:
                raise RuntimeError(f"FFmpeg failed: {err[-400:]}")

            # ── Append ending clip ────────────────────────────
            if do_ending and ending_path and Path(ending_path).exists():
                self._log(f"[MAIN] Appending ending to {src.name}")
                final_tmp = src.with_suffix(".___end___.mp4")
                ok2, err2 = concat_ending(tmp_out, Path(ending_path),
                                          final_tmp, profile)
                tmp_out.unlink(missing_ok=True)
                if not ok2:
                    raise RuntimeError(f"Ending concat failed: {err2}")
                tmp_out = final_tmp

            # ── Replace source ────────────────────────────────
            if do_delete:
                try:
                    src.unlink()
                except Exception:
                    pass
                tmp_out.rename(src)
                out_path = src
            else:
                out_path = src.with_stem(src.stem + "_processed")
                if out_path.exists():
                    out_path.unlink()
                tmp_out.rename(out_path)

            self._log(f"[MAIN] Saved: {out_path.name}  ({format_size(out_path.stat().st_size)})")

            # ── Upload to Drive ───────────────────────────────
            if do_drive and drive_root:
                token = get_oauth_token()
                if not token:
                    self._main_update_item(idx, "done", "Drive skip—not signed in")
                    return True
                subfolder = entry.get("subfolder", "")
                folder_id = drive_root
                if subfolder:
                    self._log(f"[MAIN] Drive: get/create subfolder '{subfolder}'")
                    sub_id = drive_get_or_create_subfolder(token, drive_root, subfolder)
                    if sub_id:
                        folder_id = sub_id
                self._log(f"[MAIN] Uploading to Drive: {out_path.name}")
                self._main_update_item(idx, "processing", "uploading...")
                drive_url = drive_upload_file(out_path, folder_id)
                self._log(f"[MAIN] Drive URL: {drive_url}")
                self._main_update_item(idx, "done", f"Drive OK")
            else:
                self._main_update_item(idx, "done")

            return True

        except Exception as exc:
            err_msg = str(exc)[:80]
            self._log(f"[MAIN] FAILED {src.name}: {err_msg}")
            self._main_update_item(idx, "failed", err_msg)
            # Clean up temp files
            for tmp in [src.with_suffix(".___proc___.mp4"),
                        src.with_suffix(".___end___.mp4")]:
                try:
                    tmp.unlink()
                except Exception:
                    pass
            return False


    #  TAB 1 — AUTOMATION (Drive + Sheet integration)
    # ════════════════════════════════════════════════════════
    def _build_automation_tab(self, parent):
        self._section_title(parent, "☁️ Automation — Drive + Sheet Integration")

        # ── Google Sign In ────────────────────────────────────────
        auth_card = self._card(parent, "🔐 Google Account")

        self.auto_auth_status = ctk.CTkLabel(
            auth_card,
            text="⚠ Not signed in — click Sign In to connect Google Drive",
            font=ctk.CTkFont(size=11), text_color=WARNING)
        self.auto_auth_status.pack(anchor="w", pady=(0, 6))

        auth_btn_row = ctk.CTkFrame(auth_card, fg_color="transparent")
        auth_btn_row.pack(fill="x")
        self.auto_signin_btn = ctk.CTkButton(
            auth_btn_row, text="🔐 Sign In with Google",
            width=180, height=34, fg_color=ACCENT,
            command=self._auto_signin)
        self.auto_signin_btn.pack(side="left", padx=4)
        ctk.CTkButton(auth_btn_row, text="Sign Out", width=100, height=34,
                      fg_color=BG_SIDEBAR, hover_color="#30363d",
                      command=self._auto_signout).pack(side="left", padx=4)

        # Check if already signed in
        if get_oauth_token():
            self.auto_auth_status.configure(
                text="✅ Signed in to Google Drive", text_color=SUCCESS)

        # ── Apps Script URL ───────────────────────────────────────
        cfg_card = self._card(parent, "⚙️ Configuration")

        r1 = ctk.CTkFrame(cfg_card, fg_color="transparent")
        r1.pack(fill="x", pady=3)
        ctk.CTkLabel(r1, text="Apps Script URL:", width=160, anchor="w",
                     font=ctk.CTkFont(size=11)).pack(side="left")
        self.auto_script_url = ctk.CTkEntry(r1, width=440,
                                             placeholder_text="https://script.google.com/macros/s/.../exec")
        self.auto_script_url.insert(0, SETTINGS.get("apps_script_url", ""))
        self.auto_script_url.pack(side="left", padx=8)

        r2 = ctk.CTkFrame(cfg_card, fg_color="transparent")
        r2.pack(fill="x", pady=3)
        ctk.CTkLabel(r2, text="Drive Folder ID:", width=160, anchor="w",
                     font=ctk.CTkFont(size=11)).pack(side="left")
        self.auto_folder_id = ctk.CTkEntry(r2, width=440,
                                            placeholder_text="1iYR7cw9kihjJSYQnpBBCqFEJ7oWQDb00")
        self.auto_folder_id.insert(0, SETTINGS.get("drive_folder_id", ""))
        self.auto_folder_id.pack(side="left", padx=8)

        ctk.CTkButton(cfg_card, text="💾 Save Config", width=140, height=32,
                      fg_color=SUCCESS, hover_color="#196129",
                      command=self._auto_save_config).pack(anchor="w", pady=(6, 2))

        # ── Manual Upload ──────────────────────────────────────────
        upload_card = self._card(parent, "☁️ Manual Upload — Select File → Story → Upload")

        sel_row = ctk.CTkFrame(upload_card, fg_color="transparent")
        sel_row.pack(fill="x", pady=4)

        ctk.CTkButton(sel_row, text="📁 Select Processed Video",
                      width=200, height=34, command=self._auto_pick_video
                      ).pack(side="left", padx=4)
        self.auto_video_label = ctk.CTkLabel(
            sel_row, text="No file selected",
            font=ctk.CTkFont(size=10), text_color=TEXT_MUTED)
        self.auto_video_label.pack(side="left", padx=8)

        story_row = ctk.CTkFrame(upload_card, fg_color="transparent")
        story_row.pack(fill="x", pady=4)
        ctk.CTkLabel(story_row, text="Match to Story:", width=120, anchor="w",
                     font=ctk.CTkFont(size=11)).pack(side="left")
        self.auto_story_var = tk.StringVar(value="-- Fetch stories first --")
        self.auto_story_combo = ctk.CTkComboBox(
            story_row, variable=self.auto_story_var,
            values=["-- Fetch stories first --"], width=360)
        self.auto_story_combo.pack(side="left", padx=8)
        ctk.CTkButton(story_row, text="🔄 Fetch", width=80, height=30,
                      command=self._auto_fetch_stories).pack(side="left", padx=4)

        upload_btn_row = ctk.CTkFrame(upload_card, fg_color="transparent")
        upload_btn_row.pack(fill="x", pady=6)
        ctk.CTkButton(upload_btn_row, text="☁️ UPLOAD TO DRIVE + UPDATE SHEET",
                      width=300, height=40,
                      fg_color=ACCENT, hover_color="#1558c0",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=self._auto_upload).pack(side="left", padx=4)

        self.auto_upload_progress = ctk.CTkProgressBar(upload_card, height=8)
        self.auto_upload_progress.pack(fill="x", pady=(6, 2))
        self.auto_upload_progress.set(0)

        self.auto_upload_status = ctk.CTkLabel(
            upload_card, text="",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED)
        self.auto_upload_status.pack(anchor="w", pady=2)

        # ── Auto-Watch ────────────────────────────────────────────
        watch_card = self._card(parent, "👁️ Auto-Watch Pending Folder")

        ctk.CTkLabel(watch_card,
                     text="When enabled: any new video dropped in Pending folder\n"
                          "will be auto-processed, uploaded to Drive, and sheet updated.",
                     font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
                     justify="left").pack(anchor="w", pady=(0, 6))

        watch_row = ctk.CTkFrame(watch_card, fg_color="transparent")
        watch_row.pack(fill="x")
        self.auto_watch_var = tk.BooleanVar(value=SETTINGS.get("auto_watch", False))
        ctk.CTkCheckBox(watch_row, text="Enable Auto-Watch",
                        variable=self.auto_watch_var,
                        font=ctk.CTkFont(size=11),
                        command=self._auto_toggle_watch).pack(side="left", padx=4)
        self.auto_watch_status = ctk.CTkLabel(
            watch_row, text="● Inactive",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED)
        self.auto_watch_status.pack(side="left", padx=12)

        # ── Log ───────────────────────────────────────────────────
        log_card = self._card(parent, "📋 Automation Log")
        self.auto_log = ctk.CTkTextbox(
            log_card, height=120,
            font=ctk.CTkFont(size=10, family="Consolas"),
            fg_color=BG_DARK, text_color="#c9d1d9",
            border_width=1, border_color="#30363d")
        self.auto_log.pack(fill="both", expand=True)
        self.auto_log.insert("end", "[VEdit v3.0] Automation tab ready.\n")

        # State
        self._auto_video_path = None
        self._auto_stories    = []
        self._watch_thread    = None
        self._watch_stop      = threading.Event()

    # ── Automation helpers ────────────────────────────────────────
    def _auto_log(self, msg: str) -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.after(0, lambda: (
            self.auto_log.insert("end", f"[{ts}] {msg}\n"),
            self.auto_log.see("end")
        ))

    def _auto_signin(self) -> None:
        self.auto_auth_status.configure(text="⏳ Opening browser...", text_color=WARNING)

        def on_ok(token):
            self.after(0, lambda: self.auto_auth_status.configure(
                text="✅ Signed in to Google Drive", text_color=SUCCESS))
            self._auto_log("✅ Google sign-in successful.")

        def on_err(msg):
            self.after(0, lambda: self.auto_auth_status.configure(
                text=f"❌ Sign-in failed: {msg}", text_color=DANGER))
            self._auto_log(f"❌ Sign-in failed: {msg}")

        start_oauth_flow(on_success=on_ok, on_error=on_err)

    def _auto_signout(self) -> None:
        SETTINGS["oauth_token"]  = ""
        SETTINGS["oauth_expiry"] = 0
        _oauth_token_cache.clear()
        save_settings()
        self.auto_auth_status.configure(
            text="⚠ Signed out", text_color=WARNING)
        self._auto_log("Signed out of Google.")

    def _auto_save_config(self) -> None:
        SETTINGS["apps_script_url"] = self.auto_script_url.get().strip()
        SETTINGS["drive_folder_id"] = self.auto_folder_id.get().strip()
        save_settings()
        self._auto_log("✅ Config saved to settings.json")
        messagebox.showinfo("✅ Saved", "Automation config saved!")

    def _auto_pick_video(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Processed Video",
            filetypes=[("Video files","*.mp4 *.mov *.mkv *.webm"), ("All","*.*")])
        if path:
            self._auto_video_path = Path(path)
            self.auto_video_label.configure(
                text=f"📎 {self._auto_video_path.name}  "
                     f"({self._auto_video_path.stat().st_size // (1024*1024):.1f} MB)",
                text_color=TEXT_PRIMARY)
            self._auto_log(f"Selected: {self._auto_video_path.name}")

    def _auto_fetch_stories(self) -> None:
        url = self.auto_script_url.get().strip() or SETTINGS.get("apps_script_url","")
        if not url:
            messagebox.showwarning("Missing", "Enter Apps Script URL first.")
            return
        self._auto_log("Fetching stories from sheet...")
        def worker():
            stories = sheet_fetch_stories(url)
            self._auto_stories = stories
            titles  = [f"{s.get('Title','?')} [{s.get('Status','?')}]"
                       for s in stories]
            if not titles:
                titles = ["-- No stories found --"]
            self.after(0, lambda: self.auto_story_combo.configure(values=titles))
            self.after(0, lambda: self.auto_story_combo.set(titles[0]))
            self._auto_log(f"✅ Fetched {len(stories)} stories.")
        threading.Thread(target=worker, daemon=True).start()

    def _auto_upload(self) -> None:
        if not self._auto_video_path or not self._auto_video_path.exists():
            messagebox.showwarning("No file", "Select a video file first.")
            return
        token = get_oauth_token()
        if not token:
            messagebox.showwarning("Not signed in", "Sign in with Google first.")
            return

        folder_id  = self.auto_folder_id.get().strip() or SETTINGS.get("drive_folder_id","")
        script_url = self.auto_script_url.get().strip() or SETTINGS.get("apps_script_url","")

        # Find selected story title
        sel_text = self.auto_story_var.get()
        story_title = sel_text.split(" [")[0] if "[" in sel_text else sel_text

        self.auto_upload_status.configure(text="⏳ Uploading to Drive...", text_color=WARNING)
        self.auto_upload_progress.set(0)

        def worker():
            try:
                self._auto_log(f"Uploading: {self._auto_video_path.name}")

                def on_pct(pct):
                    self.after(0, lambda: self.auto_upload_progress.set(pct / 100))
                    self.after(0, lambda: self.auto_upload_status.configure(
                        text=f"⏳ Uploading... {pct}%", text_color=WARNING))

                drive_url = drive_upload_file(self._auto_video_path, folder_id, on_pct)

                self._auto_log(f"✅ Uploaded: {drive_url}")

                # Update sheet
                if script_url and story_title:
                    self._auto_log(f"Updating sheet for: {story_title}")
                    ok = sheet_save_video_url(story_title, drive_url, script_url)
                    if ok:
                        self._auto_log("✅ Sheet updated — status set to Ready")
                    else:
                        self._auto_log("⚠ Sheet update failed (Drive upload OK)")

                self.after(0, lambda: self.auto_upload_status.configure(
                    text=f"✅ Done! {drive_url[:60]}...", text_color=SUCCESS))
                self.after(0, lambda: self.auto_upload_progress.set(1.0))
                messagebox.showinfo("✅ Upload Complete",
                                    f"Video uploaded!\n\n{drive_url}\n\n"
                                    f"Sheet updated for: {story_title}")
            except Exception as e:
                self._auto_log(f"❌ Error: {e}")
                self.after(0, lambda: self.auto_upload_status.configure(
                    text=f"❌ {e}", text_color=DANGER))

        threading.Thread(target=worker, daemon=True).start()

    def _auto_toggle_watch(self) -> None:
        if self.auto_watch_var.get():
            self._start_folder_watch()
        else:
            self._stop_folder_watch()

    def _start_folder_watch(self) -> None:
        self._watch_stop.clear()
        self.auto_watch_status.configure(text="● Watching...", text_color=SUCCESS)
        self._auto_log(f"👁 Watching: {SETTINGS['pending_dir']}")

        def watcher():
            pending = Path(SETTINGS["pending_dir"])
            seen    = set(p.name for p in pending.iterdir()
                          if p.is_file() and p.suffix.lower() in VIDEO_EXTS) \
                      if pending.exists() else set()
            while not self._watch_stop.is_set():
                time.sleep(5)
                if not pending.exists():
                    continue
                current = set(p.name for p in pending.iterdir()
                              if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
                new_files = current - seen
                for fname in new_files:
                    fpath = pending / fname
                    self._auto_log(f"🆕 New file detected: {fname}")
                    # Wait for file to finish copying (size stable)
                    prev_size = -1
                    for _ in range(12):   # wait up to 60s
                        time.sleep(5)
                        try:
                            sz = fpath.stat().st_size
                        except Exception:
                            sz = -1
                        if sz == prev_size and sz > 0:
                            break
                        prev_size = sz
                    # Set as current video and trigger batch for this file
                    self._auto_video_path = fpath
                    self.after(0, lambda f=fpath: self.auto_video_label.configure(
                        text=f"📎 {f.name}", text_color=TEXT_PRIMARY))
                    self._auto_log(f"▶ Auto-processing: {fname}")
                    # Derive story title from filename (remove extension, replace _ with space)
                    stem = fpath.stem.replace("_", " ").replace("-", " ")
                    self.after(0, lambda t=stem: self.auto_story_var.set(t))
                seen = current

        self._watch_thread = threading.Thread(target=watcher, daemon=True)
        self._watch_thread.start()

    def _stop_folder_watch(self) -> None:
        self._watch_stop.set()
        self.auto_watch_status.configure(text="● Inactive", text_color=TEXT_MUTED)
        self._auto_log("👁 Folder watch stopped.")

    # ════════════════════════════════════════════════════════
    #  TAB 2 — TRIM / SPLIT  (was TAB 1)
    # ════════════════════════════════════════════════════════
    def _build_trim_tab(self, parent):
        self._section_title(parent, "✂️ Trim, Cut & Split Video")

        card = self._card(parent, "Trim: Set Start & End Time")
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="Start (HH:MM:SS or seconds):", width=200, anchor="w").pack(side="left")
        self.trim_start = ctk.CTkEntry(row, placeholder_text="00:00:00", width=140)
        self.trim_start.pack(side="left", padx=8)
        ctk.CTkLabel(row, text="End:", anchor="w").pack(side="left")
        self.trim_end = ctk.CTkEntry(row, placeholder_text="00:01:30", width=140)
        self.trim_end.pack(side="left", padx=8)
        ctk.CTkButton(card, text="✂️ Trim Video", height=36,
                      command=self._do_trim).pack(pady=8, anchor="w")

        card2 = self._card(parent, "Split by Fixed Interval (Frame-based)")
        ctk.CTkLabel(card2, text="e.g. enter 10 to split a combined video into 10-min chunks",
                     font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack(anchor="w", pady=2)
        row2 = ctk.CTkFrame(card2, fg_color="transparent")
        row2.pack(fill="x", pady=6)
        ctk.CTkLabel(row2, text="Split every (minutes):", width=160, anchor="w").pack(side="left")
        self.split_mins = ctk.CTkEntry(row2, placeholder_text="10", width=80)
        self.split_mins.pack(side="left", padx=8)
        ctk.CTkButton(card2, text="🔪 Split Video into Chunks", height=36,
                      command=self._do_split).pack(pady=8, anchor="w")

        card3 = self._card(parent, "Cut Out a Middle Section")
        row3 = ctk.CTkFrame(card3, fg_color="transparent")
        row3.pack(fill="x", pady=4)
        ctk.CTkLabel(row3, text="Remove FROM:", width=120, anchor="w").pack(side="left")
        self.cut_from = ctk.CTkEntry(row3, placeholder_text="00:01:00", width=120)
        self.cut_from.pack(side="left", padx=8)
        ctk.CTkLabel(row3, text="TO:", anchor="w").pack(side="left")
        self.cut_to = ctk.CTkEntry(row3, placeholder_text="00:02:00", width=120)
        self.cut_to.pack(side="left", padx=8)
        ctk.CTkButton(card3, text="🗂 Remove Section", height=36,
                      command=self._do_cut_section).pack(pady=8, anchor="w")

    # ════════════════════════════════════════════════════════
    #  TAB 2 — MERGE
    # ════════════════════════════════════════════════════════
    def _build_merge_tab(self, parent):
        self._section_title(parent, "🔗 Merge / Join Multiple Videos")
        card = self._card(parent, "Files to Merge (in order shown below)")
        ctk.CTkLabel(card, text="Use ⬆ / ⬇ to reorder. All sidebar files will be merged.",
                     font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack(anchor="w", pady=2)
        self.merge_listbox = tk.Listbox(card, bg=BG_DARK, fg=TEXT_PRIMARY,
                                         selectbackground=ACCENT,
                                         borderwidth=0, highlightthickness=0,
                                         font=("Segoe UI", 10), height=8)
        self.merge_listbox.pack(fill="x", pady=6)
        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", pady=4)
        ctk.CTkButton(btn_row, text="🔄 Refresh", width=120,
                      command=self._refresh_merge_list).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="⬆ Move Up", width=100,
                      command=lambda: self._move_merge_item(-1)).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="⬇ Move Down", width=100,
                      command=lambda: self._move_merge_item(1)).pack(side="left", padx=4)

        card2 = self._card(parent, "Output Settings")
        row = ctk.CTkFrame(card2, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="Output filename:", width=140, anchor="w").pack(side="left")
        self.merge_out_name = ctk.CTkEntry(row, placeholder_text="merged_output.mp4", width=220)
        self.merge_out_name.pack(side="left", padx=8)
        ctk.CTkButton(card2, text="🔗 Merge All Videos", height=40,
                      fg_color=SUCCESS, hover_color="#196129",
                      command=self._do_merge).pack(pady=10, anchor="w")

    # ════════════════════════════════════════════════════════
    #  TAB 3 — TEXT & SUBTITLES
    # ════════════════════════════════════════════════════════
    def _build_text_tab(self, parent):
        self._section_title(parent, "📝 Add Text Overlay or Subtitles")
        card = self._card(parent, "Text Overlay")
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", pady=4)
        ctk.CTkLabel(row1, text="Text:", width=80, anchor="w").pack(side="left")
        self.text_content = ctk.CTkEntry(row1, placeholder_text="Your text here...", width=300)
        self.text_content.pack(side="left", padx=8)

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", pady=4)
        ctk.CTkLabel(row2, text="Position:", width=80, anchor="w").pack(side="left")
        self.text_pos = ctk.CTkComboBox(row2,
            values=["bottom-center","top-center","center",
                    "bottom-left","bottom-right","top-left","top-right"], width=160)
        self.text_pos.set("bottom-center")
        self.text_pos.pack(side="left", padx=8)
        ctk.CTkLabel(row2, text="Font Size:", anchor="w").pack(side="left", padx=(16,4))
        self.text_size = ctk.CTkEntry(row2, placeholder_text="36", width=60)
        self.text_size.pack(side="left")

        row3 = ctk.CTkFrame(card, fg_color="transparent")
        row3.pack(fill="x", pady=4)
        ctk.CTkLabel(row3, text="Start (sec):", width=80, anchor="w").pack(side="left")
        self.text_start = ctk.CTkEntry(row3, placeholder_text="0", width=80)
        self.text_start.pack(side="left", padx=8)
        ctk.CTkLabel(row3, text="Duration (sec):", anchor="w").pack(side="left")
        self.text_dur = ctk.CTkEntry(row3, placeholder_text="5", width=80)
        self.text_dur.pack(side="left", padx=8)
        ctk.CTkLabel(row3, text="Color:", anchor="w").pack(side="left")
        self.text_color_var = ctk.CTkEntry(row3, placeholder_text="white", width=80)
        self.text_color_var.pack(side="left", padx=8)
        ctk.CTkButton(card, text="📝 Add Text to Video", height=36,
                      command=self._do_add_text).pack(pady=8, anchor="w")

        card2 = self._card(parent, "Burn-in SRT Subtitles")
        row_s = ctk.CTkFrame(card2, fg_color="transparent")
        row_s.pack(fill="x", pady=4)
        ctk.CTkLabel(row_s, text="SRT File:", width=80, anchor="w").pack(side="left")
        self.srt_path = ctk.CTkEntry(row_s, placeholder_text="Path to .srt file", width=300)
        self.srt_path.pack(side="left", padx=8)
        ctk.CTkButton(row_s, text="Browse", width=80,
                      command=lambda: self._browse_file(self.srt_path, [("SRT","*.srt")])).pack(side="left")
        ctk.CTkButton(card2, text="💬 Burn Subtitles", height=36,
                      command=self._do_subtitles).pack(pady=8, anchor="w")

    # ════════════════════════════════════════════════════════
    #  TAB 4 — LOGO
    # ════════════════════════════════════════════════════════
    def _build_logo_tab(self, parent):
        self._section_title(parent, "🖼️ Add Logo / Watermark")
        card = self._card(parent, "Logo Settings")
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", pady=4)
        ctk.CTkLabel(row1, text="Logo Image:", width=110, anchor="w").pack(side="left")
        ctk.CTkEntry(row1, textvariable=self.logo_path,
                     placeholder_text="Path to PNG/JPG logo", width=280).pack(side="left", padx=8)
        ctk.CTkButton(row1, text="Browse", width=80,
                      command=lambda: self._browse_file(self.logo_path,
                                                         [("Images","*.png *.jpg *.jpeg")])).pack(side="left")
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", pady=4)
        ctk.CTkLabel(row2, text="Position:", width=110, anchor="w").pack(side="left")
        self.logo_pos = ctk.CTkComboBox(row2,
            values=["top-left","top-right","bottom-left","bottom-right","center"], width=140)
        self.logo_pos.set("bottom-left")
        self.logo_pos.pack(side="left", padx=8)
        ctk.CTkLabel(row2, text="Size (px):", anchor="w").pack(side="left", padx=(16,4))
        self.logo_size = ctk.CTkEntry(row2, placeholder_text="100", width=70)
        self.logo_size.pack(side="left")

        row3 = ctk.CTkFrame(card, fg_color="transparent")
        row3.pack(fill="x", pady=4)
        ctk.CTkLabel(row3, text="Opacity (0–1):", width=110, anchor="w").pack(side="left")
        self.logo_opacity = ctk.CTkSlider(row3, from_=0, to=1, number_of_steps=20, width=200)
        self.logo_opacity.set(0.8)
        self.logo_opacity.pack(side="left", padx=8)
        self.logo_opacity_label = ctk.CTkLabel(row3, text="0.80", width=40)
        self.logo_opacity_label.pack(side="left")
        self.logo_opacity.configure(command=lambda v: self.logo_opacity_label.configure(text=f"{v:.2f}"))
        ctk.CTkButton(card, text="🖼️ Apply Logo", height=36,
                      command=self._do_logo).pack(pady=8, anchor="w")

    # ════════════════════════════════════════════════════════
    #  TAB 5 — FILTERS
    # ════════════════════════════════════════════════════════
    def _build_filters_tab(self, parent):
        self._section_title(parent, "🎨 Filters & Visual Effects")
        card = self._card(parent, "Adjust Video")
        for label, attr, lo, hi, default in [
            ("Brightness", "filter_brightness", -1.0, 1.0, 0.0),
            ("Contrast",   "filter_contrast",    0.0, 3.0, 1.0),
            ("Saturation", "filter_saturation",  0.0, 3.0, 1.0),
            ("Gamma",      "filter_gamma",        0.1, 3.0, 1.0),
        ]:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=f"{label}:", width=110, anchor="w").pack(side="left")
            sl = ctk.CTkSlider(row, from_=lo, to=hi, number_of_steps=40, width=240)
            sl.set(default)
            sl.pack(side="left", padx=8)
            lbl = ctk.CTkLabel(row, text=f"{default:.2f}", width=50)
            lbl.pack(side="left")
            sl.configure(command=lambda v, l=lbl: l.configure(text=f"{v:.2f}"))
            setattr(self, attr, sl)
        ctk.CTkButton(card, text="🎨 Apply Adjustments", height=36,
                      fg_color=SUCCESS, hover_color="#196129",
                      command=self._do_color_adjust).pack(pady=8, anchor="w")

        card2 = self._card(parent, "Preset Effects")
        row_p = ctk.CTkFrame(card2, fg_color="transparent")
        row_p.pack(fill="x", pady=4)
        for lbl, cmd in [
            ("⬛ Grayscale",       self._do_grayscale),
            ("🎞️ Vignette",        self._do_vignette),
            ("🔄 Flip Horizontal", self._do_hflip),
            ("🔃 Flip Vertical",   self._do_vflip),
            ("🌫️ Blur",            self._do_blur),
        ]:
            ctk.CTkButton(row_p, text=lbl, width=130, height=34,
                          command=cmd).pack(side="left", padx=4, pady=4)

    # ════════════════════════════════════════════════════════
    #  TAB 6 — AUDIO
    # ════════════════════════════════════════════════════════
    def _build_audio_tab(self, parent):
        self._section_title(parent, "🔊 Audio Control")
        card = self._card(parent, "Volume & Mute")
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="Volume (0.0 – 3.0):", width=160, anchor="w").pack(side="left")
        self.audio_vol = ctk.CTkSlider(row, from_=0, to=3, number_of_steps=30, width=220)
        self.audio_vol.set(1.0)
        self.audio_vol.pack(side="left", padx=8)
        self.audio_vol_label = ctk.CTkLabel(row, text="1.00", width=50)
        self.audio_vol_label.pack(side="left")
        self.audio_vol.configure(command=lambda v: self.audio_vol_label.configure(text=f"{v:.2f}"))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", pady=6)
        ctk.CTkButton(btn_row, text="🔊 Set Volume", width=130, height=34,
                      command=self._do_volume).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="🔇 Mute Audio", width=130, height=34,
                      fg_color=WARNING, hover_color="#b17d0a",
                      command=self._do_mute).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="❌ Remove Audio", width=140, height=34,
                      fg_color=DANGER, hover_color="#b91c1c",
                      command=self._do_remove_audio).pack(side="left", padx=4)

        card2 = self._card(parent, "Extract / Replace Audio")
        ctk.CTkButton(card2, text="🎵 Extract Audio to MP3", height=34,
                      command=self._do_extract_audio).pack(side="left", padx=4, pady=8)
        row2 = ctk.CTkFrame(card2, fg_color="transparent")
        row2.pack(fill="x", pady=4)
        ctk.CTkLabel(row2, text="Replace with audio file:", width=180, anchor="w").pack(side="left")
        self.replace_audio_path = ctk.CTkEntry(row2, placeholder_text="Path to audio file", width=240)
        self.replace_audio_path.pack(side="left", padx=8)
        ctk.CTkButton(row2, text="Browse", width=80,
                      command=lambda: self._browse_file(self.replace_audio_path,
                                                         [("Audio","*.mp3 *.wav *.aac *.m4a")])).pack(side="left")
        ctk.CTkButton(card2, text="🔄 Replace Audio", height=34,
                      command=self._do_replace_audio).pack(pady=8, anchor="w")

        card3 = self._card(parent, "Speed Change")
        row3 = ctk.CTkFrame(card3, fg_color="transparent")
        row3.pack(fill="x", pady=4)
        ctk.CTkLabel(row3, text="Speed multiplier:", width=140, anchor="w").pack(side="left")
        self.speed_val = ctk.CTkComboBox(row3,
            values=["0.25","0.5","0.75","1.0","1.25","1.5","2.0","4.0"], width=120)
        self.speed_val.set("1.0")
        self.speed_val.pack(side="left", padx=8)
        ctk.CTkButton(card3, text="⚡ Change Speed", height=34,
                      command=self._do_speed).pack(pady=8, anchor="w")

    # ════════════════════════════════════════════════════════
    #  TAB 7 — CROP & RESIZE
    # ════════════════════════════════════════════════════════
    def _build_crop_tab(self, parent):
        self._section_title(parent, "📐 Crop & Resize")
        card = self._card(parent, "Resize to Preset or Custom")
        presets = ["1920x1080 (Full HD)","1280x720 (HD)","854x480 (SD)",
                   "1080x1920 (Reels/TikTok)","1080x1080 (Square)","Custom"]
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="Preset:", width=80, anchor="w").pack(side="left")
        self.resize_preset = ctk.CTkComboBox(row, values=presets, width=220,
                                              command=self._on_resize_preset)
        self.resize_preset.set(presets[0])
        self.resize_preset.pack(side="left", padx=8)
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", pady=4)
        ctk.CTkLabel(row2, text="Width:", width=60, anchor="w").pack(side="left")
        self.resize_w = ctk.CTkEntry(row2, placeholder_text="1920", width=90)
        self.resize_w.pack(side="left", padx=4)
        ctk.CTkLabel(row2, text="Height:", anchor="w").pack(side="left", padx=(12,4))
        self.resize_h = ctk.CTkEntry(row2, placeholder_text="1080", width=90)
        self.resize_h.pack(side="left", padx=4)
        ctk.CTkButton(card, text="📐 Resize Video", height=36,
                      command=self._do_resize).pack(pady=8, anchor="w")

        card2 = self._card(parent, "Crop (cut borders)")
        ctk.CTkLabel(card2, text="Pixels to remove from each side:",
                     font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack(anchor="w", pady=2)
        row3 = ctk.CTkFrame(card2, fg_color="transparent")
        row3.pack(fill="x", pady=4)
        for label, attr in [("Top","crop_top"),("Bottom","crop_bottom"),
                             ("Left","crop_left"),("Right","crop_right")]:
            ctk.CTkLabel(row3, text=f"{label}:", anchor="w").pack(side="left", padx=(8,2))
            e = ctk.CTkEntry(row3, placeholder_text="0", width=65)
            e.pack(side="left", padx=4)
            setattr(self, attr, e)
        
        # Output size options
        row4 = ctk.CTkFrame(card2, fg_color="transparent")
        row4.pack(fill="x", pady=4)
        ctk.CTkLabel(row4, text="Output Size:", width=80, anchor="w").pack(side="left")
        
        aspect_ratios = ["Original", "16:9 (YouTube)", "9:16 (Reels/TikTok)", "1:1 (Square)", 
                        "4:3 (Classic)", "21:9 (Cinema)", "Custom"]
        self.crop_aspect_ratio = ctk.CTkComboBox(row4, values=aspect_ratios, width=180,
                                                 command=self._on_crop_aspect_change)
        self.crop_aspect_ratio.set("Original")
        self.crop_aspect_ratio.pack(side="left", padx=8)
        
        # Custom size inputs (initially hidden)
        self.crop_size_frame = ctk.CTkFrame(card2, fg_color="transparent")
        ctk.CTkLabel(self.crop_size_frame, text="Width:", width=50, anchor="w").pack(side="left")
        self.crop_out_w = ctk.CTkEntry(self.crop_size_frame, placeholder_text="1920", width=80)
        self.crop_out_w.pack(side="left", padx=4)
        ctk.CTkLabel(self.crop_size_frame, text="Height:", anchor="w").pack(side="left", padx=(8,4))
        self.crop_out_h = ctk.CTkEntry(self.crop_size_frame, placeholder_text="1080", width=80)
        self.crop_out_h.pack(side="left", padx=4)
        
        ctk.CTkButton(card2, text="✂️ Crop Video", height=36,
                      command=self._do_crop).pack(pady=8, anchor="w")

        card3 = self._card(parent, "Add Padding / Black Bars")
        row4 = ctk.CTkFrame(card3, fg_color="transparent")
        row4.pack(fill="x", pady=4)
        ctk.CTkLabel(row4, text="Target:", width=60, anchor="w").pack(side="left")
        self.pad_w = ctk.CTkEntry(row4, placeholder_text="1920", width=90)
        self.pad_w.pack(side="left", padx=4)
        ctk.CTkLabel(row4, text="x", anchor="w").pack(side="left")
        self.pad_h = ctk.CTkEntry(row4, placeholder_text="1080", width=90)
        self.pad_h.pack(side="left", padx=4)
        ctk.CTkButton(card3, text="📦 Add Padding", height=36,
                      command=self._do_pad).pack(pady=8, anchor="w")

    # ════════════════════════════════════════════════════════
    #  TAB 8 — INTRO / OUTRO
    # ════════════════════════════════════════════════════════
    def _build_intro_outro_tab(self, parent):
        self._section_title(parent, "🎬 Add Intro & Outro Clips")
        for title, var_attr, label_text in [
            ("Intro (Starting Video)", "intro_path", "Intro Video File:"),
            ("Outro (Ending Video)",   "outro_path", "Outro Video File:"),
        ]:
            card = self._card(parent, title)
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=label_text, width=130, anchor="w").pack(side="left")
            var = getattr(self, var_attr)
            ctk.CTkEntry(row, textvariable=var,
                         placeholder_text=f"Path to {title.split()[0].lower()} video",
                         width=280).pack(side="left", padx=8)
            ctk.CTkButton(row, text="Browse", width=80,
                          command=lambda v=var: self._browse_file(
                              v, [("Video","*.mp4 *.mov *.avi *.mkv")])).pack(side="left")

        card3 = self._card(parent, "Apply Intro / Outro to Selected Video")
        ctk.CTkLabel(card3,
                     text="Concatenates: [Intro] + [Your Video] + [Outro]\nLeave blank to skip.",
                     font=ctk.CTkFont(size=11), text_color=TEXT_MUTED, justify="left").pack(anchor="w", pady=4)
        row3 = ctk.CTkFrame(card3, fg_color="transparent")
        row3.pack(fill="x", pady=4)
        ctk.CTkLabel(row3, text="Output filename:", width=130, anchor="w").pack(side="left")
        self.intro_outro_out = ctk.CTkEntry(row3, placeholder_text="final_with_intro_outro.mp4", width=260)
        self.intro_outro_out.pack(side="left", padx=8)
        ctk.CTkButton(card3, text="🎬 Attach Intro & Outro", height=40,
                      fg_color=SUCCESS, hover_color="#196129",
                      command=self._do_intro_outro).pack(pady=10, anchor="w")

    # ════════════════════════════════════════════════════════
    #  TAB 9 — EXPORT
    # ════════════════════════════════════════════════════════
    def _build_export_tab(self, parent):
        self._section_title(parent, "📤 Export / Convert Video")
        card = self._card(parent, "Export Settings")
        for label, attr, widget_cls, kwargs, default in [
            ("Output Format:",    "export_fmt",    ctk.CTkComboBox,
             {"values":["mp4","mkv","avi","mov","webm","gif"],"width":140}, "mp4"),
            ("Video Codec:",      "export_vcodec", ctk.CTkComboBox,
             {"values":["libx264","libx265","vp9","copy"],"width":140}, "libx264"),
            ("Audio Codec:",      "export_acodec", ctk.CTkComboBox,
             {"values":["aac","mp3","copy","none"],"width":140}, "aac"),
            ("Quality (CRF 0–51):","export_crf",  ctk.CTkEntry,
             {"placeholder_text":"23","width":80}, None),
            ("FPS:",              "export_fps",    ctk.CTkEntry,
             {"placeholder_text":"original","width":80}, None),
            ("Resolution:",       "export_res",    ctk.CTkComboBox,
             {"values":["original","1920x1080","1280x720","854x480"],"width":160}, "original"),
        ]:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=label, width=180, anchor="w").pack(side="left")
            w = widget_cls(row, **kwargs)
            if default and hasattr(w, "set"):
                w.set(default)
            w.pack(side="left", padx=8)
            setattr(self, attr, w)

        row_out = ctk.CTkFrame(card, fg_color="transparent")
        row_out.pack(fill="x", pady=4)
        ctk.CTkLabel(row_out, text="Output filename:", width=180, anchor="w").pack(side="left")
        self.export_out_name = ctk.CTkEntry(row_out, placeholder_text="exported_video", width=220)
        self.export_out_name.pack(side="left", padx=8)
        ctk.CTkButton(card, text="📤 Export Video", height=42,
                      fg_color=SUCCESS, hover_color="#196129",
                      font=ctk.CTkFont(size=14, weight="bold"),
                      command=self._do_export).pack(pady=12, anchor="w")

        card2 = self._card(parent, "Batch Convert All Loaded Files")
        ctk.CTkLabel(card2, text="Convert all sidebar files using the settings above.",
                     font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack(anchor="w", pady=2)
        ctk.CTkButton(card2, text="⚙️ Batch Convert All", height=36,
                      command=self._do_batch_export).pack(pady=8, anchor="w")

    # ════════════════════════════════════════════════════════
    #  UI HELPERS
    # ════════════════════════════════════════════════════════
    def _section_title(self, parent, title):
        ctk.CTkLabel(parent, text=title,
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(12,4))

    def _card(self, parent, title):
        frame = ctk.CTkFrame(parent, fg_color=BG_SIDEBAR, corner_radius=10)
        frame.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(frame, text=title,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_MUTED).pack(anchor="w", padx=14, pady=(10,4))
        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=(0,10))
        return inner

    def _browse_file(self, var, filetypes):
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            if isinstance(var, tk.StringVar):
                var.set(path)
            else:
                var.delete(0, "end")
                var.insert(0, path)

    def _browse_dir(self, var: tk.StringVar):
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    def _pick_output_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.output_dir.set(d)

    def _set_progress(self, pct, msg=""):
        self.progress_bar.set(pct / 100)
        self.progress_label.configure(text=f"{msg} {pct}%" if msg else f"{pct}%")
        self.update_idletasks()

    def _run_task(self, cmd: list, out_path: str, task_name: str):
        self._set_progress(0, task_name)
        self.cancel_event.clear()
        _CANCEL_EVENT.clear()
        self._log(f"[TASK] {task_name}")
        def worker():
            ok, err = run_ffmpeg(
                cmd,
                lambda p: self._set_progress(p, task_name),
                cancel_event=self.cancel_event,
                line_callback=self._log,
            )
            if ok:
                self._set_progress(100, "Done!")
                messagebox.showinfo("✅ Success", f"{task_name} complete!\n\nSaved to:\n{out_path}")
            else:
                self._set_progress(0, "Error")
                messagebox.showerror("❌ Error", f"{task_name} failed.\n{err}")
        threading.Thread(target=worker, daemon=True).start()

    def _require_file(self) -> bool:
        if not self.selected_file:
            messagebox.showwarning("No File", "Select a video file from the sidebar first.")
            return False
        return True

    def _out(self, suffix, ext="mp4") -> str:
        base = Path(self.selected_file["filename"]).stem
        return os.path.join(self.output_dir.get(), f"{base}_{suffix}.{ext}")

    # ── File Management ──────────────────────────────────────
    def _add_videos(self):
        if not FFMPEG_BIN:
            messagebox.showerror("FFmpeg Not Found",
                "FFmpeg is required.\nRun: pip install imageio-ffmpeg")
            return
        paths = filedialog.askopenfilenames(
            title="Select Video Files",
            filetypes=[
                ("All Video Files","*.mp4 *.MP4 *.mkv *.MKV *.avi *.AVI "
                                   "*.mov *.MOV *.webm *.flv *.wmv *.m4v *.3gp"),
                ("MP4","*.mp4 *.MP4"), ("MKV","*.mkv *.MKV"),
                ("AVI","*.avi *.AVI"), ("MOV","*.mov *.MOV"),
                ("All files","*.*"),
            ])
        if not paths:
            return
        failed = []
        for p in paths:
            if any(f["path"] == p for f in self.loaded_files):
                continue
            info = get_video_info(p)
            if info:
                self.loaded_files.append(info)
                dur  = format_duration(info["duration"])
                self.file_listbox.insert("end", f"  {info['filename']}  [{dur}]")
            else:
                failed.append(os.path.basename(p))
        if failed:
            messagebox.showwarning("Load Warning",
                "Could not read:\n" + "\n".join(failed))
        self._refresh_merge_list()

    def _remove_selected(self):
        sel = self.file_listbox.curselection()
        if sel:
            idx = sel[0]
            self.file_listbox.delete(idx)
            self.loaded_files.pop(idx)
            self.selected_file = None
            self._refresh_merge_list()

    def _on_file_select(self, event):
        sel = self.file_listbox.curselection()
        if sel:
            self.selected_file = self.loaded_files[sel[0]]
            i = self.selected_file
            self.info_text.configure(
                text=(f"📄 {i['filename']}\n"
                      f"⏱ {format_duration(i['duration'])}\n"
                      f"📺 {i['width']}×{i['height']}  {i['fps']}fps\n"
                      f"💾 {format_size(i['size'])}"))

    def _refresh_merge_list(self):
        self.merge_listbox.delete(0, "end")
        for f in self.loaded_files:
            self.merge_listbox.insert("end", f"  {f['filename']}")

    def _move_merge_item(self, direction):
        sel = self.merge_listbox.curselection()
        if not sel:
            return
        idx, new_idx = sel[0], sel[0] + direction
        if new_idx < 0 or new_idx >= len(self.loaded_files):
            return
        self.loaded_files[idx], self.loaded_files[new_idx] = \
            self.loaded_files[new_idx], self.loaded_files[idx]
        self._refresh_merge_list()
        self.merge_listbox.selection_set(new_idx)

    def _on_resize_preset(self, choice):
        if "Custom" in choice:
            return
        # Extract dimensions from preset string
        import re
        m = re.search(r'(\d+)x(\d+)', choice)
        if m:
            self.resize_w.delete(0, "end")
            self.resize_w.insert(0, m.group(1))
            self.resize_h.delete(0, "end")
            self.resize_h.insert(0, m.group(2))

    def _on_crop_aspect_change(self, choice):
        """Handle aspect ratio selection change."""
        if choice == "Custom":
            self.crop_size_frame.pack(fill="x", pady=4)
        else:
            self.crop_size_frame.pack_forget()

    # ════════════════════════════════════════════════════════
    #  AUTO BATCH OPERATIONS  (Script 1 engine)
    # ════════════════════════════════════════════════════════
    def _batch_scan(self):
        pending = Path(self.batch_pending_var.get())
        if not pending.exists():
            pending.mkdir(parents=True, exist_ok=True)
        files = [p for p in sorted(pending.iterdir())
                 if p.is_file() and p.suffix.lower() in VIDEO_EXTS]

        infos = []
        for p in files:
            info = get_video_info(str(p)) or {"path": str(p), "filename": p.name, "duration": 0.0, "width": 0, "height": 0, "fps": 0.0, "size": 0}
            infos.append(info)

        self.batch_files_infos = infos
        if hasattr(self, "batch_listbox"):
            self.batch_listbox.delete(0, "end")
            for i in infos:
                dur = format_duration(i.get("duration", 0.0) or 0.0)
                w = i.get("width", 0) or 0
                h = i.get("height", 0) or 0
                sz = format_size(i.get("size", 0) or 0)
                self.batch_listbox.insert("end", f"{i.get('filename','')}   [{dur}]   {w}x{h}   {sz}")

        self.batch_status.configure(
            text=f"📂 Found {len(files)} video(s) in: {pending.resolve()}")

        if files:
            self.batch_run_btn.configure(state="normal")
        else:
            self.batch_run_btn.configure(state="disabled")
        # CTkTextbox doesn't support .configure(text=) — use delete/insert
        if hasattr(self, "batch_details"):
            self.batch_details.configure(state="normal")
            self.batch_details.delete("1.0", "end")
            self.batch_details.insert("end", f"📂 Found {len(files)} file(s)\nClick a file to see details.")
            self.batch_details.configure(state="disabled")

    def _batch_select_all(self):
        if hasattr(self, "batch_listbox"):
            self.batch_listbox.selection_set(0, "end")
            self._update_batch_details()

    def _batch_select_none(self):
        if hasattr(self, "batch_listbox"):
            self.batch_listbox.selection_clear(0, "end")
            self._update_batch_details()

    def _on_batch_select(self, _event=None):
        self._update_batch_details()

    def _update_batch_details(self):
        if not hasattr(self, "batch_listbox"):
            return
        sel = list(self.batch_listbox.curselection())

        def _set_details(text):
            if hasattr(self, "batch_details"):
                self.batch_details.configure(state="normal")
                self.batch_details.delete("1.0", "end")
                self.batch_details.insert("end", text)
                self.batch_details.configure(state="disabled")

        if not sel:
            if self.batch_files_infos:
                _set_details("Selected: 0\n(will process ALL scanned videos)")
                self.batch_run_btn.configure(state="normal")
            else:
                _set_details("Selected: 0\nScan folder first.")
                self.batch_run_btn.configure(state="disabled")
            return

        lines = [f"Selected: {len(sel)} file(s)\n"]
        total_dur = 0.0
        total_size = 0
        for idx in sel:
            try:
                i = self.batch_files_infos[idx]
                dur  = float(i.get("duration", 0.0) or 0.0)
                sz   = int(i.get("size", 0) or 0)
                w    = i.get("width", 0) or 0
                h    = i.get("height", 0) or 0
                fps  = i.get("fps", 0) or 0
                total_dur  += dur
                total_size += sz
                lines.append(
                    f"{'─'*30}\n"
                    f"📄 {i.get('filename','?')}\n"
                    f"⏱ Duration : {format_duration(dur)}\n"
                    f"📺 Size     : {w}×{h}  {fps}fps\n"
                    f"💾 File size: {format_size(sz)}\n"
                )
            except Exception:
                pass
        lines.append(f"{'─'*30}\n")
        lines.append(f"⏱ Total dur : {format_duration(total_dur)}\n")
        lines.append(f"💾 Total size: {format_size(total_size)}\n")
        _set_details("".join(lines))
        self.batch_run_btn.configure(state="normal")

    def _batch_run(self):
        if not FFMPEG_BIN:
            messagebox.showerror("FFmpeg Not Found", "FFmpeg is required for batch processing.")
            return

        self.cancel_event.clear()
        _CANCEL_EVENT.clear()
        self._log("[BATCH] Starting batch", "info")

        # ── Update SETTINGS from UI fields ──────────────────────
        SETTINGS["pending_dir"] = self.batch_pending_var.get()
        SETTINGS["done_dir"]    = self.batch_done_var.get()
        SETTINGS["ending"]["enabled"] = self.batch_ending_var.get()
        SETTINGS["logo"]["enabled"]   = self.batch_logo_var.get()
        # Crop values
        try: SETTINGS["crop_left"]   = int(self.crop_left_var.get()   or 0)
        except: pass
        try: SETTINGS["crop_top"]    = int(self.crop_top_var.get()    or 0)
        except: pass
        try: SETTINGS["crop_right"]  = int(self.crop_right_var.get()  or 0)
        except: pass
        try: SETTINGS["crop_bottom"] = int(self.crop_bottom_var.get() or 0)
        except: pass
        # Transitions
        SETTINGS["random_transitions"] = self.trans_random_var.get()
        SETTINGS["transitions"] = [t for t, v in self._trans_vars.items() if v.get()]
        SETTINGS["upload_to_drive"] = self.batch_upload_drive_var.get()
        save_settings()

        pending = Path(SETTINGS["pending_dir"])
        done    = Path(SETTINGS["done_dir"])
        done.mkdir(parents=True, exist_ok=True)

        # Determine files to process
        files: List[Path] = []
        if hasattr(self, "batch_listbox") and self.batch_files_infos:
            sel = list(self.batch_listbox.curselection())
            for idx in sel:
                try:
                    files.append(Path(self.batch_files_infos[idx]["path"]))
                except Exception:
                    pass
        if not files:
            files = [p for p in sorted(pending.iterdir())
                     if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
        if not files:
            messagebox.showwarning("No Files",
                f"No video files found in:\n{pending.resolve()}")
            return

        key     = self.batch_profile_var.get().split(":")[0].strip()
        profile = YOUTUBE_PROFILES.get(key, YOUTUBE_PROFILES["3"])

        self.batch_run_btn.configure(state="disabled", text="⏳ Processing...")
        self.batch_status.configure(text=f"Starting — {len(files)} file(s)...")
        if hasattr(self, "batch_progress_bar"):
            self.batch_progress_bar.set(0)

        do_drive  = SETTINGS.get("upload_to_drive", False)
        folder_id = SETTINGS.get("drive_folder_id", "")
        script_url= SETTINGS.get("apps_script_url", "")

        def worker():
            ok_count = fail_count = 0
            t0 = time.time()
            for i, src in enumerate(files):
                self.after(0, self.batch_status.configure,
                           {"text": f"[{i+1}/{len(files)}] {src.name}"})
                self._set_progress(0, f"Batch {i+1}/{len(files)}")
                if hasattr(self, "batch_progress_bar"):
                    self.after(0, lambda v=i/len(files): self.batch_progress_bar.set(v))

                try:
                    duration, has_audio = probe_duration_and_audio(src)
                    self._log(f"📄 File   : {src.name}", "info")
                    self._log(f"⏱ Duration: {format_duration(duration)}  |  Audio: {has_audio}", "info")
                    trim_end = SETTINGS["trim_end_seconds"] if self.batch_trim_var.get() else 0.0
                    end_time = max(0.0, duration - trim_end) if duration > 0 else duration

                    if self.batch_scene_var.get() and end_time > 0:
                        self._log("🔍 Detecting scene changes...", "info")
                        scenes   = detect_scene_changes(src, SETTINGS["scene_threshold"])
                        segments = build_segments(scenes, end_time, SETTINGS["min_scene_seconds"])
                        self._log(f"🎬 Scenes found: {len(segments)}", "info")
                    else:
                        segments = [(0.0, end_time or duration)]
                        self._log("🎬 No scene detection — single segment", "info")

                    kept_segments = segments
                    if len(segments) > 1:
                        result_holder = [None]
                        done_event    = threading.Event()
                        def show_dialog():
                            dlg = SceneSelectDialog(self, segments)
                            result_holder[0] = dlg.result
                            done_event.set()
                        self.after(0, show_dialog)
                        done_event.wait(timeout=300)
                        if result_holder[0]:
                            kept_segments = result_holder[0]
                            self._log(f"✅ Keeping {len(kept_segments)} segment(s)", "success")

                    out_name = f"{src.stem}_{profile.height}p.mp4"
                    out_dir  = done / src.stem
                    out_dir.mkdir(parents=True, exist_ok=True)
                    main_out = out_dir / out_name
                    self._log(f"📤 Output : {main_out}", "info")

                    ending   = Path(SETTINGS["ending"]["path"]) \
                                if SETTINGS["ending"]["enabled"] else None
                    use_ending = (ending and ending.exists() and self.batch_ending_var.get())
                    proc_out   = out_dir / f"{src.stem}_{profile.height}p__main.mp4" \
                                 if use_ending else main_out

                    # ── Live FFmpeg line callback → log panel ────
                    def ffmpeg_line(line: str):
                        line = line.strip()
                        if not line:
                            return
                        # Show frame/fps/size lines as progress info
                        if line.startswith("frame=") or "time=" in line:
                            self._log(f"  ▸ {line}", "info")
                        elif "error" in line.lower() or "invalid" in line.lower():
                            self._log(f"  ⚠ {line}", "error")
                        elif line.startswith("[") or "warning" in line.lower():
                            self._log(f"  ⚠ {line}", "warning")

                    self._log(f"⚙ Rendering with profile: {profile.label}  |  Transition: {SETTINGS.get('transitions') or ['fade']}", "info")
                    ok, err = render_with_transitions(
                        src, proc_out, profile, kept_segments, has_audio,
                        progress_cb=lambda p: self._set_progress(p, f"Rendering {src.name[:20]}"))

                    if self.cancel_event.is_set() or _CANCEL_EVENT.is_set():
                        raise RuntimeError("Cancelled")

                    if ok and use_ending:
                        ok2, err2 = concat_ending(proc_out, ending, main_out, profile)
                        try: proc_out.unlink()
                        except Exception: pass
                        if not ok2:
                            ok, err = False, err2

                    if ok:
                        if self.batch_delete_var.get():
                            try: src.unlink()
                            except Exception: pass
                        ok_count += 1
                        self._set_progress(100, f"✅ {src.name[:20]}")
                        self._log(f"✅ Done: {src.name} → {main_out}", "success")
                        sz = main_out.stat().st_size if main_out.exists() else 0
                        self._log(f"   Output size: {format_size(sz)}", "success")

                        # ── Upload to Drive if enabled ───────────
                        if do_drive and folder_id:
                            try:
                                self._log(f"☁ Uploading to Drive: {main_out.name}", "info")
                                self.after(0, self.batch_status.configure,
                                           {"text": f"Uploading to Drive: {main_out.name}"})

                                drive_url = drive_upload_file(
                                    main_out, folder_id,
                                    on_progress=lambda p: self._set_progress(
                                        p, f"Drive upload {p}%"))

                                self._log(f"✅ Drive URL: {drive_url}", "success")

                                # Update sheet — derive story title from filename
                                story_title = src.stem.replace("_", " ").replace("-", " ")
                                if script_url:
                                    sheet_save_video_url(story_title, drive_url, script_url)
                                    self._log(f"✅ Sheet updated → Ready: {story_title}", "success")

                            except Exception as ue:
                                self._log(f"⚠ Drive upload failed: {ue}", "warning")
                    else:
                        fail_count += 1
                        self._set_progress(0, f"❌ Failed: {src.name[:20]}")
                        self._log(f"❌ FAILED: {src.name}", "error")
                        self._log(f"   Error: {err[:300]}", "error")
                        self.after(0, lambda e=err, n=src.name: messagebox.showerror(
                            "Batch Error", f"Failed: {n}\n\n{e}"))

                except Exception as exc:
                    fail_count += 1
                    self._log(f"❌ EXCEPTION: {src.name} → {exc}", "error")
                    self.after(0, lambda e=str(exc), n=src.name: messagebox.showerror(
                        "Batch Error", f"Error: {n}\n\n{e}"))

            elapsed = int(time.time() - t0)
            final_msg = (f"✅ Batch complete!\n\n"
                         f"Processed: {ok_count}  |  Failed: {fail_count}\n"
                         f"Time: {elapsed}s\n"
                         f"Output: {done.resolve()}")
            self.after(0, lambda: messagebox.showinfo("✅ Batch Done", final_msg))
            self.after(0, lambda: self.batch_status.configure(
                text=f"Done! ✅ {ok_count} OK  ❌ {fail_count} failed  ⏱ {elapsed}s"))
            self.after(0, lambda: self.batch_run_btn.configure(
                state="normal", text="▶ PROCESS"))
            if hasattr(self, "batch_progress_bar"):
                self.after(0, lambda: self.batch_progress_bar.set(1.0))
            self._set_progress(100, "Batch complete!")

        threading.Thread(target=worker, daemon=True).start()

    # ════════════════════════════════════════════════════════
    #  MANUAL EDITING OPERATIONS
    # ════════════════════════════════════════════════════════
    def _do_trim(self):
        if not self._require_file(): return
        src   = self.selected_file["path"]
        start = self.trim_start.get().strip() or "0"
        end   = self.trim_end.get().strip()
        if not end:
            messagebox.showwarning("Missing", "Enter an end time.")
            return
        out = self._out("trimmed")
        self._run_task([FFMPEG_BIN,"-y","-i",src,"-ss",start,"-to",end,"-c","copy",out],
                       out, "Trimming")

    def _do_split(self):
        if not self._require_file(): return
        mins = self.split_mins.get().strip()
        if not mins:
            messagebox.showwarning("Missing", "Enter split interval in minutes.")
            return
        try:
            sec = int(float(mins) * 60)
        except Exception:
            messagebox.showerror("Error", "Invalid minutes value.")
            return
        src         = self.selected_file["path"]
        base        = Path(self.selected_file["filename"]).stem
        out_pattern = os.path.join(self.output_dir.get(), f"{base}_part%03d.mp4")
        self._run_task(
            [FFMPEG_BIN,"-y","-i",src,"-c","copy","-map","0",
             "-segment_time",str(sec),"-f","segment",
             "-reset_timestamps","1", out_pattern],
            out_pattern, "Splitting")

    def _do_cut_section(self):
        if not self._require_file(): return
        src      = self.selected_file["path"]
        cut_from = self.cut_from.get().strip()
        cut_to_t = self.cut_to.get().strip()
        if not cut_from or not cut_to_t:
            messagebox.showwarning("Missing", "Fill in both From and To times.")
            return
        out       = self._out("cut")
        part1     = os.path.join(self.output_dir.get(), "_tmp_part1.mp4")
        part2     = os.path.join(self.output_dir.get(), "_tmp_part2.mp4")
        list_file = os.path.join(self.output_dir.get(), "_concat.txt")

        def worker():
            subprocess.run([FFMPEG_BIN,"-y","-i",src,"-to",cut_from,"-c","copy",part1],
                           capture_output=True)
            subprocess.run([FFMPEG_BIN,"-y","-i",src,"-ss",cut_to_t,"-c","copy",part2],
                           capture_output=True)
            with open(list_file,"w") as f:
                f.write(f"file '{part1}'\nfile '{part2}'\n")
            ok, _ = run_ffmpeg([FFMPEG_BIN,"-y","-f","concat","-safe","0",
                                 "-i",list_file,"-c","copy",out])
            for p in [part1, part2, list_file]:
                try: os.remove(p)
                except Exception: pass
            if ok:
                self._set_progress(100, "Done!")
                messagebox.showinfo("✅ Success", f"Section removed!\nSaved to:\n{out}")
            else:
                messagebox.showerror("❌ Error", "Cut section failed.")
        self._set_progress(0, "Cutting section")
        threading.Thread(target=worker, daemon=True).start()

    def _do_merge(self):
        if len(self.loaded_files) < 2:
            messagebox.showwarning("Not enough files", "Add at least 2 videos.")
            return
        list_file = os.path.join(self.output_dir.get(), "_merge_list.txt")
        out_name  = self.merge_out_name.get().strip() or "merged_output.mp4"
        out       = os.path.join(self.output_dir.get(), out_name)
        with open(list_file, "w") as f:
            for fi in self.loaded_files:
                f.write(f"file '{fi['path']}'\n")
        def worker():
            ok, err = run_ffmpeg([FFMPEG_BIN,"-y","-f","concat","-safe","0",
                                   "-i",list_file,"-c","copy",out])
            try: os.remove(list_file)
            except Exception: pass
            if ok:
                self._set_progress(100, "Done!")
                messagebox.showinfo("✅ Merged", f"Saved to:\n{out}")
            else:
                messagebox.showerror("❌ Error", f"Merge failed.\n{err}")
        self._set_progress(0, "Merging")
        threading.Thread(target=worker, daemon=True).start()

    def _do_add_text(self):
        if not self._require_file(): return
        src   = self.selected_file["path"]
        text  = self.text_content.get().strip()
        if not text:
            messagebox.showwarning("Missing", "Enter text content.")
            return
        pos   = self.text_pos.get()
        size  = self.text_size.get().strip() or "36"
        color = self.text_color_var.get().strip() or "white"
        start = self.text_start.get().strip() or "0"
        dur   = self.text_dur.get().strip() or "5"
        end_t = float(start) + float(dur)
        pos_map = {
            "bottom-center": "(w-text_w)/2:h-th-30",
            "top-center":    "(w-text_w)/2:30",
            "center":        "(w-text_w)/2:(h-text_h)/2",
            "bottom-left":   "20:h-th-30",
            "bottom-right":  "w-tw-20:h-th-30",
            "top-left":      "20:30",
            "top-right":     "w-tw-20:30",
        }
        xy  = pos_map.get(pos, "(w-text_w)/2:h-th-30")
        out = self._out("text")
        vf  = (f"drawtext=text='{text}':fontcolor={color}:fontsize={size}:"
               f"x={xy}:enable='between(t,{start},{end_t})'")
        self._run_task([FFMPEG_BIN,"-y","-i",src,"-vf",vf,"-c:a","copy",out],
                       out, "Adding text")

    def _do_subtitles(self):
        if not self._require_file(): return
        src = self.selected_file["path"]
        srt = self.srt_path.get().strip()
        if not srt or not os.path.exists(srt):
            messagebox.showwarning("Missing", "Select a valid .srt file.")
            return
        out = self._out("subtitled")
        self._run_task([FFMPEG_BIN,"-y","-i",src,"-vf",f"subtitles='{srt}'","-c:a","copy",out],
                       out, "Burning subtitles")

    def _do_logo(self):
        if not self._require_file(): return
        src  = self.selected_file["path"]
        logo = self.logo_path.get().strip()
        if not logo or not os.path.exists(logo):
            messagebox.showwarning("Missing", "Select a valid logo image.")
            return
        pos     = self.logo_pos.get()
        size    = self.logo_size.get().strip() or "100"
        opacity = self.logo_opacity.get()
        pos_map = {
            "top-left":     "10:10",
            "top-right":    "main_w-overlay_w-10:10",
            "bottom-left":  "10:main_h-overlay_h-10",
            "bottom-right": "main_w-overlay_w-10:main_h-overlay_h-10",
            "center":       "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
        }
        xy  = pos_map.get(pos, "main_w-overlay_w-10:main_h-overlay_h-10")
        out = self._out("logo")
        vf  = (f"[1:v]scale={size}:-1,format=rgba,colorchannelmixer=aa={opacity:.2f}[logo];"
               f"[0:v][logo]overlay={xy}")
        self._run_task([FFMPEG_BIN,"-y","-i",src,"-i",logo,
                        "-filter_complex",vf,"-c:a","copy",out],
                       out, "Adding logo")

    def _do_color_adjust(self):
        if not self._require_file(): return
        src = self.selected_file["path"]
        b, c, s, g = (self.filter_brightness.get(), self.filter_contrast.get(),
                      self.filter_saturation.get(), self.filter_gamma.get())
        vf  = f"eq=brightness={b:.2f}:contrast={c:.2f}:saturation={s:.2f}:gamma={g:.2f}"
        out = self._out("adjusted")
        self._run_task([FFMPEG_BIN,"-y","-i",src,"-vf",vf,"-c:a","copy",out],
                       out, "Color adjust")

    def _do_grayscale(self):
        if not self._require_file(): return
        out = self._out("grayscale")
        self._run_task([FFMPEG_BIN,"-y","-i",self.selected_file["path"],
                        "-vf","hue=s=0","-c:a","copy",out], out, "Grayscale")

    def _do_vignette(self):
        if not self._require_file(): return
        out = self._out("vignette")
        self._run_task([FFMPEG_BIN,"-y","-i",self.selected_file["path"],
                        "-vf","vignette","-c:a","copy",out], out, "Vignette")

    def _do_hflip(self):
        if not self._require_file(): return
        out = self._out("hflip")
        self._run_task([FFMPEG_BIN,"-y","-i",self.selected_file["path"],
                        "-vf","hflip","-c:a","copy",out], out, "Flip H")

    def _do_vflip(self):
        if not self._require_file(): return
        out = self._out("vflip")
        self._run_task([FFMPEG_BIN,"-y","-i",self.selected_file["path"],
                        "-vf","vflip","-c:a","copy",out], out, "Flip V")

    def _do_blur(self):
        if not self._require_file(): return
        out = self._out("blur")
        self._run_task([FFMPEG_BIN,"-y","-i",self.selected_file["path"],
                        "-vf","boxblur=5:1","-c:a","copy",out], out, "Blur")

    def _do_volume(self):
        if not self._require_file(): return
        vol = self.audio_vol.get()
        out = self._out("volume")
        self._run_task([FFMPEG_BIN,"-y","-i",self.selected_file["path"],
                        "-filter:a",f"volume={vol:.2f}","-c:v","copy",out],
                       out, "Volume")

    def _do_mute(self):
        if not self._require_file(): return
        out = self._out("muted")
        self._run_task([FFMPEG_BIN,"-y","-i",self.selected_file["path"],
                        "-filter:a","volume=0","-c:v","copy",out], out, "Muting")

    def _do_remove_audio(self):
        if not self._require_file(): return
        out = self._out("no_audio")
        self._run_task([FFMPEG_BIN,"-y","-i",self.selected_file["path"],
                        "-c:v","copy","-an",out], out, "Remove audio")

    def _do_extract_audio(self):
        if not self._require_file(): return
        out = self._out("audio", ext="mp3")
        self._run_task([FFMPEG_BIN,"-y","-i",self.selected_file["path"],
                        "-vn","-acodec","libmp3lame","-q:a","2",out],
                       out, "Extract audio")

    def _do_replace_audio(self):
        if not self._require_file(): return
        src   = self.selected_file["path"]
        audio = self.replace_audio_path.get().strip()
        if not audio or not os.path.exists(audio):
            messagebox.showwarning("Missing", "Select a valid audio file.")
            return
        out = self._out("replaced_audio")
        self._run_task([FFMPEG_BIN,"-y","-i",src,"-i",audio,
                        "-c:v","copy","-c:a","aac","-map","0:v:0","-map","1:a:0",
                        "-shortest",out], out, "Replace audio")

    def _do_speed(self):
        if not self._require_file(): return
        src   = self.selected_file["path"]
        speed = float(self.speed_val.get())
        inv   = 1.0 / speed
        out   = self._out(f"speed{speed}x")
        vf    = f"setpts={inv:.4f}*PTS"
        if speed > 2.0:
            af = "atempo=2.0,atempo=2.0" if speed <= 4 else "atempo=2.0,atempo=2.0,atempo=2.0"
        elif speed < 0.5:
            af = "atempo=0.5,atempo=0.5" if speed >= 0.25 else "atempo=0.5"
        else:
            af = f"atempo={min(2.0, max(0.5, speed)):.2f}"
        self._run_task([FFMPEG_BIN,"-y","-i",src,"-vf",vf,"-filter:a",af,out],
                       out, f"Speed {speed}x")

    def _do_resize(self):
        if not self._require_file(): return
        src = self.selected_file["path"]
        w   = self.resize_w.get().strip() or "1920"
        h   = self.resize_h.get().strip() or "1080"
        out = self._out(f"resize_{w}x{h}")
        self._run_task([FFMPEG_BIN,"-y","-i",src,
                        "-vf",f"scale={w}:{h}:flags=bilinear","-c:a","copy",out],
                       out, f"Resize {w}×{h}")

    def _do_crop(self):
        if not self._require_file(): return
        src = self.selected_file["path"]
        t   = self.crop_top.get().strip()    or "0"
        b   = self.crop_bottom.get().strip() or "0"
        l   = self.crop_left.get().strip()   or "0"
        r   = self.crop_right.get().strip()  or "0"
        
        info = self.selected_file
        cw  = info["width"]  - int(l) - int(r)
        ch  = info["height"] - int(t) - int(b)
        
        # Handle aspect ratio and output sizing
        aspect_choice = self.crop_aspect_ratio.get()
        vf_filters = []
        
        if aspect_choice != "Original":
            if aspect_choice == "Custom":
                # Use custom dimensions
                try:
                    target_w = int(self.crop_out_w.get().strip() or cw)
                    target_h = int(self.crop_out_h.get().strip() or ch)
                    vf_filters.append(f"scale={target_w}:{target_h}")
                except ValueError:
                    pass  # Fall back to original size if invalid input
            else:
                # Predefined aspect ratios
                aspect_map = {
                    "16:9 (YouTube)": (16, 9),
                    "9:16 (Reels/TikTok)": (9, 16),
                    "1:1 (Square)": (1, 1),
                    "4:3 (Classic)": (4, 3),
                    "21:9 (Cinema)": (21, 9)
                }
                
                if aspect_choice in aspect_map:
                    ar_w, ar_h = aspect_map[aspect_choice]
                    # Calculate target dimensions maintaining aspect ratio
                    current_ratio = cw / ch
                    target_ratio = ar_w / ar_h
                    
                    if current_ratio > target_ratio:
                        # Width is too wide, scale based on height
                        target_h = ch
                        target_w = int(ch * target_ratio)
                    else:
                        # Height is too tall, scale based on width
                        target_w = cw
                        target_h = int(cw / target_ratio)
                    
                    vf_filters.append(f"scale={target_w}:{target_h}")
        
        # Add crop filter
        crop_filter = f"crop={cw}:{ch}:{l}:{t}"
        if vf_filters:
            vf = ",".join([crop_filter] + vf_filters)
        else:
            vf = crop_filter
        
        out = self._out("cropped")
        self._run_task([FFMPEG_BIN,"-y","-i",src,"-vf",vf,"-c:a","copy",out],
                       out, "Cropping")

    def _do_pad(self):
        if not self._require_file(): return
        src = self.selected_file["path"]
        pw  = self.pad_w.get().strip() or "1920"
        ph  = self.pad_h.get().strip() or "1080"
        out = self._out(f"padded_{pw}x{ph}")
        vf  = (f"scale={pw}:{ph}:force_original_aspect_ratio=decrease,"
               f"pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2:black")
        self._run_task([FFMPEG_BIN,"-y","-i",src,"-vf",vf,"-c:a","copy",out],
                       out, "Padding")

    def _do_intro_outro(self):
        if not self._require_file(): return
        src   = self.selected_file["path"]
        intro = self.intro_path.get().strip()
        outro = self.outro_path.get().strip()
        out_name = self.intro_outro_out.get().strip() or "final_with_intro_outro.mp4"
        out   = os.path.join(self.output_dir.get(), out_name)
        if not intro and not outro:
            messagebox.showwarning("Missing", "Add at least an intro or outro file.")
            return
        parts = []
        if intro and os.path.exists(intro): parts.append(intro)
        parts.append(src)
        if outro and os.path.exists(outro): parts.append(outro)
        list_file = os.path.join(self.output_dir.get(), "_intro_outro_list.txt")
        with open(list_file, "w") as f:
            for p in parts:
                f.write(f"file '{p}'\n")
        def worker():
            ok, err = run_ffmpeg([FFMPEG_BIN,"-y","-f","concat","-safe","0",
                                   "-i",list_file,"-c","copy",out])
            try: os.remove(list_file)
            except Exception: pass
            if ok:
                self._set_progress(100, "Done!")
                messagebox.showinfo("✅ Success", f"Saved to:\n{out}")
            else:
                messagebox.showerror("❌ Error", f"Failed.\n{err}")
        self._set_progress(0, "Attaching intro/outro")
        threading.Thread(target=worker, daemon=True).start()

    def _do_export(self):
        if not self._require_file(): return
        src      = self.selected_file["path"]
        fmt      = self.export_fmt.get()
        vc       = self.export_vcodec.get()
        ac       = self.export_acodec.get()
        crf      = self.export_crf.get().strip() or "23"
        fps      = self.export_fps.get().strip()
        res      = self.export_res.get()
        out_name = self.export_out_name.get().strip() or "exported"
        out      = os.path.join(self.output_dir.get(), f"{out_name}.{fmt}")
        cmd      = [FFMPEG_BIN, "-y", "-i", src]
        vf_parts = []
        if res != "original" and "x" in res:
            w, h = res.split("x")
            vf_parts.append(f"scale={w}:{h}")
        if fps:
            vf_parts.append(f"fps={fps}")
        if vf_parts:
            cmd += ["-vf", ",".join(vf_parts)]
        cmd += (["-c:v", vc, "-crf", crf] if vc != "copy" else ["-c:v", "copy"])
        cmd += (["-c:a", ac] if ac != "none" else ["-an"])
        cmd.append(out)
        self._run_task(cmd, out, "Exporting")

    def _do_batch_export(self):
        if not self.loaded_files:
            messagebox.showwarning("No Files", "Load video files first.")
            return
        fmt = self.export_fmt.get()
        vc  = self.export_vcodec.get()
        ac  = self.export_acodec.get()
        crf = self.export_crf.get().strip() or "23"
        def worker():
            for i, fi in enumerate(self.loaded_files):
                self._set_progress(int(i / len(self.loaded_files) * 100),
                                    f"Batch {i+1}/{len(self.loaded_files)}")
                base = Path(fi["filename"]).stem
                out  = os.path.join(self.output_dir.get(), f"{base}_converted.{fmt}")
                run_ffmpeg([FFMPEG_BIN,"-y","-i",fi["path"],
                            "-c:v",vc,"-crf",crf,"-c:a",ac,out])
            self._set_progress(100, "Batch done!")
            messagebox.showinfo("✅ Batch Done",
                                f"All {len(self.loaded_files)} files converted!")
        self._set_progress(0, "Batch starting")
        threading.Thread(target=worker, daemon=True).start()

    def _build_log_panel(self):
        """Build the modern log panel at the bottom of the UI."""
        # Main log container with modern styling
        log_container = ctk.CTkFrame(self, fg_color=BG_DARK, height=160, corner_radius=8)
        log_container.pack(fill="x", padx=12, pady=(0, 12))
        log_container.pack_propagate(False)
        
        # Header with title and controls
        header_frame = ctk.CTkFrame(log_container, fg_color="transparent", height=35)
        header_frame.pack(fill="x", padx=8, pady=(8, 4))
        header_frame.pack_propagate(False)
        
        # Left side - Title with icon
        title_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_frame.pack(side="left", fill="x", expand=True)
        
        # Animated status indicator
        self.log_status_label = ctk.CTkLabel(title_frame, text="●", 
                                           font=ctk.CTkFont(size=14), text_color="#4ade80")
        self.log_status_label.pack(side="left", padx=(0, 4))
        
        ctk.CTkLabel(title_frame, text="📋 Console Output", 
                    font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        
        # Log counter
        self.log_counter = ctk.CTkLabel(title_frame, text="(0)", 
                                       font=ctk.CTkFont(size=11), text_color=TEXT_MUTED)
        self.log_counter.pack(side="left", padx=(8, 0))
        
        # Right side - Control buttons
        controls_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        controls_frame.pack(side="right")
        
        # Modern buttons with hover effects
        self.clear_log_btn = ctk.CTkButton(controls_frame, text="🗑️ Clear", 
                                          width=70, height=28, font=ctk.CTkFont(size=11),
                                          fg_color="#374151", hover_color="#4b5563",
                                          command=self._clear_log)
        self.clear_log_btn.pack(side="left", padx=2)
        
        self.save_log_btn = ctk.CTkButton(controls_frame, text="💾 Save", 
                                         width=70, height=28, font=ctk.CTkFont(size=11),
                                         fg_color="#059669", hover_color="#047857",
                                         command=self._save_log)
        self.save_log_btn.pack(side="left", padx=2)
        
        self.toggle_log_btn = ctk.CTkButton(controls_frame, text="👁️ Show", 
                                           width=70, height=28, font=ctk.CTkFont(size=11),
                                           fg_color="#7c3aed", hover_color="#6d28d9",
                                           command=self._toggle_log_panel)
        self.toggle_log_btn.pack(side="left", padx=2)
        
        # Log text area with modern styling
        self.log_frame = ctk.CTkFrame(log_container, fg_color="#0d1117", corner_radius=6)
        self.log_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        
        self.log_text = ctk.CTkTextbox(self.log_frame, height=100, 
                                      font=ctk.CTkFont(size=10, family="Consolas"),
                                      fg_color="#0d1117", text_color="#c9d1d9",
                                      border_width=1, border_color="#30363d",
                                      corner_radius=4)
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)
        
        # Configure text tags for different log types
        self.log_text.tag_config("info", foreground="#58a6ff")
        self.log_text.tag_config("success", foreground="#3fb950")
        self.log_text.tag_config("warning", foreground="#d29922")
        self.log_text.tag_config("error", foreground="#f85149")
        self.log_text.tag_config("timestamp", foreground="#8b949e")
        
        # Initialize log counter
        self.log_count = 0
        self.log_panel_visible = True
        
    def _log(self, message: str, log_type: str = "info"):
        """Add a message to the log panel with modern styling."""
        if hasattr(self, 'log_text'):
            import datetime
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            
            # Update counter
            self.log_count += 1
            self.log_counter.configure(text=f"({self.log_count})")
            
            # Add message with timestamp and color coding
            self.log_text.insert("end", f"[{timestamp}] ", "timestamp")
            self.log_text.insert("end", f"{message}\n", log_type)
            self.log_text.see("end")
            
            # Flash status indicator
            self._flash_log_status(log_type)
    
    def _flash_log_status(self, log_type: str):
        """Flash the status indicator based on log type."""
        colors = {
            "info": "#58a6ff",
            "success": "#3fb950", 
            "warning": "#d29922",
            "error": "#f85149"
        }
        color = colors.get(log_type, "#58a6ff")
        self.log_status_label.configure(text_color=color)
        
        # Reset to green after 1 second
        self.after(1000, lambda: self.log_status_label.configure(text_color="#4ade80"))
    
    def _clear_log(self):
        """Clear the log panel."""
        if hasattr(self, 'log_text'):
            self.log_text.delete("1.0", "end")
            self.log_count = 0
            self.log_counter.configure(text="(0)")
    
    def _save_log(self):
        """Save log content to a file."""
        if hasattr(self, 'log_text'):
            content = self.log_text.get("1.0", "end-1c")
            if not content.strip():
                messagebox.showinfo("Info", "Log is empty!")
                return
            
            from tkinter import filedialog
            filename = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                initialname=f"video_editor_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            )
            
            if filename:
                try:
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(content)
                    messagebox.showinfo("Success", f"Log saved to:\n{filename}")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to save log:\n{str(e)}")
    
    def _toggle_log_panel(self):
        """Toggle log panel visibility."""
        if self.log_panel_visible:
            self.log_frame.pack_forget()
            self.toggle_log_btn.configure(text="👁️ Show")
            self.log_panel_visible = False
        else:
            self.log_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
            self.toggle_log_btn.configure(text="👁️ Hide")
            self.log_panel_visible = True


# ════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    load_settings()
    app = VideoEditorApp()
    app.mainloop()
