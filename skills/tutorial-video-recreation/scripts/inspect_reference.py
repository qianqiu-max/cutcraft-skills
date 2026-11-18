"""Prepare local tutorial evidence; this helper does not watch, hear or understand it.

Python 3.10+, Pillow, FFmpeg and ffprobe are required. Never overwrites a
nonempty output directory. All media operations use argument lists, not a shell.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw


def command(args):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'{Path(str(args[0])).name} failed ({result.returncode}):\n{result.stderr[-4000:]}')
    return result.stdout


def positive(value):
    number=float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be a finite positive number')
    return number


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tutorial',required=True,help='Local video tutorial')
    p.add_argument('--out',required=True,help='New or empty analysis directory')
    p.add_argument('--step',type=positive,default=3,help='Whole-duration sampling interval, seconds (default: 3)')
    p.add_argument('--window',nargs=3,type=float,action='append',default=[],metavar=('START','END','STEP'),help='Additional dense sampling; may repeat')
    p.add_argument('--max-frames',type=int,default=240,help='Fail rather than silently truncate above this count')
    p.add_argument('--audio',action='store_true',help='Extract 16 kHz mono WAV when the source has audio')
    args=p.parse_args()
    for exe in ['ffmpeg','ffprobe']:
        if not shutil.which(exe):p.error(f'{exe} is not available on PATH')
    source=Path(args.tutorial).expanduser().resolve()
    if not source.is_file():p.error('Tutorial file does not exist')
    out=Path(args.out).expanduser().resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        p.error('Output must be new or empty; preserve previous evidence in a different directory')
    meta=json.loads(command(['ffprobe','-v','error','-show_format','-show_streams','-of','json',source]))
    video=next((s for s in meta.get('streams',[]) if s.get('codec_type')=='video'),None)
    if video is None:p.error('Tutorial contains no video stream')
    container_duration=float(meta.get('format',{}).get('duration',0))
    # Audio may extend beyond the last video frame; do not seek from container end.
    duration=float(video.get('duration') or container_duration)
    if not math.isfinite(duration) or duration<=0:p.error('Could not determine a positive video duration')
    try:fps=float(Fraction(video.get('avg_frame_rate') or video.get('r_frame_rate') or '30'))
    except (ValueError,ZeroDivisionError):fps=30
    if fps<=0:fps=30
    last=max(0,duration-max(1/fps+.001,.10))
    points={0.,round(last,6)}
    def add_range(start,end,step):
        count=math.floor((end-start)/step)+1
        if count>args.max_frames:p.error('Sampling exceeds --max-frames; increase --step or narrow the windows')
        for i in range(count):points.add(round(min(last,start+i*step),6))
    if args.max_frames<2:p.error('--max-frames must be at least 2')
    add_range(0,last,args.step)
    for start,end,step in args.window:
        if not all(math.isfinite(v) for v in [start,end,step]) or start<0 or end<start or end>duration or step<=0:
            p.error('Each window must have 0 <= START <= END <= duration and STEP > 0')
        add_range(min(start,last),min(end,last),step)
    times=sorted(points)
    if len(times)>args.max_frames:p.error('Combined samples exceed --max-frames; no evidence was silently dropped')
    out.mkdir(parents=True,exist_ok=True); frames=out/'frames';frames.mkdir()
    records=[{'id':i,'requested_seconds':t,'file':f'frames/frame_{i:04d}.png','review_state':'not_reviewed'} for i,t in enumerate(times)]
    def extract(record):
        target=out/record['file']
        command(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-n',
                 '-ss',f'{record["requested_seconds"]:.6f}','-i',source,'-map','0:v:0',
                 '-frames:v','1','-c:v','png','-pix_fmt','rgb24','-threads','1',target])
        if not target.is_file() or not target.stat().st_size:raise RuntimeError(f'No frame at {record["requested_seconds"]}')
        return target
    with ThreadPoolExecutor(max_workers=min(4,len(records))) as pool:
        list(pool.map(extract,records))
    sheets=[]
    cellw,cellh=400,300
    for page in range((len(records)+11)//12):
        group=records[page*12:(page+1)*12]
        rows=(len(group)+2)//3
        sheet=Image.new('RGB',(3*cellw,rows*cellh),'#152427');draw=ImageDraw.Draw(sheet)
        for i,record in enumerate(group):
            x,y=(i%3)*cellw,(i//3)*cellh
            with Image.open(out/record['file']) as frame:
                frame=frame.convert('RGB');frame.thumbnail((cellw-12,cellh-32),Image.Resampling.LANCZOS)
                sheet.paste(frame,(x+(cellw-frame.width)//2,y+28+(cellh-32-frame.height)//2))
            draw.text((x+8,y+7),f'#{record["id"]:03d}  {record["requested_seconds"]:.3f} s',fill='white')
        name=f'contact_{page+1:02d}.jpg';sheet.save(out/name,quality=92);sheets.append(name)
    has_audio=any(s.get('codec_type')=='audio' for s in meta.get('streams',[]))
    audio=None
    if args.audio and has_audio:
        audio='tutorial-audio.wav'
        command(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-n','-i',source,
                 '-map','0:a:0','-vn','-ar','16000','-ac','1',out/audio])
    with source.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest() if hasattr(hashlib,'file_digest') else hashlib.sha256(stream.read()).hexdigest()
    report={'tutorial':str(source),'sha256':digest,'duration_seconds':duration,'container_duration_seconds':container_duration,
            'width':video.get('width'),'height':video.get('height'),'fps':fps,'has_audio':has_audio,
            'sampling':{'whole_duration_step_seconds':args.step,'extra_windows':args.window,'frames_generated':len(records)},
            'contact_sheets':sheets,'frames':records,'audio_file':audio,
            'review_state':'not_reviewed','sampling_is_not_full_playback':True,
            'note':'Time labels are requested seek times; actual decoded frames follow the source time base. Generated evidence is not a claim of full viewing, listening, transcript accuracy, or tutorial comprehension.'}
    (out/'inspection.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'ffprobe.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Tutorial review coverage','',
           'Generated frames only. No viewing, listening or understanding has been recorded yet.',
           'Open full-size frame files when screen text is unreadable in a contact sheet.',
           'Record actual reviewed ranges, dense follow-ups, transcript corrections and uncertainties separately.',
           '', '| ID | Requested seconds | Full-size frame | Review state |', '|---|---:|---|---|']
    for r in records:lines.append(f'| {r["id"]} | {r["requested_seconds"]:.3f} | [{Path(r["file"]).name}]({r["file"]}) | not_reviewed |')
    (out/'review-coverage.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'inspection':str(out/'inspection.json'),'frames':len(records),'sheets':len(sheets),'audio_extracted':bool(audio),'review_state':'not_reviewed'},ensure_ascii=False))


if __name__=='__main__':main()
