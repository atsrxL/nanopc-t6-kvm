/* SPDX-License-Identifier: GPL-3.0-or-later */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

static void quoted(const char *s) {
    putchar('"');
    for(const unsigned char *p=(const unsigned char*)s;*p;p++) {
        if(*p=='"'||*p=='\\') printf("\\%c",*p);
        else if(*p<32) printf("\\u%04x",*p);
        else putchar(*p);
    }
    putchar('"');
}
static void timing(const struct v4l2_dv_timings *t) {
    printf("{\"type\":%u,\"width\":%u,\"height\":%u,\"interlaced\":%u,\"pixelclock\":%llu}",
           t->type,t->bt.width,t->bt.height,t->bt.interlaced,(unsigned long long)t->bt.pixelclock);
}
int main(int argc,char **argv) {
    const char *dev=argc==2?argv[1]:"/dev/video0";
    int fd=open(dev,O_RDONLY|O_NONBLOCK|O_CLOEXEC);
    printf("{\"read_only\":true,\"device\":"); quoted(dev);
    if(fd<0) { printf(",\"open_errno\":%d}\n",errno); return 2; }
    struct v4l2_capability cap={0};
    int r=ioctl(fd,VIDIOC_QUERYCAP,&cap),e=errno;
    printf(",\"querycap_errno\":%d",r<0?e:0);
    if(r==0) { printf(",\"driver\":"); quoted((const char*)cap.driver); printf(",\"device_caps\":%u",cap.device_caps); }
    struct v4l2_format f={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE};
    r=ioctl(fd,VIDIOC_G_FMT,&f); e=errno;
    printf(",\"g_fmt_errno\":%d",r<0?e:0);
    if(r==0) {
        struct v4l2_pix_format_mplane *p=&f.fmt.pix_mp;
        printf(",\"format\":{\"width\":%u,\"height\":%u,\"fourcc\":%u,\"num_planes\":%u,\"planes\":[",
               p->width,p->height,p->pixelformat,p->num_planes);
        for(unsigned i=0;i<p->num_planes && i<VIDEO_MAX_PLANES;i++)
            printf("%s{\"bytesperline\":%u,\"sizeimage\":%u}",i?",":"",p->plane_fmt[i].bytesperline,p->plane_fmt[i].sizeimage);
        printf("]}");
    }
    printf(",\"formats\":[");
    for(unsigned i=0;i<128;i++) {
        struct v4l2_fmtdesc d={.index=i,.type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE};
        if(ioctl(fd,VIDIOC_ENUM_FMT,&d)<0) break;
        if(i) putchar(',');
        printf("{\"fourcc\":%u,\"description\":",d.pixelformat); quoted((const char*)d.description); putchar('}');
    }
    printf("]");
    struct v4l2_dv_timings t={0};
    r=ioctl(fd,VIDIOC_QUERY_DV_TIMINGS,&t); e=errno;
    printf(",\"query_timings_errno\":%d",r<0?e:0);
    if(r==0) { printf(",\"observed_timings\":"); timing(&t); }
    struct v4l2_dv_timings_cap tc={0};
    r=ioctl(fd,VIDIOC_DV_TIMINGS_CAP,&tc); e=errno;
    printf(",\"timings_cap_errno\":%d",r<0?e:0);
    if(r==0) printf(",\"timings_cap\":{\"min_width\":%u,\"max_width\":%u,\"min_height\":%u,\"max_height\":%u,\"standards\":%u,\"capabilities\":%u}",
        tc.bt.min_width,tc.bt.max_width,tc.bt.min_height,tc.bt.max_height,tc.bt.standards,tc.bt.capabilities);
    printf(",\"enumerated_timings\":[");
    for(unsigned i=0;i<128;i++) {
        struct v4l2_enum_dv_timings en={.index=i};
        if(ioctl(fd,VIDIOC_ENUM_DV_TIMINGS,&en)<0) break;
        if(i) putchar(',');
        timing(&en.timings);
    }
    unsigned char edid[32768]={0};
    struct v4l2_edid ed={.blocks=256,.edid=edid};
    r=ioctl(fd,VIDIOC_G_EDID,&ed); e=errno;
    printf("],\"edid_errno\":%d",r<0?e:0);
    if(r==0 && ed.blocks<=256) {
        printf(",\"edid_blocks\":%u,\"edid_hex\":\"",ed.blocks);
        for(unsigned i=0;i<ed.blocks*128;i++) printf("%02x",edid[i]);
        putchar('"');
    }
    printf("}\n"); close(fd); return 0;
}
