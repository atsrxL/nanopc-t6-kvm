/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "pixels.h"
#include "wire.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <stdint.h>

int main(int argc,char **argv) {
    if(argc==2 && !strcmp(argv[1],"--wire")) {
        const uint8_t au[]={0,0,0,1,0x67,0x11,0,0,1,0x68,0x22,0,0,1,0x65,0x33};
        assert(t6_nal_mask(au,sizeof(au))==((1U<<7)|(1U<<8)|(1U<<5)));
        return t6_write_frame(1,1,3,1920,1080,0x0102030405060708ULL,9,10000,au,sizeof(au))<0;
    }
    uint8_t y[]={16,20,0xff,0xff,30,40,0xff,0xff};
    uint8_t uv[]={80,90,0xff,0xff,100,110,0xff,0xff};
    uint8_t out[48];
    struct t6_image s={T6_NV12,2,2,y,uv,sizeof(y),4,4,4,0};
    assert(t6_to_nv12(&s,out,sizeof(out),4,4)==0);
    assert(out[0]==16 && out[1]==20 && out[4]==30 && out[5]==40);
    assert(out[16]==80 && out[17]==90 && out[18]==128);
    s.format=T6_NV16; s.uv_size=8;
    assert(t6_to_nv12(&s,out,sizeof(out),4,4)==0);
    assert(out[16]==90 && out[17]==100);
    s.format=T6_NV24;
    uint8_t uv24[]={10,20,30,40,50,60,70,80};
    s.uv=uv24;
    assert(t6_to_nv12(&s,out,sizeof(out),4,4)==0);
    assert(out[16]==40 && out[17]==50);
    s.uv_size=7;
    assert(t6_to_nv12(&s,out,sizeof(out),4,4)<0);
    s.uv_size=8; s.y_stride=1;
    assert(t6_to_nv12(&s,out,sizeof(out),4,4)<0);
    uint8_t bgr[12]={0};
    s=(struct t6_image){T6_BGR24,2,2,bgr,NULL,sizeof(bgr),0,6,0,1};
    assert(t6_to_nv12(&s,out,sizeof(out),4,4)==0);
    assert(out[0]==16 && out[16]==128 && out[17]==128);
    memset(bgr,255,sizeof(bgr));
    assert(t6_to_nv12(&s,out,sizeof(out),4,4)==0);
    assert(out[0]>=234 && out[0]<=236);
    assert(t6_to_nv12(&s,out,4,4,4)<0);
    s.width=3; assert(t6_to_nv12(&s,out,sizeof(out),4,4)<0);
    puts("PASS: pixel strides, chroma downsampling, RGB endpoints, bounds; wire emission available");
    return 0;
}
