#!/usr/bin/env python3
"""Temporary Linux fbdev test, on a dedicated VT; ESC returns to previous VT."""
import os, mmap, fcntl, struct, select, time, signal, subprocess
from pathlib import Path
FONT={}
for chars,rows in [
('0123456789',['01110100011001110101110011000101110','00100011000010000100001000010001110','01110100010000100010001000100011111','11110000010000101110000010000111110','00010001100101010010111110001000010','11111100001000011110000010000111110','01110100001000011110100011000101110','11111000010001000100010000100001000','01110100011000101110100011000101110','01110100011000101111000010000101110']),
('ABCDEFGHIJKLMNOPQRSTUVWXYZ',['01110100011000111111100011000110001','11110100011000111110100011000111110','01111100001000010000100001000001111','11110100011000110001100011000111110','11111100001000011110100001000011111','11111100001000011110100001000010000','01111100001000010111100011000101111','10001100011000111111100011000110001','11111001000010000100001000010011111','00111000100001000010100101001001100','10001100101010011000101001001010001','10000100001000010000100001000011111','10001110111010110101100011000110001','10001110011010110011100011000110001','01110100011000110001100011000101110','11110100011000111110100001000010000','01110100011000110001101011001001101','11110100011000111110101001001010001','01111100001000001110000010000111110','11111001000010000100001000010000100','10001100011000110001100011000101110','10001100011000110001100010101000100','10001100011000110101101011101110001','10001100010101000100010101000110001','10001100010101000100001000010000100','11111000010001000100010001000011111'])]:
 FONT.update(zip(chars,rows))
FONT['-']='00000000000000011111000000000000000'
import threading, json, statistics
W,H=map(int,Path('/sys/class/graphics/fb0/virtual_size').read_text().split(','))
stride=int(Path('/sys/class/graphics/fb0/stride').read_text())
assert int(Path('/sys/class/graphics/fb0/bits_per_pixel').read_text())==32
buf=bytearray(stride*H);dirty=[]
def rect(x,y,w,h,c):
 x,y=int(x),int(y);r,b=min(W,x+w),min(H,y+h);x,y=max(0,x),max(0,y)
 if r<=x or b<=y:return
 dirty.append((x,y,r,b));row=struct.pack('<I',c)*(r-x)
 for yy in range(y,b):buf[yy*stride+x*4:yy*stride+r*4]=row
