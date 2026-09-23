#!/usr/bin/env python3
"""Apply a validated two-block EDID to an idle T6 HDMI receiver."""
import argparse,ctypes,fcntl,os
from pathlib import Path
class Edid(ctypes.Structure):
    _fields_=[('pad',ctypes.c_uint32),('start_block',ctypes.c_uint32),('blocks',ctypes.c_uint32),('reserved',ctypes.c_uint32*5),('edid',ctypes.c_void_p)]
def main():
    p=argparse.ArgumentParser();p.add_argument('file',type=Path);p.add_argument('--device',default='/dev/video0');a=p.parse_args()
    b=a.file.read_bytes()
    if len(b)!=256 or b[:8]!=bytes.fromhex('00ffffffffffff00') or b[126]!=1 or any(sum(b[i:i+128])%256 for i in (0,128)):
        raise SystemExit('Invalid two-block EDID')
    data=ctypes.create_string_buffer(b);ed=Edid(blocks=2,edid=ctypes.addressof(data))
    fd=os.open(a.device,os.O_RDWR|os.O_CLOEXEC)
    try:
        fcntl.ioctl(fd,0xc0285629,ed) # VIDIOC_S_EDID, 64-bit Linux
        verify=ctypes.create_string_buffer(256);read=Edid(blocks=2,edid=ctypes.addressof(verify))
        fcntl.ioctl(fd,0xc0285628,read)
        if verify.raw!=b:raise RuntimeError('EDID readback mismatch')
    finally:os.close(fd)
    print('EDID applied and readback verified')
if __name__=='__main__':main()
