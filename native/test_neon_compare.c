/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "pixels.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
int scalar_to_nv12(const struct t6_image *,uint8_t *,size_t,size_t,size_t);
int main(void){
 uint8_t src[64*3*8],a[80*12],b[80*12];
 for(unsigned k=0;k<1000;k++){
  for(unsigned i=0;i<sizeof(src);i++)src[i]=rand();
  struct t6_image im={T6_BGR24,64,8,src,NULL,sizeof(src),0,192,0,k%2};
  assert(t6_to_nv12(&im,a,sizeof(a),80,8)==0);
  assert(scalar_to_nv12(&im,b,sizeof(b),80,8)==0);
  assert(memcmp(a,b,sizeof(a))==0);
 }
 puts("PASS: 1000 randomized NEON/scalar comparisons, BT601/709, padded stride");
}
