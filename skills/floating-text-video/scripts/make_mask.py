"""Build an occlusion matte from explicitly traced polygons/lines, never guessed coordinates."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps


def build(image: Image.Image, spec: dict, expand: int, feather: float):
    width, height = image.size
    space = spec.get("coordinate_space", "normalized")
    if space not in ("normalized", "pixels"):
        raise ValueError("coordinate_space must be normalized or pixels")
    if space == "pixels" and spec.get("source_size") != [width, height]:
        raise ValueError("Pixel coordinates require source_size exactly matching the image")
    shapes = spec.get("shapes")
    if not isinstance(shapes, list) or not shapes:
        raise ValueError("Provide at least one traced shape; there are no built-in subject coordinates")
    core_image = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(core_image)
    for shape in shapes:
        kind = shape.get("type")
        points = shape.get("points", [])
        if kind not in ("polygon", "line") or len(points) < (3 if kind == "polygon" else 2):
            raise ValueError("Each polygon needs >=3 points; each line needs >=2 points")
        converted = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("Each point must be [x, y]")
            x, y = float(point[0]), float(point[1])
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("Coordinates must be finite")
            if space == "normalized":
                if not 0 <= x <= 1 or not 0 <= y <= 1:
                    raise ValueError("Normalized coordinates must fall within 0..1")
                x, y = x * (width - 1), y * (height - 1)
            elif not 0 <= x < width or not 0 <= y < height:
                raise ValueError("Pixel coordinates must be inside the source image")
            converted.append((round(x), round(y)))
        if kind == "polygon":
            draw.polygon(converted, fill=255)
        else:
            stroke = float(shape.get("width", .005 if space == "normalized" else 3))
            if not math.isfinite(stroke) or stroke <= 0:
                raise ValueError("Line width must be positive")
            stroke = max(1, round(stroke * min(width, height) if space == "normalized" else stroke))
            draw.line(converted, fill=255, width=stroke, joint="curve")
            radius = stroke / 2
            for x, y in (converted[0], converted[-1]):
                draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=255)
    core = np.asarray(core_image)
    if not np.any(core):
        raise ValueError("Shapes produced an empty foreground")
    expanded = core.copy()
    if expand:
        expanded = cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*expand+1, 2*expand+1)))
    soft = cv2.GaussianBlur(expanded, (0, 0), feather) if feather else expanded
    # Feather the outside safety margin only. Traced foreground stays fully opaque.
    matte = np.maximum(soft, core)
    return matte, core


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--shapes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--expand", type=int, default=3, help="Outward safety margin in source pixels")
    parser.add_argument("--feather", type=float, default=.8, help="Outward edge softness in source pixels")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.expand <= 100 or not math.isfinite(args.feather) or not 0 <= args.feather <= 100:
        parser.error("expand and feather must be finite values from 0 to 100")
    if args.output.suffix.lower() != ".png":
        parser.error("The matte output must be a PNG to retain exact grayscale values")
    sources = {args.image.resolve(), args.shapes.resolve()}
    outputs = [args.output] + ([args.review] if args.review else [])
    if len({p.resolve() for p in outputs}) != len(outputs):
        parser.error("Matte and review outputs must be different files")
    for output in outputs:
        if output.resolve() in sources:
            parser.error("An output cannot replace an input")
        if output.exists() and not args.overwrite:
            parser.error(f"Output exists: {output}; use a new path or --overwrite")
    with Image.open(args.image) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    spec = json.loads(args.shapes.read_text(encoding="utf-8-sig"))
    matte, core = build(image, spec, args.expand, args.feather)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(matte).save(args.output)
    if args.review:
        rgb = np.asarray(image, dtype=np.float32)
        alpha = matte.astype(np.float32)[..., None] / 255 * .4
        review = np.clip(rgb * (1-alpha) + np.array([255, 40, 50]) * alpha, 0, 255).astype(np.uint8)
        contours, _ = cv2.findContours((matte >= 128).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(review, contours, -1, (255, 210, 50), 1)
        args.review.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(review).save(args.review)
    print(json.dumps({"output": str(args.output.resolve()), "size": image.size, "mode": "L", "traced_core_pixels": int((core == 255).sum()), "core_fully_opaque": bool(np.all(matte[core == 255] == 255))}, ensure_ascii=False))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
