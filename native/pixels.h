/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef T6_PIXELS_H
#define T6_PIXELS_H
#include <stddef.h>
#include <stdint.h>
enum t6_format { T6_NV12, T6_NV16, T6_NV24, T6_BGR24 };
struct t6_image {
    enum t6_format format;
    unsigned width, height;
    const uint8_t *y, *uv;
    size_t y_size, uv_size, y_stride, uv_stride;
    int matrix709;  /* RGB conversion only; YUV retains matrix/range metadata. */
};
int t6_to_nv12(const struct t6_image *src, uint8_t *dst, size_t capacity,
               size_t stride, size_t vertical_stride);
#endif
