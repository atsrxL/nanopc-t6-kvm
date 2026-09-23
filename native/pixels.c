/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "pixels.h"
#include <string.h>
#include <errno.h>

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
    for(unsigned y=0;y<h;y++) {
        if(s->format!=T6_BGR24) memcpy(dst+y*ds,s->y+y*s->y_stride,w);
        else for(unsigned x=0;x<w;x++) {
            int yy,u,v; rgb(s->y+y*s->y_stride+x*3,s->matrix709,&yy,&u,&v);
            dst[y*ds+x]=clip(yy);
        }
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
