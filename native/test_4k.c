/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "pixels.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
int main(void) {
    const unsigned w=3840,h=2160,ds=3840,dh=2176;
    size_t cap=(size_t)ds*dh*3/2,n=(size_t)w*h*3;
    unsigned char *src=malloc(n),*dst=malloc(cap+32);
    assert(src&&dst); memset(src,255,n);memset(dst,0xa5,cap+32);
    struct t6_image im={T6_BGR24,w,h,src,NULL,n,0,w*3,0,1};
    assert(t6_to_nv12(&im,dst,cap,ds,dh)==0);
    assert(dst[0]==235 && dst[(h-1)*ds+w-1]==235);
    assert(dst[h*ds]==16 && dst[ds*dh]==127);
    for(size_t i=cap;i<cap+32;i++)assert(dst[i]==0xa5);
    im.y_size=n-1;assert(t6_to_nv12(&im,dst,cap,ds,dh)<0);
    memset(src,90,n);im=(struct t6_image){T6_NV12,w,h,src,src+(size_t)w*h,(size_t)w*h,(size_t)w*h/2,w,w,1};
    assert(t6_to_nv12(&im,dst,cap,ds,dh)==0);
    assert(dst[0]==90 && dst[ds*dh]==90 && dst[ds*dh+(h/2-1)*ds+w-1]==90);
    free(src);free(dst);puts("PASS: 4K BGR/NV12 conversion, padding, bounds");return 0;
}
