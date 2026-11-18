"""Create an independent project; never overwrite an existing scene.json."""
import argparse, json, os, shutil, sys
from pathlib import Path
from render import media_info, check_font


def find_font():
    windows_fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    candidates = [windows_fonts / 'STXINGKA.TTF', windows_fonts / 'simkai.ttf',
                  '/System/Library/Fonts/PingFang.ttc', '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
                  '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    return next((Path(p) for p in candidates if Path(p).is_file()), None)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--text-file', type=Path, required=True)
    ap.add_argument('--font', type=Path)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--mask', type=Path)
    ap.add_argument('--source-start', type=float, default=0)
    ap.add_argument('--mask-start', type=float)
    ap.add_argument('--width', type=int); ap.add_argument('--height', type=int)
    ap.add_argument('--fps', type=float, default=30)
    ap.add_argument('--duration', type=float)
    ap.add_argument('--ffprobe')
    args = ap.parse_args()
    if args.project.exists() and any(args.project.iterdir()):
        raise FileExistsError('Choose a new/empty project directory; existing files are preserved')
    info = media_info(args.source, args.ffprobe)
    texts = [line.strip() for line in args.text_file.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    if not texts or any(len(line) > 32 for line in texts):
        raise ValueError('Provide 1 or more lines of text, each 1–32 characters; split long prose into short columns')
    font = args.font or find_font()
    if font is None:
        raise ValueError('No suitable font found; pass --font with a font that covers the supplied text')
    font = font.resolve()
    check_font(font, ''.join(texts))
    if args.fps <= 0 or args.source_start < 0:
        raise ValueError('fps must be positive and source-start nonnegative')
    available = info['duration'] - args.source_start if info['kind'] == 'video' else 10
    requested = args.duration if args.duration is not None else min(10, available)
    duration = int(requested * args.fps + .000001) / args.fps
    if duration <= 0 or (info['kind'] == 'video' and duration > available + .0001):
        raise ValueError('Requested duration is invalid or exceeds the source')
    ratio = info['width'] / info['height']
    width = args.width or round((args.height or min(1080, 1920 / ratio)) * ratio)
    height = args.height or round(width / ratio)
    width, height = width // 2 * 2, height // 2 * 2
    if min(width, height) < 2:
        raise ValueError('Invalid dimensions')
    mask_info = media_info(args.mask, args.ffprobe) if args.mask else None
    if mask_info and (mask_info['width'], mask_info['height']) != (info['width'], info['height']):
        raise ValueError('Source and mask dimensions differ')
    if mask_info and info['kind'] == 'video' and mask_info['kind'] != 'video':
        raise ValueError('Video input needs a time-aligned video mask')
    root = args.project.resolve()
    (root / 'assets').mkdir(parents=True, exist_ok=True)
    (root / 'output').mkdir()
    source = Path('assets') / ('source' + args.source.suffix.lower())
    shutil.copy2(args.source, root / source)
    (root / 'text.txt').write_text('\n'.join(texts) + '\n', encoding='utf-8')
    mask = None
    if args.mask:
        dest = Path('assets') / ('mask' + args.mask.suffix.lower())
        shutil.copy2(args.mask, root / dest)
        mask = {'path': dest.as_posix(), 'kind': mask_info['kind'], 'start': args.mask_start if args.mask_start is not None else args.source_start}
    layers = []
    for kind, count, speed, size in [('far', 9, 85, 42), ('white', 7, 165, 60), ('gold', 5, 275, 100)]:
        for i in range(count):
            layers.append({'text': texts[i % len(texts)], 'kind': kind, 'x': -.13 + i * 1.34 / count,
                           'y': [-.12, .20, .05, .37, .0, .54, .16, .65, .28][i], 'size': size,
                           'vx': speed, 'phase': i * .83, 'angle': [-2, 2, -1, 3, 0][i % 5]})
    cfg = {'version': 1, 'width': width, 'height': height, 'fps': args.fps, 'duration': duration,
           'source': {'path': source.as_posix(), 'kind': info['kind'], 'start': args.source_start},
           'mask': mask, 'font': str(font), 'protect_subject': True, 'allow_unprotected': False,
           'audio': 'source' if info.get('has_audio') else 'none', 'camera_zoom': .035, 'layers': layers}
    (root / 'scene.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    print(root / 'scene.json')
    print('Inspect a rendered glyph preview. Font licenses are not verified or redistributed.')
    if mask is None:
        print('Subject protection is enabled. Supply a matching mask in scene.json before composite export, or render --mode overlay for your editor.')


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    main()
