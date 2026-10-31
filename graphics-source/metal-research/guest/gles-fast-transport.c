/* Exercise the same bounded RPC contract that the TCG helper exposes to the guest. */
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "gfx/gfx.h"
#include "protocol.h"
#ifndef IOSGPU_RPC_TEST
static int64_t iosvm_gpu_rpc(uint32_t op,uint32_t ctx,const void *request,uint32_t size,void *reply,uint32_t capacity,uint32_t *written) {
 /* Resolve normal guest VM faults before the emulator copies across the boundary.
  * Newly malloc'd readback pages may have no physical backing until first write. */
 if(size){const volatile unsigned char *p=request;for(uint32_t i=0;i<size;i+=4096)(void)p[i];(void)p[size-1];}
 if(capacity){volatile unsigned char *p=reply;for(uint32_t i=0;i<capacity;i+=4096){unsigned char v=p[i];p[i]=v;}unsigned char v=p[capacity-1];p[capacity-1]=v;}
 register uint64_t a __asm__("x0")=op,b __asm__("x1")=ctx,c __asm__("x2")=(uintptr_t)request,
 d __asm__("x3")=size,e __asm__("x4")=(uintptr_t)reply,f __asm__("x5")=capacity,magic __asm__("x16")=IOSGPU_MAGIC;
 __asm__ __volatile__("hlt #0x4f53" : "+r"(a),"+r"(b) : "r"(c),"r"(d),"r"(e),"r"(f),"r"(magic) : "memory","cc");
 *written=(uint32_t)b;return (int64_t)a;
}
#endif
static int call(uint32_t op,uint32_t context,const void *p,uint32_t n,void *reply,uint32_t capacity){
 uint32_t written=0;int64_t r=iosvm_gpu_rpc(op,context,p,n,reply,capacity,&written);
 if(r<0)return (int)-r;
 if((op==IOSGPU_READ||op==IOSGPU_RESOURCE_DOWNLOAD)&&written!=capacity)return EIO;
 return 0;
}
static int write_stream(void *arg,const void *p,size_t n){return n>IOSGPU_MAX_BYTES?EINVAL:call(IOSGPU_WRITE,(uint32_t)(uintptr_t)arg,p,(uint32_t)n,NULL,0);}
static int read_stream(void *arg,void *p,size_t n){return n>IOSGPU_MAX_BYTES?EINVAL:call(IOSGPU_READ,(uint32_t)(uintptr_t)arg,NULL,0,p,(uint32_t)n);}
static void close_stream(void *arg){(void)call(IOSGPU_CLOSE,(uint32_t)(uintptr_t)arg,NULL,0,NULL,0);}
static int create(void *arg,uint32_t w,uint32_t h,uint32_t *id){
 uint32_t size[2]={w,h},written=0;int64_t r=iosvm_gpu_rpc(IOSGPU_RESOURCE_CREATE,(uint32_t)(uintptr_t)arg,size,8,NULL,0,&written);
 if(r<0)return (int)-r;*id=(uint32_t)r;return 0;
}
static int unref(void *arg,uint32_t id){return call(IOSGPU_RESOURCE_UNREF,(uint32_t)(uintptr_t)arg,&id,4,NULL,0);}
static int xfer(void *arg,uint32_t id,uint32_t x,uint32_t y,uint32_t w,uint32_t h,void *pixels,uint32_t stride,int upload){
 uint64_t bytes=(uint64_t)(h?h-1:0)*stride+(uint64_t)w*4;
 if(!h||bytes>IOSGPU_MAX_BYTES-24)return EINVAL;
 uint64_t row=(uint64_t)w*4,tight=row*h;
 if(!w||row>stride||tight>IOSGPU_MAX_BYTES-24)return EINVAL;
 uint32_t a[6]={id,x,y,w,h,(uint32_t)row};int code;
 /* The helper validates the complete destination and publishes a successful
  * bounded reply only. Packed destinations need no guest-side staging copy.
  * Keep scratch storage for padded rows so adjacent live pixels stay intact. */
 if(!upload&&stride==row)return call(IOSGPU_RESOURCE_DOWNLOAD,(uint32_t)(uintptr_t)arg,a,24,pixels,(uint32_t)tight);
 /* Wire transfers are tight. Copy only the requested pixels: a padded/partial
  * destination contains other live pixels between rows, never reply padding. */
 uint8_t *p=malloc((size_t)tight+24);if(!p)return ENOMEM;
 if(upload){memcpy(p,a,24);for(uint32_t i=0;i<h;i++)memcpy(p+24+(size_t)i*row,(const uint8_t *)pixels+(size_t)i*stride,(size_t)row);
  code=call(IOSGPU_RESOURCE_UPLOAD,(uint32_t)(uintptr_t)arg,p,(uint32_t)tight+24,NULL,0);
 }else{code=call(IOSGPU_RESOURCE_DOWNLOAD,(uint32_t)(uintptr_t)arg,a,24,p,(uint32_t)tight);
  if(!code)for(uint32_t i=0;i<h;i++)memcpy((uint8_t *)pixels+(size_t)i*stride,p+(size_t)i*row,(size_t)row);
 }
 free(p);
 return code;
}
static int upload(void *a,uint32_t r,uint32_t x,uint32_t y,uint32_t w,uint32_t h,const void *p,uint32_t s){return xfer(a,r,x,y,w,h,(void *)p,s,1);}
static int download(void *a,uint32_t r,uint32_t x,uint32_t y,uint32_t w,uint32_t h,void *p,uint32_t s){return xfer(a,r,x,y,w,h,p,s,0);}
int gfx_test_transport(struct gfx_transport *t){
 uint32_t written=0;int64_t r=iosvm_gpu_rpc(IOSGPU_OPEN,0,NULL,0,NULL,0,&written);
 if(r<=0)return EIO;
 *t=(struct gfx_transport){.arg=(void *)(uintptr_t)r,.write=write_stream,.read=read_stream,.close=close_stream,
  .res_create=create,.res_unref=unref,.res_upload=upload,.res_download=download,.flags_sent=0};return 0;
}
