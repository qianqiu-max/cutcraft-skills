"""Build or render a portable paper-plane curtain project (Pillow + FFmpeg)."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def probe(path):
    command = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    return json.loads(subprocess.check_output(command))


def artwork(path):
    """Original four-fold paper plane; the lower rear crease is the tow point."""
    size = (1040, 784)
    image = Image.new("RGBA", size)
    pen = ImageDraw.Draw(image)
    tip = (.991, .015)
    fold = (.196, .550)
    tow = (.217, .802)
    wing = (.535, .988)

    def face(points, color):
        pen.polygon([(round(x * size[0]), round(y * size[1])) for x, y in points], fill=color)

    face([(.012, .236), tip, fold], "#f9f7f0")
    face([fold, tip, tow], "#bcbec0")
    face([tow, tip, (.337, .665)], "#969da4")
    face([(.224, .606), tip, wing], "#e6e7e6")
    face([(.224, .606), wing, (.245, .610)], "#d6d9da")
    image.resize((520, 392), Image.Resampling.LANCZOS).save(path)


def find_font(explicit, title, size):
    windows = Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [explicit] if explicit else [
        windows / name for name in ("STXINGKA.TTF", "simkai.ttf", "msyhbd.ttc", "arialbd.ttf")
    ]
    if not explicit:
        candidates.extend(["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/Supplemental/Songti.ttc",
                           "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"])
        if shutil.which("fc-match"):
            match = subprocess.run(["fc-match", "-s", "-f", "%{file}\n", "serif:lang=zh-cn"],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
            candidates.extend(match.stdout.splitlines())
        candidates.append("DejaVuSans-Bold.ttf")
    for candidate in dict.fromkeys(candidates):
        try:
            font = ImageFont.truetype(str(candidate), size)
            missing = bytes(font.getmask("\U0010ffff"))
            if all(bytes(font.getmask(char)) != missing for char in set(title) if not char.isspace()):
                return font
        except (OSError, ValueError):
            continue
    raise ValueError("No installed font covers the title. Pass --font with a licensed TTF, TTC or OTF file.")


def title_matte(folder, recipe, font_path=None, sample_dir=None):
    canvas, title = recipe["canvas"], recipe["title"]
    width, height = canvas["width"], canvas["height"]
    key = hashlib.sha256(json.dumps([width, height, title], sort_keys=True).encode()).hexdigest()
    matte_path = folder / "media/title-mask.png"
    info_path = folder / "media/title-mask.json"
    if not font_path:
        origins = [matte_path.parent]
        if sample_dir is not None:
            origins.append(sample_dir)
        for origin in origins:
            raster = origin / "title-mask.png"
            record = origin / "title-mask.json"
            if not raster.is_file() or not record.is_file():
                continue
            if json.loads(record.read_text(encoding="utf-8"))["key"] != key:
                continue
            with Image.open(raster) as image:
                if image.size != (width, height):
                    continue
                cached = image.convert("L")
            if origin != matte_path.parent:
                shutil.copyfile(raster, matte_path)
                shutil.copyfile(record, info_path)
            return cached
    text = title["text"]
    image = Image.new("L", (width, height))
    font_name = None
    if text.strip():
        font = find_font(font_path, text, max(1, round(height * title["height_ratio"])))
        font_name = font.getname()[0]
        left, top, right, bottom = font.getbbox(text)
        glyphs = Image.new("L", (max(1, right - left), max(1, bottom - top)))
        ImageDraw.Draw(glyphs).text((-left, -top), text, font=font, fill=255)
        glyphs.thumbnail((max(1, round(width * title["max_width_ratio"])), height), Image.Resampling.LANCZOS)
        cx, cy = title["center"]
        image.paste(glyphs, (round(cx * width - glyphs.width / 2), round(cy * height - glyphs.height / 2)))
    image.save(matte_path)
    write_json(info_path, {"key": key, "font_family": font_name})
    return image


def media_path(folder, relative):
    path = (folder / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(folder) or not path.is_file():
        raise ValueError(f"Project media must be an existing relative file: {relative}")
    return path


def validate(recipe):
    if recipe.get("version") != 1:
        raise ValueError("Unsupported recipe version")
    canvas = recipe["canvas"]
    for key in ("width", "height"):
        if type(canvas[key]) is not int or canvas[key] < 2 or canvas[key] % 2:
            raise ValueError(f"{key} must be a positive even pixel size")
    duration = canvas["duration"]
    if not 0 < duration < float("inf") or not 1 <= canvas["fps"] <= 120:
        raise ValueError("Duration must be positive and fps must be between 1 and 120")
    flight, curtain, title = recipe["flight"], recipe["curtain"], recipe["title"]
    if not 0 <= flight["start"] < flight["end"] < curtain["finish"] <= duration:
        raise ValueError("Use 0 <= flight.start < flight.end < curtain.finish <= canvas.duration (seconds)")
    if not all(0 < flight[key] <= 2 for key in ("plane_width", "end_plane_width")) or not 0 <= curtain["feather_px"] <= 20:
        raise ValueError("Plane widths must be in (0, 2] and feather_px in [0, 20]")
    if not 0 < title["height_ratio"] <= 2 or not 0 < title["max_width_ratio"] <= 1:
        raise ValueError("Check title height_ratio and max_width_ratio")
    for xy in [flight["start_tail"], flight["end_tail"], curtain["final_tip"], flight["anchor"], title["center"]]:
        if len(xy) != 2 or not all(math.isfinite(v) for v in xy):
            raise ValueError("Points need two finite coordinates")
    if min(flight["anchor"]) < 0 or max(flight["anchor"]) > 1:
        raise ValueError("Plane anchor coordinates must be within [0, 1]")
    if not 0 < curtain["bottom_reach"] <= 1 or not 0 <= curtain["sag"] <= 2:
        raise ValueError("Check curtain bottom_reach and sag")
    if type(recipe["audio"]["preserve"]) is not bool:
        raise ValueError("audio.preserve must be true or false")


def initialize(args):
    target = args.project.resolve()
    if target.exists():
        raise ValueError(f"Create a new project directory; this path exists: {target}")
    source = args.source.resolve(strict=True)
    metadata = probe(source)
    stream = next((s for s in metadata["streams"] if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    if not stream:
        raise ValueError("The source must contain an image or video stream")
    raw_w, raw_h = stream["width"], stream["height"]
    sar = stream.get("sample_aspect_ratio", "1:1").split(":")
    if len(sar) == 2 and all(s.isdigit() and int(s) > 0 for s in sar):
        raw_w = round(raw_w * int(sar[0]) / int(sar[1]))
    rotation = next((s["rotation"] for s in stream.get("side_data_list", []) if "rotation" in s), 0)
    if round(rotation / 90) % 2:
        raw_w, raw_h = raw_h, raw_w
    width = args.width if args.width is not None else max(2, 2 * round(raw_w / 2))
    height = args.height if args.height is not None else max(2, 2 * round(raw_h / 2))
    if (args.width is None) != (args.height is None):
        raise ValueError("Set both --width and --height, or omit both to use the source aspect ratio")
    seconds = stream.get("duration") or metadata["format"].get("duration") or 6.0
    duration = args.duration if args.duration is not None else float(seconds)
    period = min(6.0, duration)
    source_name = "media/source" + source.suffix.lower()
    recipe = {
        "version": 1, "source": source_name, "plane": "media/plane.png",
        "canvas": {"width": width, "height": height, "fps": args.fps, "duration": duration},
        "title": {"text": args.title, "height_ratio": .39, "max_width_ratio": .74, "center": [.50, .49]},
        "flight": {"start": 0, "end": period * .55, "start_tail": [-.232, 1.230], "end_tail": [1.034, -.031],
                   "plane_width": .180, "end_plane_width": .140, "anchor": [.217, .802]},
        "curtain": {"finish": period * .852, "final_tip": [2.04, -.99], "bottom_reach": .515,
                    "sag": .25, "feather_px": .48},
        "audio": {"preserve": True},
    }
    validate(recipe)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as work:
        stage = Path(work) / "project"
        (stage / "media").mkdir(parents=True)
        shutil.copyfile(source, stage / source_name)
        if args.plane:
            with Image.open(args.plane) as plane:
                rgba = plane.convert("RGBA")
                if rgba.getchannel("A").getextrema() in ((255, 255), (0, 0)):
                    raise ValueError("The custom paper-plane sprite needs visible artwork on a transparent background")
                rgba.save(stage / recipe["plane"])
        else:
            artwork(stage / recipe["plane"])
        sample_dir = Path(__file__).resolve().parent.parent / "assets/initial-snow-title"
        title_matte(stage, recipe, args.font, sample_dir=sample_dir)
        write_json(stage / "recipe.json", recipe)
        shutil.copyfile(__file__, stage / "render.py")
        stage.rename(target)
    print(f"Created {target / 'recipe.json'}")


def interpolate(start, end, progress):
    return tuple(a + (b - a) * progress for a, b in zip(start, end))


def curtain_mask(size, tip, curtain):
    """Two inward-bowed edges meet at the same point as the plane's rear fold."""
    width, height = size
    tx, ty = tip
    mask = Image.new("L", size)
    if tx <= 0 or ty >= 1:
        return mask
    span = 1 - ty
    lower_x = tx * curtain["bottom_reach"]
    top_curve, side_curve = [], []
    for step in range(81):
        u = step / 80
        # Top edge runs from left to the tow point, with its greatest sag near the middle.
        top_y = ty + tx * (.047 * (1 - u) + 4 * curtain["sag"] * u * (1 - u))
        top_curve.append((round(tx * u * width), round(top_y * height)))
        # The right seam bends left toward the bottom, leaving the lower-right corner covered.
        side_x = tx + (lower_x - tx) * (u + .42 * u * (1 - u))
        side_curve.append((round(side_x * width), round((ty + span * u) * height)))
    ImageDraw.Draw(mask).polygon(top_curve + side_curve + [(0, height)], fill=255)
    if curtain["feather_px"]:
        mask = mask.filter(ImageFilter.GaussianBlur(curtain["feather_px"]))
    return mask


