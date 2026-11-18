"""Create or rerender a portable live-footage title fly-through (Pillow + FFmpeg)."""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def probe(path):
    return json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))


def font_for(text, explicit):
    size = 560
    windows = Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts"
    choices = [explicit] if explicit else [
        windows / "msyhbd.ttc", windows / "simhei.ttf", windows / "arialbd.ttf",
        "/System/Library/Fonts/PingFang.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
    if not explicit:
        if shutil.which("fc-match"):
            matches = subprocess.run(["fc-match", "-s", "-f", "%{file}\n", "sans:bold:lang=zh-cn"],
                                     stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", check=False)
            choices.extend(matches.stdout.splitlines())
        choices.append("DejaVuSans-Bold.ttf")
    for name in dict.fromkeys(choices):
        try:
            font = ImageFont.truetype(str(name), size)
            missing = bytes(font.getmask("\U0010ffff"))
            if all(bytes(font.getmask(char)) != missing for char in set(text) if not char.isspace()):
                return font
        except (OSError, ValueError):
            pass
    raise ValueError("No font covers the title. Pass --font with a licensed TTF, OTF or TTC.")


def glyph_matte(folder, text, explicit=None, sample=None):
    local = folder / "media"
    if not explicit:
        for origin in (local, sample):
            if origin is None or not (origin / "glyph.json").is_file() or not (origin / "glyph.png").is_file():
                continue
            record = json.loads((origin / "glyph.json").read_text(encoding="utf-8"))
            if record.get("text") == text:
                with Image.open(origin / "glyph.png") as image:
                    matte = image.convert("L")
                if origin != local:
                    shutil.copyfile(origin / "glyph.png", local / "glyph.png")
                    write_json(local / "glyph.json", record)
                return matte
    font = font_for(text, explicit)
    x0, y0, x1, y1 = font.getbbox(text)
    glyph = Image.new("L", (max(1, x1-x0), max(1, y1-y0)))
    ImageDraw.Draw(glyph).text((-x0, -y0), text, fill=255, font=font)
    bounds = glyph.getbbox()
    if bounds is None:
        raise ValueError("Title contains no visible strokes")
    glyph = glyph.crop(bounds)
    glyph.save(local / "glyph.png")
    write_json(local / "glyph.json", {"text": text, "font_family": font.getname()[0]})
    return glyph


def automatic_anchor(glyph, aspect):
    """Largest white square after aspect correction approximates the widest safe viewport inside an ink stroke."""
    normalized_w = glyph.width / aspect
    scale = 320 / max(normalized_w, glyph.height)
    width, height = max(1, round(normalized_w * scale)), max(1, round(glyph.height * scale))
    pixels = glyph.resize((width, height), Image.Resampling.BOX).tobytes()
    previous = [0] * (width + 1)
    best, distance, anchor = 0, float("inf"), None
    for y in range(height):
        row = [0] * (width + 1)
        for x in range(width):
            if pixels[y * width + x] < 254:
                continue
            side = 1 + min(previous[x], previous[x + 1], row[x])
            row[x + 1] = side
            if side >= best:
                cx, cy = (x + 1 - side / 2) / width, (y + 1 - side / 2) / height
                score = (cx - .5) ** 2 + (cy - .5) ** 2
                if side > best or score < distance:
                    best, distance, anchor = side, score, (cx * glyph.width, cy * glyph.height)
        previous = row
    if anchor is None:
        # Narrow isolated strokes can vanish from the reduced image.
        # Search full-resolution bands near the center first. Erosion keeps the
        # chosen point several pixels clear of antialiased stroke boundaries.
        step = max(128, glyph.height)
        bands = sorted(range(0, glyph.width, step), key=lambda left: abs(left + step/2 - glyph.width/2))
        for left in bands:
            band = glyph.crop((left, 0, min(left+step, glyph.width), glyph.height))
            interior = band.point(lambda v: 255 if v == 255 else 0).filter(ImageFilter.MinFilter(9))
            for y in sorted(range(band.height), key=lambda row: abs(row-band.height/2)):
                row = interior.crop((0, y, band.width, y+1))
                pixels = row.tobytes()
                if 255 in pixels:
                    return left + pixels.index(255) + .5, y + .5
        raise ValueError("No solid ink found. Choose a font with thicker strokes.")
    return anchor


def inside_height(glyph, anchor, aspect):
    """Find the tallest viewport around the chosen point wholly inside an opaque stroke."""
    cx, cy = anchor
    lo, hi = 0., 2 * min(cy, glyph.height - cy, cx / aspect, (glyph.width - cx) / aspect)
    # Quantized crop bounds also reserve one source pixel for bicubic sampling.
    for _ in range(20):
        height = (lo + hi) / 2
        width = height * aspect
        rect = (math.floor(cx-width/2)-1, math.floor(cy-height/2)-1,
                math.ceil(cx+width/2)+1, math.ceil(cy+height/2)+1)
        if glyph.crop(rect).getextrema()[0] >= 254:
            lo = height
        else:
            hi = height
    if lo < .25:
        raise ValueError("The anchor must lie inside solid ink. Use auto or a thicker font.")
    return lo


def validate(recipe):
    if recipe["version"] != 1:
        raise ValueError("Unsupported recipe version")
    canvas, title, motion = recipe["canvas"], recipe["title"], recipe["motion"]
    for key in ("width", "height"):
        if type(canvas[key]) is not int or canvas[key] < 2 or canvas[key] % 2:
            raise ValueError("Canvas dimensions must be positive even pixel counts")
    if type(canvas["fps"]) is not int or not 1 <= canvas["fps"] <= 120:
        raise ValueError("Use an integer fps from 1 to 120")
    if not math.isfinite(canvas["duration"]) or not 0 < motion["entrance_end"] < motion["fill_time"] <= canvas["duration"]:
        raise ValueError("Use 0 < motion.entrance_end < motion.fill_time <= canvas.duration (seconds)")
    if not isinstance(title["text"], str) or not title["text"].strip() or len(title["text"]) > 80 or "\n" in title["text"]:
        raise ValueError("Use a visible single-line title of up to 80 characters")
    if not all(0 < title[k] <= 1 for k in ("max_width", "max_height")):
        raise ValueError("max_width and max_height are fractions of the frame in (0, 1]")
    if not 0 < motion["entrance_scale"] <= 1 or not 0 < motion["zoom_exponent"] <= 6:
        raise ValueError("Check the entrance scale or zoom exponent")
    points = [title["center"]] if motion["anchor"] == "auto" else [title["center"], motion["anchor"]]
    for point in points:
        if not isinstance(point, list) or len(point) != 2 or not all(isinstance(v, (int,float)) and 0 <= v <= 1 for v in point):
            raise ValueError("Use normalized [x, y] coordinates in [0, 1]")
    if type(recipe["audio"]["preserve"]) is not bool:
        raise ValueError("audio.preserve must be a boolean")


def initialize(args):
    folder = args.project.resolve()
    if folder.exists():
        raise ValueError("Choose a new project directory")
    source = args.source.resolve(strict=True)
    data = probe(source)
    stream = next((s for s in data["streams"] if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    if not stream:
        raise ValueError("An image or video stream is required")
    w, h = stream["width"], stream["height"]
    sar = stream.get("sample_aspect_ratio", "").split(":")
    if len(sar) == 2 and all(n.isdecimal() and int(n)>0 for n in sar):
        w = round(w * int(sar[0]) / int(sar[1]))
    angle = next((d["rotation"] for d in stream.get("side_data_list", []) if "rotation" in d), 0)
    if round(angle / 90) % 2:
        w, h = h, w
    if (args.width is None) != (args.height is None):
        raise ValueError("Specify both width and height, or omit both")
    w = args.width if args.width is not None else max(2, 2 * round(w/2))
    h = args.height if args.height is not None else max(2, 2 * round(h/2))
    duration = args.duration if args.duration is not None else float(stream.get("duration") or data["format"].get("duration") or 6)
    phase = min(2., duration / 3)
    recipe = {
        "version": 1, "source": "media/source" + source.suffix.lower(),
        "canvas": {"width":w, "height":h, "fps":args.fps, "duration":duration},
        "title": {"text":args.title, "max_width":.86, "max_height":.36, "center":[.5,.5]},
        "motion": {"entrance_end":phase, "fill_time":2*phase, "entrance_scale":.52, "zoom_exponent":1.7,
                   "anchor":"auto"},
        "audio": {"preserve": True}
    }
    validate(recipe)
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder.parent) as temp:
        stage = Path(temp) / "project"
        (stage / "media").mkdir(parents=True)
        shutil.copyfile(source, stage / recipe["source"])
        glyph_matte(stage, args.title, args.font, Path(__file__).resolve().parent.parent / "assets/demo-title")
        write_json(stage / "recipe.json", recipe)
        shutil.copyfile(__file__, stage / "render.py")
        stage.rename(folder)
    print(f"Created {folder / 'recipe.json'}")


class AnimatedTitle:
    def __init__(self, glyph, recipe):
        self.glyph = glyph
        self.motion = recipe["motion"]
        title = recipe["title"]
        self.size = (recipe["canvas"]["width"], recipe["canvas"]["height"])
        w, h = self.size
        self.fit = min(w * title["max_width"] / glyph.width, h * title["max_height"] / glyph.height)
        self.center = (title["center"][0] * w, title["center"][1] * h)
        anchor = self.motion["anchor"]
        self.anchor = automatic_anchor(glyph, w/h) if anchor == "auto" else (anchor[0]*glyph.width, anchor[1]*glyph.height)
        self.final_zoom = max(1., 1.035 * h / (self.fit * inside_height(glyph, self.anchor, w/h)))

    def mask_at(self, seconds):
        width, height = self.size
        enter, finish = self.motion["entrance_end"], self.motion["fill_time"]
        ax, ay = self.anchor
        cx, cy = self.center
        if seconds < enter:
            progress = seconds / enter
            ease = 1 - (1-progress)**2
            scale = self.fit * (self.motion["entrance_scale"] + (1-self.motion["entrance_scale"]) * ease)
            # During the entrance the complete title scales about its center.
            sx = cx + (ax-self.glyph.width/2)*scale
            sy = cy + (ay-self.glyph.height/2)*scale
            opacity = ease
        else:
            progress = min(1., (seconds-enter)/(finish-enter))
            scale = self.fit * (1 + (self.final_zoom-1) * progress**self.motion["zoom_exponent"])
            # A point of ink, often off the visual center, approaches screen center as the view enters it.
            ox = cx + (ax-self.glyph.width/2)*self.fit
            oy = cy + (ay-self.glyph.height/2)*self.fit
            sx, sy = ox + (width/2-ox)*progress, oy + (height/2-oy)*progress
            opacity = 1.
        mapping = (1/scale, 0, ax-sx/scale, 0, 1/scale, ay-sy/scale)
        mask = self.glyph.transform(self.size, Image.Transform.AFFINE, mapping, Image.Resampling.BICUBIC, fillcolor=0)
        if opacity < 1:
            mask = mask.point([round(v*opacity) for v in range(256)])
        return mask


def media_path(folder, relative):
    path = (folder / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(folder) or not path.is_file():
        raise ValueError(f"Project media must be an existing relative file: {relative}")
    return path


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
    glyph = glyph_matte(folder, recipe["title"]["text"], args.font)
    title = AnimatedTitle(glyph, recipe)
    black = Image.new("RGB", scene_size)
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
                            if number / fps < recipe["motion"]["fill_time"]:
                                scene = Image.frombytes("RGB", scene_size, raw)
                                raw = Image.composite(scene, black, title.mask_at(number / fps)).tobytes()
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
    init.add_argument("--title", required=True, help="Short, single-line text to fly through")
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