def text(x,y,s,scale=4,c=0xe5edf9):
 for ch in s:
  for j,b in enumerate(FONT.get(ch.upper(),'0'*35)):
   if b=='1':rect(x+j%5*scale,y+j//5*scale,scale,scale,c)
  x+=6*scale
previous=int(os.environ.get('T6_PREVIOUS_VT','9'))
fd=os.open('/dev/fb0',os.O_RDWR);fb=mmap.mmap(fd,stride*H)
tty=os.open('/dev/tty',os.O_RDWR);fcntl.ioctl(tty,0x4B3A,1)
fds=[]
for p in Path('/sys/class/input').glob('event*'):
 try:
  if 'T6 keyboard' in (p/'device/name').read_text():fds.append(os.open('/dev/input/'+p.name,os.O_RDONLY|os.O_NONBLOCK))
 except OSError:pass
state=dict(x=200,y=200,clicks=0,right=0,wheel=0,keys=0,lastkey=0,down=False,drag=False,boxx=1000,boxy=450)
lock=threading.Lock();running=True

def stop(*_):
 global running
 running=False
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
def inputs():
 global running
 while running:
  for e in select.select(fds,[],[],.01)[0]:
   data=os.read(e,4096)
   with lock:
    for i in range(0,len(data),24):
     _,_,typ,code,val=struct.unpack('llHHi',data[i:i+24])
     if typ==3:
      if code==0:state['x']=val*(W-1)//32767
      if code==1:state['y']=val*(H-1)//32767
     elif typ==2 and code==8:state['wheel']+=val
     elif typ==1:
      if code==272:
       state['down']=bool(val)
       if val:
        state['clicks']+=1;state['drag']=state['boxx']<=state['x']<state['boxx']+260 and state['boxy']<=state['y']<state['boxy']+160
       else:state['drag']=False
      elif code==273 and val:state['right']+=1
      elif code<256 and val==1:
       state['keys']+=1;state['lastkey']=code
       if code==1:running=False
    if state['drag']:
     state['boxx']=max(0,min(W-260,state['x']-130));state['boxy']=max(250,min(H-160,state['y']-80))
rect(0,0,W,H,0x111b2c)
text(60,45,'T6 MOUSE AND KEYBOARD TEST',6)
text(60,120,'60 HZ TEST - ESC TO RETURN',3)
text(60,910,'MOVE CLICK DRAG SCROLL TYPE',4)
base=bytes(buf);fb[:]=buf;dirty.clear()
thread=threading.Thread(target=inputs,daemon=True);thread.start()
period=1/60;deadline=time.monotonic();start=deadline;report_at=start+5
regions=[];intervals=[];draws=[];missed=0;last=None;bar=0
try:
 while running:
  delay=deadline-time.monotonic()
  if delay>0:time.sleep(delay)
  began=time.monotonic()
  if last is not None:intervals.append((began-last)*1000)
  last=began;deadline+=period
  if began>deadline:
   skip=int((began-deadline)/period)+1;missed+=skip;deadline+=skip*period
  for row,(lo,hi) in regions:
   a=row*stride+lo*4;b=row*stride+hi*4;buf[a:b]=base[a:b]
  dirty.clear()
  with lock:v=state.copy()
  x,y=v['x'],v['y'];boxx,boxy=v['boxx'],v['boxy']
  text(60,175,'TIME '+str(int((began-start)*10)),4,0x55ddaa)
  text(60,250,'X '+str(x)+' Y '+str(y))
  text(60,315,'LEFT '+str(v['clicks'])+' RIGHT '+str(v['right']))
  text(60,380,'WHEEL '+str(v['wheel']))
  text(60,445,'KEYS '+str(v['keys'])+' CODE '+str(v['lastkey']))
  hover=60<=x<600 and 570<=y<730
  rect(60,570,540,160,0xe8a23b if v['down'] and hover else 0x236ea5 if hover else 0x25445c)
  text(110,630,'CLICK HERE',5)
  rect(boxx,boxy,260,160,0xb760cf if v['drag'] else 0x6150a5);text(boxx+20,boxy+60,'DRAG ME')
  bar=(bar+1)%(W-119);rect(60,850,bar,18,0x55ddaa)
  rect(x-15,y-2,31,5,0xffee33);rect(x-2,y-15,5,31,0xffee33)
  current={}
  for xx,yy,r,b in dirty:
   for row in range(yy,b):
    lo,hi=current.get(row,(W,0));current[row]=(min(lo,xx),max(hi,r))
  spans=dict(regions)
  for row,(lo,hi) in current.items():
   l,h=spans.get(row,(W,0));spans[row]=(min(l,lo),max(h,hi))
  regions=list(current.items())
  for row,(lo,hi) in spans.items():
   a=row*stride+lo*4;b=row*stride+hi*4;fb[a:b]=buf[a:b]
  draws.append((time.monotonic()-began)*1000)
  if time.monotonic()>=report_at:
   def stats(v):
    q=sorted(v);return dict(median=statistics.median(q),p95=q[int((len(q)-1)*.95)],max=max(q))
   Path('/tmp/t6-mouse-timing.json').write_text(json.dumps(dict(frames=len(draws),fps=1000/statistics.mean(intervals),interval_ms=stats(intervals),draw_ms=stats(draws),missed_deadlines=missed)))
   intervals.clear();draws.clear();missed=0;report_at=time.monotonic()+5
finally:
 running=False;thread.join(timeout=1)
 for e in fds:os.close(e)
 fcntl.ioctl(tty,0x4B3A,0);os.close(tty);fb.close();os.close(fd)
 subprocess.run(['chvt',str(previous)],check=False)
