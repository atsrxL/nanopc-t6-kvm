# SPDX-License-Identifier: GPL-3.0-or-later
"""MS-A2-specific destructive display diagnostic; changes card2/connector378/crtc364.
Run only with an authorized exclusive display window. Restores CRTC on exit.
Never run automatically as part of installation or tests.
"""
import ctypes as C,os,fcntl,mmap,time,signal,math,select
D=C.CDLL('libdrm.so.2',use_errno=True)
u32=C.c_uint32;u16=C.c_uint16
class Mode(C.Structure):
 _fields_=[('clock',u32)]+[(n,u16) for n in ['hdisplay','hsync_start','hsync_end','htotal','hskew','vdisplay','vsync_start','vsync_end','vtotal','vscan']]+[(n,u32) for n in ['vrefresh','flags','type']]+[('name',C.c_char*32)]
class Crtc(C.Structure):
 _fields_=[(n,u32) for n in ['crtc_id','buffer_id','x','y','width','height']]+[('mode_valid',C.c_int),('mode',Mode),('gamma_size',C.c_int)]
class Dumb(C.Structure):
 _fields_=[(n,u32) for n in ['height','width','bpp','flags','handle','pitch']]+[('size',C.c_uint64)]
class Map(C.Structure):
 _fields_=[('handle',u32),('pad',u32),('offset',C.c_uint64)]
D.drmModeGetCrtc.argtypes=[C.c_int,u32];D.drmModeGetCrtc.restype=C.POINTER(Crtc)
D.drmModeSetCrtc.argtypes=[C.c_int,u32,u32,u32,u32,C.POINTER(u32),C.c_int,C.POINTER(Mode)]
D.drmModeAddFB.argtypes=[C.c_int,u32,u32,C.c_uint8,C.c_uint8,u32,u32,C.POINTER(u32)]
fd=os.open('/dev/dri/card2',os.O_RDWR);saved=D.drmModeGetCrtc(fd,364);assert saved
old=Crtc.from_buffer_copy(saved.contents);conn=(u32*1)(378);handle=0;fb=u32();mem=None;buffers=[]
try:
 if D.drmSetMaster(fd):raise OSError(C.get_errno(),'drmSetMaster failed')
 for _ in range(2):
  d=Dumb(height=1440,width=2560,bpp=32);fcntl.ioctl(fd,0xc02064b2,d)
  f=u32()
  if D.drmModeAddFB(fd,2560,1440,24,32,d.pitch,d.handle,C.byref(f)):raise OSError(C.get_errno(),'AddFB')
  m=Map(handle=d.handle);fcntl.ioctl(fd,0xc01064b3,m)
  buffers.append((d,f,mmap.mmap(fd,d.size,offset=m.offset)))
 d,fb,mem=buffers[0]
 D.drmModePageFlip.argtypes=[C.c_int,u32,u32,u32,C.c_void_p]
 # Distinct bars identify the real output, not an encoded synthetic input.
 colors=[0x003030e0,0x0030d030,0x00d03030,0x00dddddd]
 for y in range(1440):mem[y*d.pitch:y*d.pitch+10240]=b''.join(c.to_bytes(4,'little')*640 for c in colors)
 mode=Mode(clock=241500,hdisplay=2560,hsync_start=2608,hsync_end=2640,htotal=2720,vdisplay=1440,vsync_start=1443,vsync_end=1448,vtotal=1481,vrefresh=60,flags=9,type=64,name=b'2560x1440')
 r=D.drmModeSetCrtc(fd,364,fb.value,0,0,conn,1,C.byref(mode))
 print('2560x1440 modeset result',r,'errno',C.get_errno(),flush=True)
 if r!=0:raise RuntimeError('1440p modeset failed')
 running=True
 def stop(*_):
  global running
  running=False
 signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
 # Precompute broad moving color waves; full-frame motion, no disk/video dependencies.
 period=2560
 scan=bytearray()
 for x in range(period):
  rr=int(127+110*math.sin(2*math.pi*x/period))
  gg=int(127+110*math.sin(2*math.pi*x/period+2.094))
  bb=int(127+110*math.sin(2*math.pi*x/period+4.188))
  scan.extend(bytes([bb,gg,rr,0]))
 scan=bytes(scan)*2
 rows=[(y*3)%period for y in range(1440)]
 deadline=time.monotonic();frame=0
 while running:
  delay=deadline-time.monotonic()
  if delay>0:time.sleep(delay)
  now=time.monotonic();deadline=max(deadline+1/60,now)
  d,fb,mem=buffers[(frame+1)%2]
  offset=(frame*8)%period
  for y,shift in enumerate(rows):
   x=(shift+offset)%period;mem[y*d.pitch:y*d.pitch+10240]=scan[x*4:x*4+10240]
  # A wide bright band follows a smooth periodic trajectory across the picture.
  left=int(1120+1000*math.sin(frame/120));top=int(620+450*math.sin(frame/180))
  white=bytes([240,240,240,0])*320
  for y in range(top,min(top+160,1440)):mem[y*d.pitch+left*4:y*d.pitch+(left+320)*4]=white
  if D.drmModePageFlip(fd,364,fb.value,1,None):raise OSError(C.get_errno(),'page flip')
  if not select.select([fd],[],[],2)[0]:raise TimeoutError('page flip completion')
  event=os.read(fd,4096)
  if len(event)<8:raise RuntimeError('short DRM event')
  frame+=1
  if frame%600==0:print('vblank flips',frame,flush=True)

finally:
 r=D.drmModeSetCrtc(fd,old.crtc_id,old.buffer_id,old.x,old.y,conn,1,C.byref(old.mode));print('restore result',r,flush=True)
 for d,fb,mem in buffers:
  mem.close();D.drmModeRmFB(fd,fb.value);fcntl.ioctl(fd,0xc00464b4,u32(d.handle))
 D.drmDropMaster(fd);os.close(fd)
