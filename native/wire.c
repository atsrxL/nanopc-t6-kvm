/* SPDX-License-Identifier: GPL-3.0-or-later */
#define _POSIX_C_SOURCE 200809L
#include "wire.h"
#include <unistd.h>
#include <errno.h>
#include <string.h>
#include <time.h>
static void be(uint8_t *out,uint64_t n,unsigned bytes) {
    for(unsigned i=0;i<bytes;i++) { out[bytes-1-i]=(uint8_t)n; n>>=8; }
}
static int all(int fd,const void *buf,size_t n) {
    const uint8_t *p=buf;
    while(n) {
        ssize_t wrote=write(fd,p,n);
        if(wrote<0 && errno==EINTR) continue;
        if(wrote<=0) return -1;
        n-=(size_t)wrote; p+=wrote;
    }
    return 0;
}
int t6_write_frame(int fd,unsigned kind,unsigned flags,unsigned w,unsigned h,
                   uint64_t epoch,uint64_t seq,uint64_t pts,const void *data,size_t size) {
    if(!size||size>T6_MAX_AU) { errno=EMSGSIZE; return -1; }
    uint8_t hdr[48]={ 'T','6','A','U',1,0,0,48 };
    hdr[5]=(uint8_t)kind;
    be(hdr+8,size,4); be(hdr+12,flags,4); be(hdr+16,w,4); be(hdr+20,h,4);
    be(hdr+24,epoch,8); be(hdr+32,seq,8); be(hdr+40,pts,8);
    return all(fd,hdr,sizeof(hdr)) || all(fd,data,size) ? -1 : 0;
}
int t6_write_status(int fd,const char *json) {
    return t6_write_frame(fd,2,0,0,0,0,0,0,json,strlen(json));
}
unsigned t6_nal_mask(const uint8_t *d,size_t n) {
    unsigned mask=0;
    for(size_t i=0;i+3<n;i++) {
        if(!d[i]&&!d[i+1]&&d[i+2]==1) {
            mask |= 1U<<(d[i+3]&31); i+=3;
        }
    }
    return mask;
}
uint64_t t6_now_us(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC,&ts);
    return (uint64_t)ts.tv_sec*1000000+(uint64_t)ts.tv_nsec/1000;
}
