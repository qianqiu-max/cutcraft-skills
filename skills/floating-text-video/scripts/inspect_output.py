"""Inspect decoded video, sampled images and real alpha; no claim of real-time viewing."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw


def tool(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} is not on PATH; install/configure FFmpeg before inspection")
    return path


def rational(value):
    numerator, separator, denominator = str(value).partition("/")
    try:
        divisor = float(denominator) if separator else 1.0
        result = float(numerator) / divisor if divisor else 0.0
        return result if math.isfinite(result) else 0.0
    except ValueError:
        return 0.0


def preview_time(video, format_info):
    fps = rational(video.get("avg_frame_rate", "0/1"))
    if fps <= 0:
        fps = rational(video.get("r_frame_rate", "30/1"))
    fps = fps if fps > 0 else 30.0
    if video.get("duration") not in (None, "N/A"):
        duration = float(video["duration"])
    elif video.get("duration_ts") is not None:
        duration = int(video["duration_ts"]) * rational(video["time_base"])
    elif video.get("nb_frames") not in (None, "N/A"):
        duration = int(video["nb_frames"]) / fps
    else:
        duration = float(format_info["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("Cannot establish a positive video duration")
    # Seek slightly before the last nominal frame, not to the EOF timestamp.
    return fps, duration, max(0.0, duration - 1.0/fps - .001)


def checker_composite(rgba):
    width, height = rgba.size
    yy, xx = np.mgrid[0:height, 0:width]
    shade = np.where(((xx//16) + (yy//16)) % 2, 185, 225).astype(np.uint8)
    background = Image.fromarray(np.repeat(shade[..., None], 3, axis=2)).convert("RGBA")
    return Image.alpha_composite(background, rgba).convert("RGB")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not 2 <= args.samples <= 120:
        parser.error("samples must be from 2 to 120")
    if not args.video.is_file():
        parser.error(f"Input is not a file: {args.video}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    existing = list(args.output_dir.glob("sample-*.png")) + list(args.output_dir.glob("contact-sheet-*.jpg"))
    report_path = args.output_dir / "inspection.json"
    if (report_path.exists() or existing) and not args.overwrite:
        parser.error("Inspection outputs already exist; choose another directory or --overwrite")
    ffmpeg, ffprobe = tool("ffmpeg"), tool("ffprobe")
    probe = json.loads(subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(args.video)], capture_output=True, check=True).stdout)
    streams = [s for s in probe["streams"] if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")]
    if not streams:
        raise RuntimeError("No playable video stream")
    stream = streams[0]
    fps, duration, last = preview_time(stream, probe["format"])
    decode = subprocess.run([ffmpeg, "-v", "error", "-xerror", "-i", str(args.video), "-f", "null", "-"], capture_output=True)
    times = [last * i/(args.samples-1) for i in range(args.samples)]
    sampled = []
    thumbnails = []
    for index, target in enumerate(times):
        actual_seek = target
        image = None
        last_error = ""
        for delta in (0, 1/fps, 2/fps):
            actual_seek = max(0.0, target-delta)
            extraction = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{actual_seek:.6f}", "-i", str(args.video), "-map", f"0:{stream['index']}", "-frames:v", "1", "-vf", "scale=480:270:force_original_aspect_ratio=decrease", "-pix_fmt", "rgba", "-c:v", "png", "-f", "image2pipe", "pipe:1"], capture_output=True)
            last_error = extraction.stderr.decode("utf-8", "replace")
            if extraction.returncode == 0 and extraction.stdout:
                with Image.open(io.BytesIO(extraction.stdout)) as extracted:
                    image = extracted.convert("RGBA")
                break
        if image is None:
            raise RuntimeError(f"Cannot sample frame at {target:.4f}s: {last_error}")
        output = args.output_dir / f"sample-{index:03d}.png"
        if output.resolve() == args.video.resolve():
            raise RuntimeError("Refusing to replace the input video")
        image.save(output)
        alpha = np.asarray(image)[:, :, 3]
        sampled.append({"requested_seconds": target, "seek_seconds": actual_seek, "file": output.name, "alpha_min": int(alpha.min()), "alpha_max": int(alpha.max()), "transparent_fraction": float(np.mean(alpha == 0)), "nonopaque_fraction": float(np.mean(alpha < 255)), "partial_alpha_fraction": float(np.mean((alpha > 0) & (alpha < 255)))})
        thumb = checker_composite(image)
        panel = Image.new("RGB", (480, 296), (18, 20, 22))
        panel.paste(thumb, ((480-thumb.width)//2, 26+(270-thumb.height)//2))
        ImageDraw.Draw(panel).text((10, 7), f"{actual_seek:.3f} s | alpha {int(alpha.min())}..{int(alpha.max())}", fill="white")
        thumbnails.append(panel)
    for start in range(0, len(thumbnails), 12):
        batch = thumbnails[start:start+12]
        rows = math.ceil(len(batch)/4)
        sheet = Image.new("RGB", (1920, rows*296), (18, 20, 22))
        for index, image in enumerate(batch):
            sheet.paste(image, ((index % 4)*480, (index//4)*296))
        sheet.save(args.output_dir/f"contact-sheet-{start//12+1}.jpg", quality=93)
    has_transparency = any(s["alpha_min"] < 255 for s in sampled)
    has_visible = any(s["alpha_max"] > 0 for s in sampled)
    digest = hashlib.sha256()
    with args.video.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b""):
            digest.update(chunk)
    report = {"input": str(args.video.resolve()), "metadata": probe, "duration_seconds": duration, "nominal_fps": fps, "decode_exit_code": decode.returncode, "decode_errors": decode.stderr.decode("utf-8", "replace"), "sampled_frames": sampled, "alpha": {"reported_pixel_format": stream.get("pix_fmt"), "sampled_transparency_present": has_transparency, "sampled_visible_content_present": has_visible, "verdict": "Real transparency and visible content detected in decoded samples" if has_transparency and has_visible else "Samples are wholly transparent" if has_transparency else "No transparency found in decoded samples"}, "sha256": digest.hexdigest(), "scope": "Full technical decode plus sampled images only. No claim of complete real-time visual playback or auditory review."}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path.resolve()), "decode_exit_code": decode.returncode, "samples": len(sampled), "duration_seconds": duration, "alpha": report["alpha"]}, ensure_ascii=False))
    if decode.returncode:
        raise SystemExit(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
