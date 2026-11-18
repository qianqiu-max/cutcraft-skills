"""Render a project as a protected composite or a transparent text overlay."""
from __future__ import annotations
import argparse, json, math, os, shutil, subprocess, sys, tempfile, uuid
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


def executable(name, explicit=None):
    value = explicit or os.environ.get(name.upper()) or shutil.which(name)
    if not value or not Path(value).is_file():
        raise RuntimeError(f"{name} not found; install it or provide --{name}/the {name.upper()} environment variable")
    return str(value)


def media_info(path, ffprobe=None):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        with Image.open(path) as im:
            if getattr(im, 'is_animated', False):
                raise ValueError('Animated images are not supported; convert to a video first')
            im = ImageOps.exif_transpose(im)
            return {'kind': 'image', 'width': im.width, 'height': im.height, 'duration': None}
    except (OSError, SyntaxError):
        pass
    data = json.loads(subprocess.check_output([executable('ffprobe', ffprobe), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))
    stream = next((s for s in data['streams'] if s['codec_type'] == 'video'), None)
    if not stream:
        raise ValueError(f'No video stream: {path}')
    width, height = int(stream['width']), int(stream['height'])
    rotation = float(stream.get('tags', {}).get('rotate', 0))
    for side in stream.get('side_data_list', []):
        rotation = float(side.get('rotation', rotation))
    if round(rotation) % 180:
        width, height = height, width
    duration = float(stream.get('duration', data.get('format', {}).get('duration', 0)))
    if duration <= 0:
        raise ValueError('Cannot establish source duration')
    return {'kind': 'video', 'width': width, 'height': height, 'duration': duration,
            'has_audio': any(s['codec_type'] == 'audio' for s in data['streams'])}


def check_font(path, text):
    font = ImageFont.truetype(str(path), 64)
    missing = font.getmask(chr(0x10FFFF))
    signature = (missing.size, bytes(missing))
    absent = []
    for ch in sorted(set(text)):
        if ch.isspace():
            continue
        glyph = font.getmask(ch)
        if not glyph.getbbox() or (glyph.size, bytes(glyph)) == signature:
            absent.append(ch)
    if absent:
        raise ValueError('Font lacks glyphs: ' + ''.join(absent))


class Reader:
    def __init__(self, path, spec, duration, fps, ffmpeg, ffprobe=None):
        self.info = media_info(path, ffprobe)
        if spec['kind'] != self.info['kind']:
            raise ValueError(f'Media kind mismatch: {path}')
        self.proc = None
        self.log = None
        self.image = None
        start = float(spec.get('start', 0))
        if start < 0:
            raise ValueError('Negative source start')
        if self.info['kind'] == 'image':
            with Image.open(path) as im:
                self.image = np.array(ImageOps.exif_transpose(im).convert('RGB'))
        else:
            if start + duration > self.info['duration'] + .0001:
                raise ValueError(f'Source too short: {path}; need {start + duration:.3f}s, have {self.info["duration"]:.3f}s')
            self.log = tempfile.TemporaryFile()
            w, h = self.info['width'], self.info['height']
            cmd = [ffmpeg, '-nostdin', '-v', 'error', '-ss', str(start), '-i', str(path), '-t', str(duration), '-vf', f'fps={fps},scale={w}:{h}', '-an', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=self.log)

    def next(self):
        if self.image is not None:
            return self.image
        size = self.info['width'] * self.info['height'] * 3
        chunks, count = [], 0
        while count < size:
            block = self.proc.stdout.read(size - count)
            if not block:
                self.log.seek(0)
                raise RuntimeError('Video/matte ended before the requested range: ' + self.log.read().decode('utf-8', 'replace'))
            chunks.append(block)
            count += len(block)
        return np.frombuffer(b''.join(chunks), np.uint8).reshape(self.info['height'], self.info['width'], 3)

    def close(self):
        if self.proc:
            self.proc.stdout.close()
            if self.proc.poll() is None:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill(); self.proc.wait()
        if self.log:
            self.log.close()


class Compositor:
    def __init__(self, cfg, root):
        self.cfg, self.root = cfg, Path(root)
        self.w, self.h = int(cfg['width']), int(cfg['height'])
        self.unit = self.h / 1080
        self.font = self.resolve(cfg['font'])
        check_font(self.font, ''.join(x['text'] for x in cfg['layers']))
        if not cfg['layers'] or any(float(x['vx']) <= 0 for x in cfg['layers']):
            raise ValueError('This effect requires nonempty layers with strictly positive vx')
        self.layers = [(x, self.sprite(x)) for x in cfg['layers']]
        # Keep an entire rotated sprite offscreen before recycling it.
        self.margin = max(.17 * self.w, max(im.shape[1] for _, im in self.layers) * .6 + 4)

    def resolve(self, value):
        p = Path(value)
        return p if p.is_absolute() else self.root / p

    def sprite(self, layer):
        size = max(12, round(layer['size'] * self.unit))
        font = ImageFont.truetype(str(self.font), size * 2)
        pad, step = max(12, round(38 * self.unit)), round(size * 1.1)
        w, h = size + pad * 2, step * (len(layer['text']) - 1) + size + pad * 2
        mask = Image.new('L', (w * 2, h * 2))
        draw = ImageDraw.Draw(mask)
        for i, ch in enumerate(layer['text']):
            box = font.getbbox(ch)
            x = (w * 2 - (box[2] - box[0])) / 2 - box[0]
            y = (pad + i * step + size / 2) * 2 - (box[3] - box[1]) / 2 - box[1]
            draw.text((x, y), ch, font=font, fill=255)
        mask = mask.resize((w, h), Image.Resampling.LANCZOS).rotate(layer.get('angle', 0), Image.Resampling.BICUBIC, expand=True)
        core = np.asarray(mask, np.float32) / 255
        near = np.asarray(mask.filter(ImageFilter.GaussianBlur(4 * self.unit)), np.float32) / 255
        if layer['kind'] == 'gold':
            far = np.asarray(mask.filter(ImageFilter.GaussianBlur(13 * self.unit)), np.float32) / 255
            alpha = np.clip(core * .98 + near * .65 + far * 1.15, 0, 1)
            mix = np.clip(core * 1.4, 0, 1)[..., None]
            rgb = np.array([255, 195, 62]) * (1 - mix) + np.array([255, 246, 177]) * mix
        else:
            if layer['kind'] == 'far':
                core = np.asarray(mask.filter(ImageFilter.GaussianBlur(1.05 * self.unit)), np.float32) / 255
            alpha = np.clip(core + near * .16, 0, 1) * (.56 if layer['kind'] == 'far' else .87)
            rgb = np.full((*alpha.shape, 3), [255, 252, 231], np.float32)
        return np.dstack((rgb * alpha[..., None], alpha)).astype(np.float32)

    def overlay(self, t):
        result = np.zeros((self.h, self.w, 4), np.float32)
        for layer, base in self.layers:
            phase = layer.get('phase', 0)
            scale = 1 + .02 * math.sin(t * .25 + phase)
            sw, sh = round(base.shape[1] * scale), round(base.shape[0] * scale)
            sprite = cv2.resize(base, (sw, sh))
            px = ((layer['x'] * self.w + layer['vx'] * self.unit * t + self.margin) % (self.w + 2 * self.margin)) - self.margin
            py = layer['y'] * self.h + math.sin(t * .65 + phase) * 5 * self.unit
            x, y = round(px - sw / 2), round(py)
            x1, y1, x2, y2 = max(0, x), max(0, y), min(self.w, x + sw), min(self.h, y + sh)
            if x2 <= x1 or y2 <= y1:
                continue
            crop = sprite[y1-y:y2-y, x1-x:x2-x]
            opacity = .91 + .09 * math.sin(t * .72 + phase)
            roi = result[y1:y2, x1:x2]
            alpha = crop[..., 3:4] * opacity
            roi[..., :3] = crop[..., :3] * opacity + roi[..., :3] * (1 - alpha)
            roi[..., 3:4] = alpha + roi[..., 3:4] * (1 - alpha)
        return result

    def composite(self, t, source, mask=None):
        bh, bw = source.shape[:2]
        cover = max(self.w / bw, self.h / bh)
        zoom = 1 + float(self.cfg.get('camera_zoom', .035)) * t / self.cfg['duration']
        scale = cover * zoom
        matrix = np.float32([[scale, 0, (self.w - bw * scale) / 2], [0, scale, (self.h - bh * scale) / 2]])
        clean = cv2.warpAffine(source, matrix, (self.w, self.h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101).astype(np.float32)
        layer = self.overlay(t)
        frame = layer[..., :3] + clean * (1 - layer[..., 3:4])
        if mask is not None:
            if mask.shape[:2] != source.shape[:2]:
                raise ValueError('Mask must match source dimensions before crop/zoom')
            matte = cv2.cvtColor(mask, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
            matte = cv2.warpAffine(matte, matrix, (self.w, self.h), flags=cv2.INTER_LINEAR)[..., None]
            frame = frame * (1 - matte) + clean * matte
        return np.clip(frame, 0, 255).astype(np.uint8)


def straight_rgba(layer):
    alpha = layer[..., 3:4]
    rgb = np.divide(layer[..., :3], alpha, out=np.zeros_like(layer[..., :3]), where=alpha > .00001)
    return np.clip(np.concatenate((rgb, alpha * 255), axis=2), 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--mode', choices=['composite', 'overlay'], default='composite')
    ap.add_argument('--still', type=float)
    ap.add_argument('--output', type=Path)
    ap.add_argument('--overwrite', action='store_true')
    ap.add_argument('--ffmpeg'); ap.add_argument('--ffprobe')
    args = ap.parse_args()
    root = args.project.resolve()
    cfg = json.loads((root / 'scene.json').read_text(encoding='utf-8-sig'))
    fps, duration = float(cfg['fps']), float(cfg['duration'])
    count = round(fps * duration)
    if fps <= 0 or duration <= 0 or count < 1 or abs(count / fps - duration) > .0001:
        raise ValueError('Use a positive duration equal to a whole number of frames')
    if any(int(cfg[k]) < 2 or int(cfg[k]) % 2 for k in ['width', 'height']):
        raise ValueError('Width and height must be positive even integers')
    if args.still is not None and not 0 <= args.still < duration:
        raise ValueError('--still must be within [0, duration)')
    comp = Compositor(cfg, root)
    ext = '.png' if args.still is not None else ('.mov' if args.mode == 'overlay' else '.mp4')
    name = f'{args.mode}-{args.still:.3f}' if args.still is not None else args.mode
    output = (args.output if args.output.is_absolute() else root / args.output) if args.output else root / 'output' / (name + ext)
    if output.exists() and not args.overwrite:
        raise FileExistsError(f'{output}; choose a new output or explicitly use --overwrite')
    protected = [comp.resolve(cfg['source']['path']), root/'scene.json', comp.font]
    if cfg.get('mask'):
        protected.append(comp.resolve(cfg['mask']['path']))
    if output.resolve() in [p.resolve() for p in protected]:
        raise ValueError('Output must not overwrite source or project configuration')
    if output.suffix.lower() != ext:
        raise ValueError(f'This mode requires {ext} output')
    ffmpeg = executable('ffmpeg', args.ffmpeg)
    readers, writer = [], None
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        if args.mode == 'composite':
            protect = cfg.get('protect_subject', True)
            if not protect and not cfg.get('allow_unprotected', False):
                raise ValueError('Unprotected output requires protect_subject=false AND allow_unprotected=true')
            if protect and not cfg.get('mask'):
                raise ValueError('Subject mask missing: prepare a mask or use overlay mode for the editor workflow')
            if protect and cfg['source']['kind'] == 'video' and cfg['mask']['kind'] != 'video':
                raise ValueError('A moving video requires a time-aligned video mask, not a static image mask')
            specs = [cfg['source']] + ([cfg['mask']] if protect else [])
            for spec in specs:
                readers.append(Reader(comp.resolve(spec['path']), spec, duration, fps, ffmpeg, args.ffprobe))
        still_index = min(count - 1, int(args.still * fps)) if args.still is not None else None
        render_times = [still_index / fps] if args.still is not None else [i / fps for i in range(count)]
        if args.still is not None and readers:
            # Sequential decode preserves source and matte timing, including VFR input.
            for _ in range(still_index):
                for reader in readers:
                    reader.next()
        if args.still is None:
            cmd = [ffmpeg, '-nostdin', '-y' if args.overwrite else '-n', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgba' if args.mode == 'overlay' else 'rgb24', '-s', f'{comp.w}x{comp.h}', '-r', str(fps), '-i', 'pipe:0']
            if args.mode == 'composite' and cfg.get('audio') == 'source' and cfg['source']['kind'] == 'video':
                cmd += ['-ss', str(cfg['source'].get('start', 0)), '-i', str(comp.resolve(cfg['source']['path'])), '-map', '0:v:0', '-map', '1:a:0?', '-c:a', 'aac', '-b:a', '192k']
            else:
                cmd += ['-an']
            cmd += ['-t', str(duration)]
            cmd += (['-c:v', 'prores_ks', '-profile:v', '4', '-pix_fmt', 'yuva444p10le', '-alpha_bits', '16'] if args.mode == 'overlay' else ['-c:v', 'libx264', '-crf', '18', '-preset', 'fast', '-pix_fmt', 'yuv420p', '-movflags', '+faststart'])
            log = open(output.with_suffix(output.suffix + '.log'), 'wb')
            partial = output.with_name(output.stem + '.partial-' + uuid.uuid4().hex[:8] + output.suffix)
            writer = subprocess.Popen(cmd + [str(partial)], stdin=subprocess.PIPE, stderr=log)
        for i, t in enumerate(render_times):
            if args.mode == 'overlay':
                frame = straight_rgba(comp.overlay(t))
            else:
                source = readers[0].next()
                mask = readers[1].next() if len(readers) > 1 else None
                frame = comp.composite(t, source, mask)
            if args.still is not None:
                Image.fromarray(frame).save(output)
            else:
                if writer.poll() is not None:
                    raise RuntimeError('FFmpeg stopped early; inspect the output .log file')
                writer.stdin.write(frame.tobytes())
                if (i + 1) % max(1, round(fps)) == 0:
                    print(f'{i+1}/{count} frames', flush=True)
        if writer:
            writer.stdin.close()
            if writer.wait(timeout=120):
                raise RuntimeError('FFmpeg failed; inspect the output .log file')
            if output.exists() and not args.overwrite:
                raise FileExistsError('Output appeared during rendering; the completed partial file was preserved')
            partial.replace(output)
        print(output, flush=True)
    finally:
        for reader in readers:
            reader.close()
        if writer:
            if writer.poll() is None:
                writer.kill(); writer.wait()
            log.close()


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    main()