def composite(scene, time, title, sprite, recipe):
    flight, curtain = recipe["flight"], recipe["curtain"]
    if time >= curtain["finish"]:
        return scene
    flying = time <= flight["end"]
    if flying:
        progress = max(0.0, (time - flight["start"]) / (flight["end"] - flight["start"]))
        tip = interpolate(flight["start_tail"], flight["end_tail"], progress)
    else:
        progress = (time - flight["end"]) / (curtain["finish"] - flight["end"])
        tip = interpolate(flight["end_tail"], curtain["final_tip"], progress)
    matte = ImageChops.lighter(title, curtain_mask(scene.size, tip, curtain))
    frame = Image.composite(scene, Image.new("RGB", scene.size), matte)
    if flying and time >= flight["start"]:
        ratio = flight["plane_width"] + (flight["end_plane_width"] - flight["plane_width"]) * progress
        plane_w = max(1, round(scene.width * ratio))
        plane = sprite.resize((plane_w, max(1, round(plane_w * sprite.height / sprite.width))), Image.Resampling.LANCZOS)
        ax, ay = flight["anchor"]
        origin = (round(tip[0] * scene.width - ax * plane.width), round(tip[1] * scene.height - ay * plane.height))
        frame.paste(plane, origin, plane.getchannel("A"))
    return frame


