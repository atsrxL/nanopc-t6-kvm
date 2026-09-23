# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only host inventory. It never binds ports, streams video, or writes EDID."""
import argparse
import ctypes.util
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import time

def command(argv):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=8, check=False)
        return {"argv":argv,"returncode":p.returncode,"stdout":p.stdout[-40000:],"stderr":p.stderr[-4000:]}
    except (OSError, subprocess.TimeoutExpired) as ex:
        return {"argv":argv,"error":str(ex)}

def read(path):
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError as ex:
        return {"error":str(ex)}

def bound_gadgets(root=Path("/sys/kernel/config/usb_gadget")):
    result=[]
    if not root.is_dir():
        return result
    for path in sorted(root.iterdir()):
        if path.is_dir():
            result.append({"name":path.name,"udc":read(path/"UDC")})
    return result

def listening_ports():
    ports=set()
    for name in ("/proc/net/tcp","/proc/net/tcp6"):
        try:
            for line in Path(name).read_text().splitlines()[1:]:
                fields=line.split()
                if fields[3]=="0A":
                    ports.add(int(fields[1].rsplit(":",1)[1],16))
        except (OSError,ValueError,IndexError):
            continue
    return sorted(ports)

def inspect(device="/dev/video0",port=5900,probe=None):
    devices={}
    names=[device,"/dev/mpp_service","/dev/rga",*map(str,Path("/dev/dri").glob("renderD*")),
           *map(str,Path("/dev/dma_heap").glob("*"))]
    for name in names:
        try:
            s=Path(name).stat()
            devices[name]={"uid":s.st_uid,"gid":s.st_gid,"mode":oct(stat.S_IMODE(s.st_mode)),
                           "character_device":stat.S_ISCHR(s.st_mode),
                           "readable_for_current_uid":os.access(name,os.R_OK),
                           "writable_for_current_uid":os.access(name,os.W_OK)}
        except OSError as ex:
            devices[name]={"error":str(ex)}
    ports=listening_ports()
    udcs={p.name:{"state":read(p/"state"),"function":read(p/"function")}
          for p in Path("/sys/class/udc").glob("*")}
    disks={}
    for path in ("/","/nvme","/opt"):
        if Path(path).exists():
            disks[path]=dict(zip(("total","used","free"),shutil.disk_usage(path)))
    info={"time_unix":time.time(),"read_only":True,"uid":os.geteuid(),
          "machine":platform.machine(),"uname":list(platform.uname()),"os_release":read("/etc/os-release"),
          "device_tree_model":read("/proc/device-tree/model"),"meminfo":read("/proc/meminfo"),
          "loadavg":read("/proc/loadavg"),"devices":devices,"udcs":udcs,
          "gadgets":bound_gadgets(),"ports_listening":ports,"vnc_port":port,"vnc_port_free":port not in ports,
          "disks":disks,"mpp_library":ctypes.util.find_library("rockchip_mpp"),
          "rga_library_optional":ctypes.util.find_library("rga"),
          "ldconfig":command(["ldconfig","-p"]),
          "software":{x:shutil.which(x) for x in ("git","cmake","cc","pkg-config","python3","ffmpeg","v4l2-ctl")}}
    if probe:
        p=command([str(probe),device]); info["video_probe_command"]=p
        try: info["video"]=json.loads(p.get("stdout",""))
        except ValueError: info["video"]={"error":"No valid probe JSON"}
    else:
        info["video"]={"status":"NOT TESTED", "reason":"Compile native/probe.c; pass --probe PATH"}
    blockers=[]
    if info["machine"] not in ("aarch64","arm64"): blockers.append("Not AArch64 RK3588 target")
    if not udcs: blockers.append("No USB device controller visible")
    if port in ports: blockers.append("Requested VNC port is already listening")
    for name in (device,"/dev/mpp_service"):
        if not devices[name].get("character_device"): blockers.append(f"Missing character device: {name}")
    for g in info["gadgets"]:
        if g["udc"]: blockers.append(f"Existing/unknown gadget: {g['name']} (do not override)")
    if not probe: blockers.append("V4L2 read-only probe was not performed")
    if info["video"].get("open_errno"): blockers.append("V4L2 probe open failed")
    info["blockers"]=blockers
    info["note"]="Inventory is not permission proof for another account or an HDMI/MPP/HID acceptance result. No changes performed."
    return info

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--device",default="/dev/video0")
    p.add_argument("--port",type=int,default=5900)
    p.add_argument("--probe",type=Path)
    p.add_argument("--strict",action="store_true")
    args=p.parse_args()
    result=inspect(args.device,args.port,args.probe)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if args.strict and result["blockers"]:
        raise SystemExit(2)

if __name__=="__main__":
    main()
