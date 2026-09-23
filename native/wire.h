/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef T6_WIRE_H
#define T6_WIRE_H
#include <stdint.h>
#include <stddef.h>
#define T6_MAX_AU (4U*1024U*1024U)
int t6_write_frame(int fd,unsigned kind,unsigned flags,unsigned w,unsigned h,
                   uint64_t epoch,uint64_t seq,uint64_t pts,const void *data,size_t size);
int t6_write_status(int fd,const char *json);
unsigned t6_nal_mask(const uint8_t *data,size_t size);
uint64_t t6_now_us(void);
#endif