def render(args):
    folder = args.project.resolve(strict=True)
    recipe = json.loads((folder / "recipe.json").read_text(encoding="utf-8-sig"))
    validate(recipe)
    source = media_path(folder, recipe["source"])
    canvas = recipe["canvas"]
    width, height, fps = canvas["width"], canvas["height"], canvas["fps"]
    frames = max(1, math.ceil(canvas["duration"] * fps - 1e-8))
    seconds = frames / fps
    scene_size = (width, height)
    title = title_matte(folder, recipe, args.font)
    with Image.open(media_path(folder, recipe["plane"])) as image:
        sprite = image.convert("RGBA")
    common = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
    fit = f"scale=iw*if(gt(sar\\,0)\\,sar\\,1):ih,setsar=1,scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"
    vf = f"{fit},tpad=stop_mode=clone:stop_duration={seconds:.8f},fps={fps}"
    decoder = common + ["-i", str(source), "-map", "0:V:0", "-an", "-vf", vf, "-frames:v", str(frames),
                        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
    encoder = common + ["-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{width}x{height}",
                        "-framerate", str(fps), "-i", "pipe:0"]
    audio = recipe["audio"]["preserve"] and any(s["codec_type"] == "audio" for s in probe(source)["streams"])
    if audio:
        encoder.extend(["-i", str(source), "-map", "0:v", "-map", "1:a:0", "-af", "apad", "-c:a", "aac", "-b:a", "192k"])
    else:
        encoder.extend(["-map", "0:v", "-an"])
    encoder.extend(["-t", f"{seconds:.8f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart"])
    with tempfile.TemporaryDirectory(dir=folder) as temp:
        output = Path(temp) / "output.mp4"
        with subprocess.Popen(decoder, stdout=subprocess.PIPE) as reader:
            try:
                with subprocess.Popen(encoder + [str(output)], stdin=subprocess.PIPE) as writer:
                    try:
                        for number in range(frames):
                            raw = reader.stdout.read(width * height * 3)
                            if len(raw) != width * height * 3:
                                raise ValueError(f"Source decoder ended early at frame {number}")
                            if number / fps < recipe["curtain"]["finish"]:
                                scene = Image.frombytes("RGB", scene_size, raw)
                                raw = composite(scene, number / fps, title, sprite, recipe).tobytes()
                            writer.stdin.write(raw)
                        writer.stdin.close()
                        if writer.wait():
                            raise ValueError("FFmpeg failed to encode the output")
                    finally:
                        if writer.poll() is None:
                            writer.kill()
                if reader.wait():
                    raise ValueError("FFmpeg failed to decode the source")
            finally:
                reader.stdout.close()
                if reader.poll() is None:
                    reader.kill()
        output.replace(folder / "output.mp4")
    print(f"Rendered {folder / 'output.mp4'} ({frames} frames, {fps} fps, {width}x{height}, audio={bool(audio)})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a new portable project")
    init.add_argument("--project", type=Path, required=True)
    init.add_argument("--source", type=Path, required=True, help="One still image or video")
    init.add_argument("--title", default="", help="Scene-filled opening title; omit for a plain black opening")
    init.add_argument("--plane", type=Path, help="Optional transparent plane image, nose pointing upper right")
    init.add_argument("--font", type=Path, help="Optional local TTF/TTC/OTF used to rasterize the title")
    init.add_argument("--width", type=int)
    init.add_argument("--height", type=int)
    init.add_argument("--fps", type=int, default=30)
    init.add_argument("--duration", type=float, help="Seconds; defaults to source duration, or 6 for a still")
    run = commands.add_parser("render", help="Render (or rerender after editing recipe.json)")
    run.add_argument("--project", type=Path, required=True)
    run.add_argument("--font", type=Path, help="Regenerate the title matte with this font")
    args = parser.parse_args()
    try:
        (initialize if args.command == "init" else render)(args)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        sys.exit(f"Error: {error}")


if __name__ == "__main__":
    main()
