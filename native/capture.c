/* SPDX-License-Identifier: GPL-3.0-or-later
 * Actual V4L2 multi-plane -> CPU NV12 -> MPP H.264 worker.
 * No EDID writes, no scaler, no fake generated picture fallback.
 * One worker owns one format/encoder epoch. Source change exits cleanly;
 * Python supervisor reopens/query/reallocates and assigns a new epoch.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/random.h>
#include <unistd.h>
#include "rk_mpi.h"
#include "mpp_buffer.h"
#include "mpp_frame.h"
#include "mpp_packet.h"
#include "rk_venc_cfg.h"
#include "pixels.h"
#include "wire.h"

#define COUNT 4
#define ALIGN64(x) (((x)+63U)&~63U)
static volatile sig_atomic_t stopping;
static void on_signal(int sig) { (void)sig; stopping=1; }
static int xioctl(int fd,unsigned long req,void *arg) {
    int r; do { r=ioctl(fd,req,arg); } while(r<0&&errno==EINTR&&!stopping); return r;
}
struct opts { const char *device; unsigned fps,bitrate,gop,mw,mh,ew,eh; };
struct mapping { void *addr[VIDEO_MAX_PLANES]; size_t size[VIDEO_MAX_PLANES]; };
struct state {
    int fd,streaming; unsigned count,nplanes;
    struct mapping maps[COUNT];
    struct v4l2_pix_format_mplane fmt;
    MppCtx ctx; MppApi *api; MppEncCfg cfg;
    MppBufferGroup group; MppBuffer input;
    unsigned hs,vs; size_t input_size;
    uint8_t *au; uint64_t epoch,sequence,captured;
    int matrix709,full_range;
};
static void close_state(struct state *s) {
    if(s->fd>=0 && s->streaming) {
        enum v4l2_buf_type t=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        xioctl(s->fd,VIDIOC_STREAMOFF,&t);
    }
    if(s->ctx) mpp_destroy(s->ctx);
    if(s->input) mpp_buffer_put(s->input);
    if(s->group) mpp_buffer_group_put(s->group);
    if(s->cfg) mpp_enc_cfg_deinit(s->cfg);
    for(unsigned i=0;i<s->count;i++) for(unsigned p=0;p<s->nplanes;p++)
        if(s->maps[i].addr[p] && s->maps[i].addr[p]!=MAP_FAILED)
            munmap(s->maps[i].addr[p],s->maps[i].size[p]);
    if(s->fd>=0) close(s->fd);
    free(s->au);
}
static int queue(struct state *s,unsigned index) {
    struct v4l2_plane planes[VIDEO_MAX_PLANES]={0};
    struct v4l2_buffer b={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
                         .memory=V4L2_MEMORY_MMAP,.index=index,.length=s->nplanes,.m.planes=planes};
    return xioctl(s->fd,VIDIOC_QBUF,&b);
}
static int capture_open(struct state *s,const struct opts *o) {
    s->fd=open(o->device,O_RDWR|O_NONBLOCK|O_CLOEXEC);
    if(s->fd<0) return -1;
    struct v4l2_capability cap={0};
    if(xioctl(s->fd,VIDIOC_QUERYCAP,&cap)<0) return -1;
    unsigned caps=cap.capabilities & V4L2_CAP_DEVICE_CAPS?cap.device_caps:cap.capabilities;
    if(!(caps&V4L2_CAP_VIDEO_CAPTURE_MPLANE)||!(caps&V4L2_CAP_STREAMING)) { errno=ENOTSUP; return -1; }
    struct v4l2_dv_timings t={0};
    if(xioctl(s->fd,VIDIOC_QUERY_DV_TIMINGS,&t)<0) return -1;
    if(t.type!=V4L2_DV_BT_656_1120||t.bt.interlaced||t.bt.width%2||t.bt.height%2||
       !t.bt.width||!t.bt.height||t.bt.width>o->mw||t.bt.height>o->mh||
       (o->ew && (t.bt.width!=o->ew||t.bt.height!=o->eh))) {
        fprintf(stderr,"t6: native timing %ux%u interlaced=%u rejected; no scaling or silent fallback\n",
                t.bt.width,t.bt.height,t.bt.interlaced); errno=ENOTSUP; return -1;
    }
    /* Apply only currently observed timing; never manufacture or install EDID. */
    if(xioctl(s->fd,VIDIOC_S_DV_TIMINGS,&t)<0) {
        fprintf(stderr,"t6: driver rejected observed DV timing (1440p CEA-list restriction is possible)\n");
        return -1;
    }
    struct v4l2_format f={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE};
    if(xioctl(s->fd,VIDIOC_G_FMT,&f)<0) return -1;
    s->fmt=f.fmt.pix_mp; s->nplanes=s->fmt.num_planes;
    if(s->fmt.width!=t.bt.width||s->fmt.height!=t.bt.height||
       (s->nplanes!=1 && s->nplanes!=2) || s->fmt.field!=V4L2_FIELD_NONE) { errno=ENOTSUP; return -1; }
    uint32_t pf=s->fmt.pixelformat;
    if(pf!=V4L2_PIX_FMT_NV12&&pf!=V4L2_PIX_FMT_NV16&&pf!=V4L2_PIX_FMT_NV24&&pf!=V4L2_PIX_FMT_BGR24) {
        errno=ENOTSUP; return -1;
    }
    unsigned c=s->fmt.colorspace, enc=s->fmt.ycbcr_enc,quant=s->fmt.quantization;
    if(c==V4L2_COLORSPACE_BT2020||c==V4L2_COLORSPACE_OPRGB||
       (s->fmt.xfer_func!=V4L2_XFER_FUNC_DEFAULT && s->fmt.xfer_func!=V4L2_XFER_FUNC_709 &&
        s->fmt.xfer_func!=V4L2_XFER_FUNC_SRGB)) { errno=ENOTSUP; return -1; }
    if(enc==V4L2_YCBCR_ENC_DEFAULT) enc=V4L2_MAP_YCBCR_ENC_DEFAULT(c);
    if(pf!=V4L2_PIX_FMT_BGR24 && enc!=V4L2_YCBCR_ENC_601 && enc!=V4L2_YCBCR_ENC_709) {
        fprintf(stderr,"t6: unknown/extended YCbCr matrix rejected\n"); errno=ENOTSUP; return -1;
    }
    s->matrix709=(pf==V4L2_PIX_FMT_BGR24?s->fmt.height>=720:enc==V4L2_YCBCR_ENC_709);
    if(pf==V4L2_PIX_FMT_BGR24 && quant==V4L2_QUANTIZATION_LIM_RANGE) {
        fprintf(stderr,"t6: limited-range BGR input not implemented\n"); errno=ENOTSUP; return -1;
    }
    s->full_range=(pf!=V4L2_PIX_FMT_BGR24 && quant==V4L2_QUANTIZATION_FULL_RANGE);
    unsigned long long totalw=(unsigned long long)t.bt.width+t.bt.hfrontporch+t.bt.hsync+t.bt.hbackporch;
    unsigned long long totalh=(unsigned long long)t.bt.height+t.bt.vfrontporch+t.bt.vsync+t.bt.vbackporch;
    double signal_fps=(totalw&&totalh)?(double)t.bt.pixelclock/(double)(totalw*totalh):0;
    char json[1024];
    snprintf(json,sizeof(json),"{\"online\":false,\"message\":\"Configuring native capture\","
             "\"input\":{\"width\":%u,\"height\":%u,\"signal_fps\":%.6f,\"fourcc\":%u,"
             "\"num_planes\":%u,\"bytesperline\":%u,\"sizeimage\":%u,\"colorspace\":%u,"
             "\"ycbcr_enc\":%u,\"quantization\":%u}}",
             s->fmt.width,s->fmt.height,signal_fps,pf,s->nplanes,s->fmt.plane_fmt[0].bytesperline,
             s->fmt.plane_fmt[0].sizeimage,c,enc,quant);
    if(t6_write_status(STDOUT_FILENO,json)<0) return -1;
    struct v4l2_event_subscription sub={.type=V4L2_EVENT_SOURCE_CHANGE};
    if(xioctl(s->fd,VIDIOC_SUBSCRIBE_EVENT,&sub)<0 && errno!=EINVAL) return -1;
    struct v4l2_requestbuffers req={.count=COUNT,.type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
                                  .memory=V4L2_MEMORY_MMAP};
    if(xioctl(s->fd,VIDIOC_REQBUFS,&req)<0) return -1;
    if(req.count<2||req.count>COUNT) { errno=ENOBUFS; return -1; }
    s->count=req.count;
    for(unsigned i=0;i<s->count;i++) {
        struct v4l2_plane planes[VIDEO_MAX_PLANES]={0};
        struct v4l2_buffer b={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,.memory=V4L2_MEMORY_MMAP,
                             .index=i,.length=s->nplanes,.m.planes=planes};
        if(xioctl(s->fd,VIDIOC_QUERYBUF,&b)<0) return -1;
        for(unsigned p=0;p<s->nplanes;p++) {
            s->maps[i].size[p]=planes[p].length;
            s->maps[i].addr[p]=mmap(NULL,planes[p].length,PROT_READ|PROT_WRITE,MAP_SHARED,
                                   s->fd,planes[p].m.mem_offset);
            if(s->maps[i].addr[p]==MAP_FAILED) return -1;
        }
        if(queue(s,i)<0) return -1;
    }
    enum v4l2_buf_type type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    if(xioctl(s->fd,VIDIOC_STREAMON,&type)<0) return -1;
    s->streaming=1;
    return 0;
}
static int encoder_open(struct state *s,const struct opts *o) {
    s->hs=ALIGN64(s->fmt.width); s->vs=ALIGN64(s->fmt.height);
    s->input_size=(size_t)s->hs*s->vs*3/2;
#define M(call) do { MPP_RET r=(call); if(r!=MPP_OK) { fprintf(stderr,"t6: %s failed: %d\n",#call,r); return -1; } } while(0)
    M(mpp_create(&s->ctx,&s->api));
    M(mpp_init(s->ctx,MPP_CTX_ENC,MPP_VIDEO_CodingAVC));
    M(mpp_enc_cfg_init(&s->cfg));
    M(s->api->control(s->ctx,MPP_ENC_GET_CFG,s->cfg));
#define C(key,value) M(mpp_enc_cfg_set_s32(s->cfg,key,value))
    C("codec:type",MPP_VIDEO_CodingAVC);
    C("prep:width",s->fmt.width); C("prep:height",s->fmt.height);
    C("prep:hor_stride",s->hs); C("prep:ver_stride",s->vs); C("prep:format",MPP_FMT_YUV420SP);
    C("prep:range",s->full_range?MPP_FRAME_RANGE_JPEG:MPP_FRAME_RANGE_MPEG);
    /* color is matrix coefficients; primaries/transfer kept consistent with SDR source. */
    C("prep:colorspace",s->matrix709?1:6); C("prep:colorprim",s->matrix709?1:6);
    C("prep:colortrc",s->matrix709?1:6);
    C("rc:mode",MPP_ENC_RC_MODE_CBR); C("rc:bps_target",o->bitrate);
    C("rc:bps_max",o->bitrate*17/16); C("rc:bps_min",o->bitrate*15/16);
    C("rc:fps_in_flex",0); C("rc:fps_in_num",o->fps); C("rc:fps_in_denom",1);
    C("rc:fps_out_flex",0); C("rc:fps_out_num",o->fps); C("rc:fps_out_denom",1);
    C("rc:gop",o->gop); M(mpp_enc_cfg_set_u32(s->cfg,"rc:drop_mode",MPP_ENC_RC_DROP_FRM_DISABLED));
    M(mpp_enc_cfg_set_u32(s->cfg,"rc:max_reenc_times",0)); C("rc:qp_init",-1); C("rc:qp_min",10); C("rc:qp_max",51);
    C("rc:qp_min_i",10); C("rc:qp_max_i",51); C("rc:qp_ip",2);
    /* Baseline profile rules out B slices; level 5.1 covers target 1440p60 budget. */
    C("h264:profile",66); C("h264:level",51); C("h264:cabac_en",0);
    M(mpp_enc_cfg_set_u32(s->cfg,"split:mode",0));
    M(mpp_enc_cfg_set_u32(s->cfg,"h264:vui_en",1));
    C("base:low_delay",1); C("h264:stream_type",0);
    M(s->api->control(s->ctx,MPP_ENC_SET_CFG,s->cfg));
    MppEncHeaderMode mode=MPP_ENC_HEADER_MODE_EACH_IDR;
    M(s->api->control(s->ctx,MPP_ENC_SET_HEADER_MODE,&mode));
    MppPollType timeout=MPP_POLL_BLOCK;
    M(s->api->control(s->ctx,MPP_SET_OUTPUT_TIMEOUT,&timeout));
    M(mpp_buffer_group_get_internal(&s->group,MPP_BUFFER_TYPE_DRM,0));
    M(mpp_buffer_get(s->group,&s->input,s->input_size));
    s->au=malloc(T6_MAX_AU); if(!s->au) return -1;
    if(getrandom(&s->epoch,sizeof(s->epoch),0)!=(ssize_t)sizeof(s->epoch)) return -1;
    if(!s->epoch) s->epoch=1;
    return 0;
#undef C
#undef M
}
static int convert(struct state *s,unsigned index,const struct v4l2_plane *planes) {
    struct t6_image im={.width=s->fmt.width,.height=s->fmt.height,.matrix709=s->matrix709};
    switch(s->fmt.pixelformat) {
    case V4L2_PIX_FMT_NV12: im.format=T6_NV12; break;
    case V4L2_PIX_FMT_NV16: im.format=T6_NV16; break;
    case V4L2_PIX_FMT_NV24: im.format=T6_NV24; break;
    case V4L2_PIX_FMT_BGR24: im.format=T6_BGR24; break;
    default: return -1;
    }
    for(unsigned p=0;p<s->nplanes;p++) {
        if(planes[p].bytesused> s->maps[index].size[p] ||
           planes[p].data_offset>=planes[p].bytesused) return -1;
    }
    im.y=(const uint8_t*)s->maps[index].addr[0]+planes[0].data_offset;
    im.y_size=planes[0].bytesused-planes[0].data_offset;
    im.y_stride=s->fmt.plane_fmt[0].bytesperline;
    if(im.format!=T6_BGR24) {
        size_t ybytes=im.y_stride*im.height;
        unsigned chroma_rows=im.format==T6_NV12?im.height/2:im.height;
        if(s->nplanes==2) {
            im.uv=(const uint8_t*)s->maps[index].addr[1]+planes[1].data_offset;
            im.uv_size=planes[1].bytesused-planes[1].data_offset;
            im.uv_stride=s->fmt.plane_fmt[1].bytesperline;
        } else {
            /* This driver's logical planes are packed Y followed by UV.
             * Reject ambiguous/short sizeimage; never assume width == stride. */
            size_t total=s->fmt.plane_fmt[0].sizeimage;
            if(ybytes>=total || total>im.y_size || (total-ybytes)%chroma_rows) return -1;
            im.uv=im.y+ybytes; im.uv_size=total-ybytes;
            im.uv_stride=im.uv_size/chroma_rows; im.y_size=ybytes;
        }
    }
    if(mpp_buffer_sync_begin(s->input)!=MPP_OK) return -1;
    int result=t6_to_nv12(&im,mpp_buffer_get_ptr(s->input),s->input_size,s->hs,s->vs);
    if(mpp_buffer_sync_end(s->input)!=MPP_OK) return -1;
    return result;
}
static int encode(struct state *s,uint64_t pts,int force_idr) {
    if(force_idr && s->api->control(s->ctx,MPP_ENC_SET_IDR_FRAME,NULL)!=MPP_OK) return -1;
    MppFrame f=NULL;
    if(mpp_frame_init(&f)!=MPP_OK) return -1;
    mpp_frame_set_width(f,s->fmt.width); mpp_frame_set_height(f,s->fmt.height);
    mpp_frame_set_hor_stride(f,s->hs); mpp_frame_set_ver_stride(f,s->vs);
    mpp_frame_set_fmt(f,MPP_FMT_YUV420SP); mpp_frame_set_pts(f,(RK_S64)pts);
    mpp_frame_set_buffer(f,s->input);
    MPP_RET ret=s->api->encode_put_frame(s->ctx,f);
    mpp_frame_deinit(&f);
    if(ret!=MPP_OK) return -1;
    size_t used=0; int end=0;
    do {
        MppPacket packet=NULL;
        ret=s->api->encode_get_packet(s->ctx,&packet);
        if(ret!=MPP_OK||!packet) return -1;
        size_t n=mpp_packet_get_length(packet);
        if(n>T6_MAX_AU-used) { mpp_packet_deinit(&packet); return -1; }
        memcpy(s->au+used,mpp_packet_get_pos(packet),n); used+=n;
        end=!mpp_packet_is_partition(packet)||mpp_packet_is_eoi(packet);
        mpp_packet_deinit(&packet);
    } while(!end&&!stopping);
    if(!end||!used) return -1;
    unsigned mask=t6_nal_mask(s->au,used);
    int key=!!(mask&(1U<<5));
    if(key && (mask&((1U<<7)|(1U<<8)))!=((1U<<7)|(1U<<8))) {
        fprintf(stderr,"t6: IDR lacks inline SPS/PPS; refusing unsafe AU\n"); return -1;
    }
    return t6_write_frame(STDOUT_FILENO,1,1U|(key?2U:0U),s->fmt.width,s->fmt.height,
                          s->epoch,++s->sequence,pts,s->au,used);
}
static int work(struct state *s,const struct opts *o) {
    uint64_t due=0,last_status=t6_now_us();
    int force_idr=1;
    while(!stopping) {
        struct pollfd pollers[2]={{s->fd,POLLIN|POLLPRI,0},{STDIN_FILENO,POLLIN,0}};
        int r=poll(pollers,2,2000);
        if(r<0 && errno==EINTR) continue;
        if(r<=0) { errno=ETIMEDOUT; return -1; }
        if(pollers[1].revents&(POLLIN|POLLHUP|POLLERR)) {
            char control[64]; ssize_t n=read(STDIN_FILENO,control,sizeof(control));
            if(n<=0) return 0;
            for(ssize_t i=0;i<n;i++) if(control[i]=='K') force_idr=1; else return -1;
        }
        if(pollers[0].revents&(POLLPRI|POLLERR|POLLHUP)) {
            fprintf(stderr,"t6: source change/error: tearing down capture and encoder epoch\n");
            errno=EPIPE; return -1;
        }
        if(!(pollers[0].revents&POLLIN)) continue;
        struct v4l2_plane planes[VIDEO_MAX_PLANES]={0};
        struct v4l2_buffer b={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,.memory=V4L2_MEMORY_MMAP,
                             .length=s->nplanes,.m.planes=planes};
        if(xioctl(s->fd,VIDIOC_DQBUF,&b)<0) { if(errno==EAGAIN) continue; return -1; }
        if(b.index>=s->count) return -1;
        s->captured++;
        uint64_t now=t6_now_us();
        /* Only raw, NOT already encoded, frames can be skipped for rate limiting. */
        if((b.flags&V4L2_BUF_FLAG_ERROR) || now+1000<due) {
            if(queue(s,b.index)<0) return -1;
            continue;
        }
        if(convert(s,b.index,planes)<0) { fprintf(stderr,"t6: invalid/unsupported plane layout\n"); return -1; }
        /* Copy completes before return to driver; MPP owns a separate DRM buffer. */
        if(queue(s,b.index)<0) return -1;
        if(encode(s,now,force_idr)<0) return -1;
        force_idr=0;
        due=now+1000000/o->fps;
        if(now-last_status>=1000000) {
            char json[256];
            snprintf(json,sizeof(json),"{\"online\":true,\"capture_frames\":%llu,\"encoded_frames\":%llu,\"copy\":true}",
                     (unsigned long long)s->captured,(unsigned long long)s->sequence);
            if(t6_write_status(STDOUT_FILENO,json)<0) return -1;
            last_status=now;
            /* Re-query guards drivers without source-change event support. */
            struct v4l2_dv_timings t={0};
            if(xioctl(s->fd,VIDIOC_QUERY_DV_TIMINGS,&t)<0 || t.bt.interlaced ||
               t.bt.width!=s->fmt.width||t.bt.height!=s->fmt.height) return -1;
            struct v4l2_format current={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE};
            if(xioctl(s->fd,VIDIOC_G_FMT,&current)<0) return -1;
            const struct v4l2_pix_format_mplane *f=&current.fmt.pix_mp;
            if(f->width!=s->fmt.width||f->height!=s->fmt.height||f->pixelformat!=s->fmt.pixelformat||
               f->num_planes!=s->fmt.num_planes||f->colorspace!=s->fmt.colorspace||
               f->ycbcr_enc!=s->fmt.ycbcr_enc||f->quantization!=s->fmt.quantization||
               f->xfer_func!=s->fmt.xfer_func) return -1;
            for(unsigned i=0;i<f->num_planes;i++)
                if(f->plane_fmt[i].bytesperline!=s->fmt.plane_fmt[i].bytesperline||
                   f->plane_fmt[i].sizeimage!=s->fmt.plane_fmt[i].sizeimage) return -1;
        }
    }
    return 0;
}
static unsigned number(const char *s) {
    char *end=NULL; errno=0; unsigned long n=strtoul(s,&end,10);
    if(errno||!s[0]||*end||n>100000000U||s[0]=='-') { fprintf(stderr,"Invalid integer\n"); exit(2); }
    return (unsigned)n;
}
int main(int argc,char **argv) {
    struct opts o={"/dev/video0",60,20000000,60,1920,1080,0,0};
    for(int i=1;i<argc;i+=2) {
        if(i+1>=argc) { fprintf(stderr,"Missing argument value\n"); return 2; }
        const char *k=argv[i],*v=argv[i+1];
        if(!strcmp(k,"--device")) o.device=v;
        else if(!strcmp(k,"--fps")) o.fps=number(v);
        else if(!strcmp(k,"--bitrate")) o.bitrate=number(v);
        else if(!strcmp(k,"--gop")) o.gop=number(v);
        else if(!strcmp(k,"--max-width")) o.mw=number(v);
        else if(!strcmp(k,"--max-height")) o.mh=number(v);
        else if(!strcmp(k,"--expected-width")) o.ew=number(v);
        else if(!strcmp(k,"--expected-height")) o.eh=number(v);
        else { fprintf(stderr,"Unknown option: %s\n",k); return 2; }
    }
    if(!o.fps||o.fps>60||o.bitrate<100000||o.bitrate>35000000||!o.gop||o.gop>120||
       o.mw<64||o.mw>2560||o.mh<64||o.mh>1440||o.mw%2||o.mh%2||
       (!!o.ew!=!!o.eh)||o.ew>o.mw||o.eh>o.mh||o.ew%2||o.eh%2) return 2;
    signal(SIGTERM,on_signal); signal(SIGINT,on_signal); signal(SIGPIPE,SIG_IGN);
    struct state s={.fd=-1};
    int r=capture_open(&s,&o);
    if(r==0) r=encoder_open(&s,&o);
    if(r==0) r=work(&s,&o);
    if(r<0) {
        fprintf(stderr,"t6: worker error (errno=%d: %s); supervisor may retry\n",errno,strerror(errno));
        t6_write_status(STDOUT_FILENO,"{\"online\":false,\"message\":\"Capture/encoder failed; inspect native stderr\"}");
    }
    close_state(&s);
    return r<0?75:0;
}
