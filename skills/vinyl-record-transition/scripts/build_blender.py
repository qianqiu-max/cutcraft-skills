"""Build an editable Blender VSE vinyl transition from a prepared recipe.

Run in a new background Blender process, not the user's active desktop session:
  blender --background --factory-startup --python build_blender.py -- \
    --recipe /project/recipe.json --output /project/editable.blend \
    --render /project/result.mp4
"""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy


def fail(message):
    raise ValueError(message)


def collection(editor):
    # Blender 4.5 exposes both names; 5.2 removes `sequences`.
    return editor.strips if hasattr(editor, 'strips') else editor.sequences


def linear_curves(action):
    """Support both legacy and layered Actions (Blender 4.5/5.2)."""
    curves = []
    if hasattr(action, 'fcurves'):
        curves.extend(action.fcurves)
    for layer in getattr(action, 'layers', []):
        for action_strip in layer.strips:
            for bag in getattr(action_strip, 'channelbags', []):
                curves.extend(bag.fcurves)
    for curve in curves:
        for key in curve.keyframe_points:
            key.interpolation = 'LINEAR'


def main():
    args_list = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', required=True)
    parser.add_argument('--output', required=True, help='New native .blend project')
    parser.add_argument('--render', help='Optional new .mp4 output, rendered by Blender')
    args = parser.parse_args(args_list)
    recipe_path = Path(args.recipe).resolve()
    root = recipe_path.parent
    output = Path(args.output).resolve()
    rendered = Path(args.render).resolve() if args.render else None
    if output.suffix.lower() != '.blend':
        fail('--output must end in .blend')
    if rendered and rendered.suffix.lower() != '.mp4':
        fail('--render must end in .mp4')
    for path in [output, rendered]:
        if path and path.exists():
            fail(f'Refusing to overwrite existing file: {path}. Use a new versioned path.')
    cfg = json.loads(recipe_path.read_text(encoding='utf-8-sig'))
    w, h, fps = int(cfg['width']), int(cfg['height']), int(cfg['fps'])
    seconds = float(cfg['duration'])
    n = round(seconds * fps)
    if min(w, h, fps, n) <= 0 or w % 2 or h % 2:
        fail('width/height must be positive even integers; fps and duration must be positive')
    tr = cfg['transition']
    start, end, switch = (float(tr[k]) for k in ['start', 'end', 'switch'])
    if not 0 <= start < switch < end <= seconds:
        fail('Expected 0 <= transition.start < switch < end <= duration')
    rotation_seconds = float(cfg['rotation_seconds'])
    if rotation_seconds <= 0:
        fail('rotation_seconds must be positive')
    start_frame, switch_frame = round(start * fps) + 1, round(switch * fps) + 1
    end_frame = round(end * fps) + 1
    files = cfg['files']

    def asset(value):
        path = (root / value).resolve()
        if not path.is_file():
            fail(f'Missing prepared asset: {path}')
        try:
            path.relative_to(root)
        except ValueError:
            fail(f'Prepared assets must be inside the project bundle: {path}')
        return path

    media = {name: asset(files[name]) for name in ['background', 'panel', 'vinyl', 'photo', 'decor']}
    clouds = [asset(name) for name in files['cloud_frames']]
    if len(clouds) != end_frame - start_frame:
        fail('cloud_frames count must equal the transition duration in frames')
    if len({p.parent for p in clouds}) != 1:
        fail('Cloud PNG frames must share one directory')
    audio = asset(files['audio']) if files.get('audio') else None
    scene = bpy.context.scene
    if scene.sequence_editor and len(collection(scene.sequence_editor)):
        fail('Expected a fresh scene. Start Blender with --background --factory-startup.')
    editor = scene.sequence_editor_create()
    strips = collection(editor)
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.render.resolution_percentage = 100
    scene.render.fps, scene.render.fps_base = fps, 1.0
    scene.frame_start, scene.frame_end = 1, n
    scene.render.use_sequencer = True
    scene.render.use_compositing = False
    scene.sequencer_colorspace_settings.name = 'sRGB'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1

    # Both movie strips start at source frame 0. Trimming the second by a handle
    # retains the original time, so the footage does not restart at the switch.
    before = strips.new_movie(name='01 · Full-screen footage', filepath=str(media['background']), channel=1, frame_start=1, fit_method='ORIGINAL')
    if before.frame_final_duration < n:
        fail(f'Prepared background is too short: {before.frame_final_duration} frames; need {n}')
    before.frame_final_end = switch_frame
    after = strips.new_movie(name='02 · Continuing footage / shifted right', filepath=str(media['background']), channel=1, frame_start=1, fit_method='ORIGINAL')
    after.frame_final_start = switch_frame
    after.frame_final_end = n + 1
    after.transform.offset_x = float(cfg['background_shift_x'])

    def image_strip(name, path, channel, at=switch_frame, final=n+1):
        strip = strips.new_image(name=name, filepath=str(path), channel=channel, frame_start=at, fit_method='ORIGINAL')
        strip.frame_final_end = final
        strip.blend_type = 'ALPHA_OVER'
        strip.blend_alpha = 1
        # The PNGs produced by the preparer contain straight (unassociated) alpha.
        if hasattr(strip, 'alpha_mode'):
            strip.alpha_mode = 'STRAIGHT'
        return strip

    image_strip('03 · Feathered white panel + gray band', media['panel'], 2)
    cx, cy = (float(x) for x in cfg['disc_center'])
    record = image_strip('04 · Vinyl / editable rotation', media['vinyl'], 3)
    photo = image_strip('05 · Circular cover / editable rotation', media['photo'], 4)
    for strip, size in [(record, float(cfg['disc_size'])), (photo, float(cfg['photo_size']))]:
        elem = strip.elements[0]
        strip.transform.scale_x = size / elem.orig_width
        strip.transform.scale_y = size / elem.orig_height
        strip.transform.offset_x, strip.transform.offset_y = cx - w/2, h/2 - cy
        strip.transform.rotation = 0
        strip.transform.keyframe_insert(data_path='rotation', frame=switch_frame)
        strip.transform.rotation = -2 * math.pi * ((n + 1 - switch_frame) / fps) / rotation_seconds
        strip.transform.keyframe_insert(data_path='rotation', frame=n+1)
    image_strip('06 · Title + player decoration', media['decor'], 5)
    cloud = image_strip('07 · Cloud transition / PNG sequence', clouds[0], 6, at=start_frame, final=start_frame+1)
    for path in clouds[1:]:
        cloud.elements.append(path.name)
    cloud.frame_final_end = end_frame
    if audio:
        sound = strips.new_sound(name='08 · Audio', filepath=str(audio), channel=7, frame_start=1)
        sound.frame_final_end = min(sound.frame_final_end, n+1)
        sound.volume = 1
    if scene.animation_data and scene.animation_data.action:
        linear_curves(scene.animation_data.action)

    for name, frame in [('Cloud in', start_frame), ('Hidden layout switch', switch_frame), ('Cloud out', end_frame)]:
        scene.timeline_markers.new(name, frame=frame)
    scene['vinyl_recipe'] = json.dumps(cfg, ensure_ascii=False)
    scene['vinyl_build_info'] = json.dumps({'blender': bpy.app.version_string, 'native_vse': True, 'audio': bool(audio), 'frame_count': n}, ensure_ascii=False)
    scene.frame_set(min(n, end_frame+fps))
    for screen in bpy.data.screens:
        if screen.name == 'Layout':
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.type = 'SEQUENCE_EDITOR'
                    area.spaces.active.view_type = 'SEQUENCER_PREVIEW'
    if hasattr(scene.render.image_settings, 'media_type'):
        scene.render.image_settings.media_type = 'VIDEO'
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.ffmpeg.constant_rate_factor = 'HIGH'
    scene.render.ffmpeg.ffmpeg_preset = 'GOOD'
    scene.render.ffmpeg.audio_codec = 'AAC' if audio else 'NONE'
    scene.render.ffmpeg.audio_bitrate = 192
    scene.render.ffmpeg.audio_mixrate = 48000
    scene.render.filepath = str(rendered or output.with_suffix('.mp4'))
    scene.render.use_file_extension = True
    output.parent.mkdir(parents=True, exist_ok=True)
    if rendered:
        rendered.parent.mkdir(parents=True, exist_ok=True)
    # Save once to establish Blender's relative-path base, remap, save again.
    # This is an isolated process; the preference is not persisted to user config.
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    bpy.ops.file.make_paths_relative()
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    print('NATIVE_PROJECT', str(output), flush=True)
    print('LAYERS', [(s.name, s.channel, s.frame_final_start, s.frame_final_end) for s in strips], flush=True)
    if rendered:
        bpy.ops.render.render(animation=True)
        if not rendered.is_file() or rendered.stat().st_size == 0:
            fail(f'Blender did not create the expected video: {rendered}')
        print('RENDERED', str(rendered), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        # Blender without --python-exit-code otherwise exits 0 on Python failures.
        sys.exit(1)
