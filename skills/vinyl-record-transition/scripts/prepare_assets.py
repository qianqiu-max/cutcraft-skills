"""Prepare portable media/layers for editing software; never renders the final effect.

Requires Python 3.10+, Pillow, numpy, FFmpeg and ffprobe on PATH.
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def run(args):
    subprocess.run([str(v) for v in args], check=True)


def probe(path):
    p = subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,check=True,text=True,encoding='utf-8')
    return json.loads(p.stdout)


def smooth(v):
    v=np.clip(v,0,1)
    return v*v*(3-2*v)


def get_font(arg, text):
    windows_fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    candidates = [arg] if arg else []
    if any(ord(c)>127 for c in text):
        candidates += [windows_fonts / 'msyh.ttc','/System/Library/Fonts/PingFang.ttc','/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    else:
        candidates += ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',windows_fonts / 'arial.ttf','/System/Library/Fonts/Supplemental/Arial.ttf']
    for c in candidates:
        if c and Path(c).is_file(): return str(Path(c).resolve())
    if any(ord(c)>127 for c in text):
        raise ValueError('Non-ASCII labels need a compatible --font TTF/OTF/TTC path')
    return None


def vinyl(size):
    s=size*2; y,x=np.mgrid[:s,:s].astype(float); mid=(s-1)/2
    r=np.hypot(x-mid,y-mid)/mid; a=np.arctan2(y-mid,x-mid)
    shine=(np.cos(a*2-.75)*.5+.5)**11
    v=10+11*(1-r)+52*shine+(np.cos(r*690)*.5+.5)*5
    rgb=np.stack([v*.91,v*.96,v],axis=-1).clip(0,255).astype('uint8')
    alpha=(np.clip((1-r)*mid,0,1)*255).astype('uint8')
    im=Image.fromarray(np.dstack([rgb,alpha]))
    d=ImageDraw.Draw(im)
    for rad in [mid-3,mid-10,mid*.63]:
        d.ellipse((mid-rad,mid-rad,mid+rad,mid+rad),outline=(130,142,145,130),width=2)
    return im.resize((size,size),Image.Resampling.LANCZOS)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,help='Local video or static image')
    p.add_argument('--out',required=True,help='New empty project directory')
    p.add_argument('--photo',help='Optional local image for the centre label')
    p.add_argument('--music',help='Optional local audio file to use instead of source audio')
    p.add_argument('--keep-source-audio',action='store_true')
    p.add_argument('--duration',type=float,help='Defaults to min(14, video duration), at least 6 seconds; short sources loop')
    p.add_argument('--start',type=float,default=0)
    p.add_argument('--width',type=int,default=1280)
    p.add_argument('--height',type=int,default=720)
    p.add_argument('--fps',type=int,default=30)
    p.add_argument('--fit',choices=['contain','cover'],default='contain')
    p.add_argument('--rotation-seconds',type=float,help='Seconds per full turn; default min(8, player section duration)')
    p.add_argument('--transition-start',type=float)
    p.add_argument('--transition-duration',type=float,default=1)
    p.add_argument('--title',default='SLOW DAYS')
    p.add_argument('--subtitle',default='A MOMENT ON REPEAT')
    p.add_argument('--font',help='Compatible font path; never redistributed automatically')
    args=p.parse_args()
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'): p.error('FFmpeg and ffprobe must be on PATH')
    source=Path(args.source).expanduser().resolve()
    if not source.is_file():p.error('Source file does not exist')
    out=Path(args.out).expanduser().resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):p.error('Output must be new or empty; existing work is never overwritten')
    w,h,fps=args.width,args.height,args.fps
    if min(w,h)<160 or w%2 or h%2 or w/h<1.4 or w/h>2.4:p.error('Bundled layout needs even landscape dimensions, aspect 1.4–2.4; use the editor guide for other layouts')
    if not 1<=fps<=60 or args.start<0 or (args.rotation_seconds is not None and args.rotation_seconds<=0):p.error('Invalid fps, source start, or rotation period')
    info=probe(source); video=next((s for s in info['streams'] if s['codec_type']=='video'),None)
    if not video:p.error('Source has no image/video stream')
    is_image=source.suffix.lower() in {'.jpg','.jpeg','.png','.webp','.bmp','.tif','.tiff'}
    length=0 if is_image else float(info.get('format',{}).get('duration',video.get('duration',0)))
    if not is_image and (length<=0 or args.start>=length):p.error('Source duration/start is not usable')
    duration=args.duration if args.duration is not None else (14 if is_image else max(6,min(14,length-args.start)))
    if not math.isfinite(duration) or not 2<=duration<=300:p.error('Duration must be 2–300 seconds')
    duration=round(duration*fps)/fps
    start=args.transition_start if args.transition_start is not None else min(2.2,duration*.2)
    start=round(start*fps)/fps
    ncloud=round(args.transition_duration*fps)
    if ncloud<4 or start<0 or start+ncloud/fps>=duration:p.error('Transition must fit inside the duration and contain at least four frames')
    switch=start+(ncloud//2)/fps
    rotation_seconds=args.rotation_seconds if args.rotation_seconds is not None else min(8,duration-switch)
    if args.music and args.keep_source_audio:p.error('Choose either music or source audio, not both')
    for attr in ['photo','music','font']:
        val=getattr(args,attr)
        if val and not Path(val).expanduser().is_file():p.error(f'{attr} file does not exist')
    fp=get_font(args.font,args.title+args.subtitle)
    out.mkdir(parents=True,exist_ok=True); assets=out/'assets';assets.mkdir();cloud=assets/'cloud';cloud.mkdir()
    notes=[]
    if is_image:notes.append('Background is a static image, not live-action video.')
    elif duration>length-args.start:notes.append('Source is shorter than requested; background is looped.')
    mode='increase' if args.fit=='cover' else 'decrease'
    base=f'scale={w}:{h}:force_original_aspect_ratio={mode}'
    fit=f'{base},crop={w}:{h}' if args.fit=='cover' else f'{base},pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=white'
    common=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-n']
    inputs=['-loop','1'] if is_image else ['-stream_loop','-1','-ss',args.start]
    run(common+inputs+['-i',source,'-map','0:v:0','-an','-t',duration,'-vf',fit+f',setsar=1,fps={fps}','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',assets/'background.mp4'])
    # Decode after normalising orientation, aspect ratio and source timing.
    snapshot=assets/'source-still.png'
    run(common+['-ss',min(duration*.25,duration-1/fps),'-i',assets/'background.mp4','-frames:v','1',snapshot])
    cx,cy=round(w*.201),round(h*.5125)
    ds=round(min(w*.258,h*.48));ps=round(ds*.636)
    vinyl(ds).save(assets/'vinyl.png')
    image_path=Path(args.photo).expanduser().resolve() if args.photo else snapshot
    from PIL import ImageOps
    im=ImageOps.exif_transpose(Image.open(image_path)).convert('RGB')
    side=min(im.size);x=(im.width-side)//2;y=(im.height-side)//2
    im=im.crop((x,y,x+side,y+side)).resize((ps,ps),Image.Resampling.LANCZOS)
    mask=Image.new('L',(ps*2,ps*2));ImageDraw.Draw(mask).ellipse((1,1,ps*2-1,ps*2-1),fill=255)
    im.putalpha(mask.resize((ps,ps),Image.Resampling.LANCZOS));im.save(assets/'photo.png')
    xx=np.arange(w); alpha=((1-smooth((xx-w*.305)/(w*.266)))*255).astype('uint8')
    rgba=np.ones((h,w,4),dtype='uint8')*255;rgba[:,:,3]=alpha[None,:]
    panel=Image.fromarray(rgba)
    band=Image.new('RGBA',(w,h));ImageDraw.Draw(band).rectangle((0,round(cy-h*.128),round(cx+ds*.60),round(cy+h*.107)),fill=(139,145,145,160))
    panel=Image.alpha_composite(panel,band);panel.save(assets/'panel.png')
    decor=Image.new('RGBA',(w,h));d=ImageDraw.Draw(decor)
    scale=min(w/1280,h/720)
    def label(x,y,value,size):
        size=round(size*scale);maxwidth=round(w*.36)
        face=ImageFont.truetype(fp,size) if fp else ImageFont.load_default(size=size)
        while d.textbbox((0,0),value,font=face)[2]>maxwidth and size>10:
            size-=1;face=ImageFont.truetype(fp,size) if fp else ImageFont.load_default(size=size)
        d.text((round(x*w),round(y*h)),value,font=face,fill='#23383b')
    label(.05,.075,args.title,44);label(.055,.17,args.subtitle,14)
    label(.058,.78,'NOW PLAYING',15)
    y=round(h*.854);left=round(w*.059);right=round(w*.347)
    d.line((left,y,right,y),fill='#627d7d',width=max(1,round(2*scale)))
    d.ellipse((left-3,y-3,left+3,y+3),fill='#23383b')
    y=round(h*.923);r=round(21*scale)
    d.ellipse((cx-r,y-r,cx+r,y+r),outline='#819392',width=max(1,round(scale)))
    for x in [cx-6*scale,cx+3*scale]:d.rectangle((x,y-7*scale,x+3*scale,y+8*scale),fill='#23383b')
    for x,sgn in [(cx-53*scale,-1),(cx+53*scale,1)]:
        d.polygon([(x+sgn*7*scale,y),(x-sgn*5*scale,y-7*scale),(x-sgn*5*scale,y+7*scale)],fill='#354b4d')
    decor.save(assets/'decor.png')
    # Cloud fully covers the canvas on both sides of the exact cut frame.
    yy,xx=np.mgrid[:h,:w].astype('float32')
    coord=xx+w*.03*np.sin(yy/(h*.10))+w*.02*np.sin(yy/(h*.04)+.7)
    cloud_files=[]
    for i in range(ncloud):
        p=i/(ncloud-1)
        if .44<=p<=.56:a=np.ones((h,w),dtype='float32')
        elif p<.44:
            edge=(-.12+1.28*smooth(p/.44))*w
            a=smooth((edge-coord)/(w*.018))
        else:
            edge=(-.12+1.28*smooth((p-.56)/.44))*w
            a=1-smooth((edge-coord)/(w*.018))
        rgba=np.ones((h,w,4),dtype='uint8')*255;rgba[:,:,3]=(a*255).astype('uint8')
        name=f'cloud_{i:04d}.png';Image.fromarray(rgba).save(cloud/name);cloud_files.append(f'assets/cloud/{name}')
    audio=None
    if args.music:
        music=Path(args.music).expanduser().resolve()
        run(common+['-stream_loop','-1','-i',music,'-vn','-t',duration,'-af',f'afade=t=out:st={max(0,duration-.3)}:d=0.3','-ar','48000','-ac','2',assets/'audio.wav'])
        audio='assets/audio.wav'
    elif args.keep_source_audio:
        if is_image or not any(s['codec_type']=='audio' for s in info['streams']):
            notes.append('Requested source audio is absent; project has no audio.')
        else:
            run(common+['-stream_loop','-1','-ss',args.start,'-i',source,'-map','0:a:0','-vn','-t',duration,'-ar','48000','-ac','2',assets/'audio.wav']);audio='assets/audio.wav'
    if audio is None:notes.append('No audio selected: output is intentionally silent. Do not report it as an audio failure or add unlicensed music.')
    files={'background':'assets/background.mp4','panel':'assets/panel.png','vinyl':'assets/vinyl.png','photo':'assets/photo.png','decor':'assets/decor.png','cloud_frames':cloud_files,'audio':audio}
    recipe={'version':1,'width':w,'height':h,'fps':fps,'duration':duration,'transition':{'start':start,'end':start+ncloud/fps,'switch':switch},'rotation_seconds':rotation_seconds,'background_shift_x':round(w*.14),'disc_center':[cx,cy],'disc_size':ds,'photo_size':ps,'files':files,'notes':notes,'labels':{'title':args.title,'subtitle':args.subtitle}}
    (out/'recipe.json').write_text(json.dumps(recipe,ensure_ascii=False,indent=2),encoding='utf-8')
    # Source paths describe provenance but are never read by the Blender adapter.
    sources=[]
    for role,path in [('source',source),('photo',Path(args.photo).expanduser().resolve() if args.photo else None),('music',Path(args.music).expanduser().resolve() if args.music else None)]:
        if path:
            with path.open('rb') as stream:
                digest=hashlib.file_digest(stream,'sha256').hexdigest() if hasattr(hashlib,'file_digest') else hashlib.sha256(stream.read()).hexdigest()
            sources.append({'role':role,'source_filename':path.name,'sha256':digest,'rights':'user-supplied or local source; authorization must be assessed by the agent'})
    (out/'sources.json').write_text(json.dumps({'sources':sources,'fit':args.fit,'font_used':Path(fp).name if fp else None,'notes':notes},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'recipe':str(out/'recipe.json'),'notes':notes},ensure_ascii=False))


if __name__=='__main__':main()
