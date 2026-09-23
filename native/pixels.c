/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "pixels.h"
#include <string.h>
#include <errno.h>
#if defined(__aarch64__) && !defined(T6_SCALAR_ONLY)
#include <arm_neon.h>
static void bgr8(const uint8_t *p,int bt,uint8x8_t *y,int16x8_t *u,int16x8_t *v) {
    uint8x8x3_t c=vld3_u8(p);
    uint16x8_t b=vmovl_u8(c.val[0]),g=vmovl_u8(c.val[1]),r=vmovl_u8(c.val[2]);
    uint16x8_t yy=vaddq_u16(vaddq_u16(vmulq_n_u16(r,bt?47:66),
        vmulq_n_u16(g,bt?157:129)),vmulq_n_u16(b,bt?16:25));
    *y=vadd_u8(vshrn_n_u16(vaddq_u16(yy,vdupq_n_u16(128)),8),vdup_n_u8(16));
    int16x8_t rr=vreinterpretq_s16_u16(r),gg=vreinterpretq_s16_u16(g),bb=vreinterpretq_s16_u16(b);
    *u=vaddq_s16(vshrq_n_s16(vaddq_s16(vaddq_s16(vmulq_n_s16(rr,bt?-26:-38),
        vmulq_n_s16(gg,bt?-87:-74)),vaddq_s16(vmulq_n_s16(bb,112),vdupq_n_s16(128))),8),vdupq_n_s16(128));
    *v=vaddq_s16(vshrq_n_s16(vaddq_s16(vaddq_s16(vmulq_n_s16(rr,112),
        vmulq_n_s16(gg,bt?-102:-94)),vaddq_s16(vmulq_n_s16(bb,bt?-10:-18),vdupq_n_s16(128))),8),vdupq_n_s16(128));
}
#endif

static int span(size_t available,size_t stride,unsigned rows,size_t used) {
    return rows && stride >= used && (rows-1) <= SIZE_MAX/stride &&
           (rows-1)*stride <= available && used <= available-(rows-1)*stride;
}
static uint8_t clip(int v) { return (uint8_t)(v<0?0:(v>255?255:v)); }
static void rgb(const uint8_t *p,int bt709,int *y,int *u,int *v) {
    int b=p[0],g=p[1],r=p[2];
    /* Full-range RGB -> limited-range YUV, integer BT.601/BT.709. */
    if (bt709) {
        *y=((47*r+157*g+16*b+128)>>8)+16;
        *u=((-26*r-87*g+112*b+128)>>8)+128;
        *v=((112*r-102*g-10*b+128)>>8)+128;
    } else {
        *y=((66*r+129*g+25*b+128)>>8)+16;
        *u=((-38*r-74*g+112*b+128)>>8)+128;
        *v=((112*r-94*g-18*b+128)>>8)+128;
    }
}
int t6_to_nv12(const struct t6_image *s,uint8_t *dst,size_t cap,size_t ds,size_t dh) {
    if (!s||!dst||!s->y||!s->width||!s->height||s->width%2||s->height%2||
        s->width>4096||s->height>4096||ds<s->width||dh<s->height||dh%2||
        ds>SIZE_MAX/dh || ds*dh>SIZE_MAX/3*2 || cap < ds*dh+ds*(dh/2)) return -EINVAL;
    unsigned w=s->width,h=s->height;
    if (!span(s->y_size,s->y_stride,h,s->format==T6_BGR24?3*w:w)) return -EINVAL;
    if (s->format!=T6_BGR24 && (!s->uv ||
        !span(s->uv_size,s->uv_stride,s->format==T6_NV12?h/2:h,
              s->format==T6_NV24?2*w:w))) return -EINVAL;
    if (s->format<T6_NV12 || s->format>T6_BGR24) return -EINVAL;
    memset(dst,16,ds*dh);
    uint8_t *duv=dst+ds*dh;
    memset(duv,128,ds*(dh/2));
#if defined(__aarch64__) && !defined(T6_SCALAR_ONLY)
    if(s->format==T6_BGR24 && w%8==0) {
        for(unsigned y=0;y<h;y+=2) for(unsigned x=0;x<w;x+=8) {
            uint8x8_t y0,y1; int16x8_t u0,u1,v0,v1;
            bgr8(s->y+y*s->y_stride+x*3,s->matrix709,&y0,&u0,&v0);
            bgr8(s->y+(y+1)*s->y_stride+x*3,s->matrix709,&y1,&u1,&v1);
            vst1_u8(dst+y*ds+x,y0); vst1_u8(dst+(y+1)*ds+x,y1);
            int16x8_t us=vaddq_s16(u0,u1),vs=vaddq_s16(v0,v1);
            int16x4_t ua=vshr_n_s16(vadd_s16(vpadd_s16(vget_low_s16(us),vget_high_s16(us)),vdup_n_s16(2)),2);
            int16x4_t va=vshr_n_s16(vadd_s16(vpadd_s16(vget_low_s16(vs),vget_high_s16(vs)),vdup_n_s16(2)),2);
            uint8x8_t uv=vqmovun_s16(vcombine_s16(ua,va));
            uint8x8_t zipped=vzip_u8(uv,vext_u8(uv,uv,4)).val[0];
            vst1_u8(duv+(y/2)*ds+x,zipped);
        }
        return 0;
    }
#endif
    for(unsigned y=0;y<h;y++) {
        if(s->format!=T6_BGR24) memcpy(dst+y*ds,s->y+y*s->y_stride,w);
        else for(unsigned x=0;x<w;x++) {
            int yy,u,v; rgb(s->y+y*s->y_stride+x*3,s->matrix709,&yy,&u,&v);
            dst[y*ds+x]=clip(yy);
        }
    }
    if(s->format==T6_NV12) {
        for(unsigned y=0;y<h/2;y++) memcpy(duv+y*ds,s->uv+y*s->uv_stride,w);
        return 0;
    }
    for(unsigned y=0;y<h/2;y++) for(unsigned x=0;x<w;x+=2) {
        unsigned u=0,v=0;
        if(s->format==T6_NV12) {
            u=s->uv[y*s->uv_stride+x]; v=s->uv[y*s->uv_stride+x+1];
        } else if(s->format==T6_NV16) {
            u=(s->uv[2*y*s->uv_stride+x]+s->uv[(2*y+1)*s->uv_stride+x]+1)/2;
            v=(s->uv[2*y*s->uv_stride+x+1]+s->uv[(2*y+1)*s->uv_stride+x+1]+1)/2;
        } else {
            int sumu=0,sumv=0;
            for(unsigned dy=0;dy<2;dy++) for(unsigned dx=0;dx<2;dx++) {
                if(s->format==T6_NV24) {
                    sumu+=s->uv[(2*y+dy)*s->uv_stride+(x+dx)*2];
                    sumv+=s->uv[(2*y+dy)*s->uv_stride+(x+dx)*2+1];
                } else {
                    int yy,uu,vv;
                    rgb(s->y+(2*y+dy)*s->y_stride+(x+dx)*3,s->matrix709,&yy,&uu,&vv);
                    sumu+=uu; sumv+=vv;
                }
            }
            u=clip((sumu+2)/4); v=clip((sumv+2)/4);
        }
        duv[y*ds+x]=(uint8_t)u; duv[y*ds+x+1]=(uint8_t)v;
    }
    return 0;
}
