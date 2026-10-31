/* Typed backend selection, only in the expendable worker. AGPL-3.0-or-later */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "renderer.h"
#include "protocol.h"
#include "snapshot_backend.h"
static struct {uint32_t id;void *metal;int shared;} contexts[16];
static uint32_t next_metal=0x10000;
static void *metal_library;
static void *(*metal_open)(uint32_t,const uint8_t *,uint32_t,uint8_t *,uint32_t);
static int64_t (*metal_call)(void *,const uint8_t *,uint32_t,uint8_t *,uint32_t,uint32_t *);
static void (*metal_close)(void *);
static void *(*metal_open_shared)(uint32_t,const uint8_t *,uint32_t,uint8_t *,uint32_t);
static struct iosgpu_frame_api frame_api;
static int load_metal(void){
 if(metal_library)return metal_open&&metal_call&&metal_close?0:-ENOSYS;
 Dl_info info;char path[4096];
 if(!dladdr((void *)iosgpu_route_call,&info)||!info.dli_fname)return -EIO;
 const char *slash=strrchr(info.dli_fname,'/');
 if(!slash||(size_t)(slash-info.dli_fname)>sizeof(path)-sizeof("/libiosgpu_metal.so"))return -EIO;
 snprintf(path,sizeof(path),"%.*s/libiosgpu_metal.so",(int)(slash-info.dli_fname),info.dli_fname);
 metal_library=dlopen(path,RTLD_NOW|RTLD_LOCAL);if(!metal_library)return -ENOSYS;
 *(void **)(&metal_open)=dlsym(metal_library,"iosmetal_open");
 *(void **)(&metal_call)=dlsym(metal_library,"iosmetal_call");
 *(void **)(&metal_close)=dlsym(metal_library,"iosmetal_close");
 *(void **)(&metal_open_shared)=dlsym(metal_library,"iosmetal_open_shared_frames");
 *(void **)(&frame_api.prepare)=dlsym(metal_library,"iosmetal_frame_prepare");
 *(void **)(&frame_api.submit)=dlsym(metal_library,"iosmetal_frame_submit");
 *(void **)(&frame_api.cancel)=dlsym(metal_library,"iosmetal_frame_cancel");
 *(void **)(&frame_api.returned)=dlsym(metal_library,"iosmetal_frame_return");
 *(void **)(&frame_api.collect)=dlsym(metal_library,"iosmetal_frame_collect");
 return metal_open&&metal_call&&metal_close?0:-ENOSYS;
}
int64_t iosgpu_route_call(uint32_t op,uint32_t id,const void *input,uint32_t size,
 void *output,uint32_t capacity,uint32_t *written){
 if(!written)return -EINVAL;*written=0;
 if(size>IOSGPU_MAX_BYTES||capacity>IOSGPU_MAX_BYTES||(size&&!input)||(capacity&&!output))return -EINVAL;
 unsigned count=0;int found=-1,empty=-1;
 for(unsigned i=0;i<16;i++)if(contexts[i].id){count++;if(contexts[i].id==id)found=(int)i;}else if(empty<0)empty=(int)i;
 if(op==IOSGPU_OPEN){
  if(id||capacity)return -EINVAL;
  if(count+iosgpu_backend_context_count()>=16)return -ENOSPC;
  if(!size)return iosgpu_backend_call(op,0,NULL,0,NULL,0,written);
  if(size!=16)return -EINVAL;
  uint32_t fields[4];memcpy(fields,input,sizeof(fields));
  if(fields[0]!=IOSGPU_METAL_OPEN_MAGIC||fields[1]!=1||fields[2]>1||fields[3])return -EINVAL;
  if(empty<0||next_metal==UINT32_MAX)return -ENOSPC;
  int code=load_metal();if(code)return code;
  if(fields[2]){
   if(!metal_open_shared||!frame_api.prepare||!frame_api.submit||!frame_api.cancel||!frame_api.returned||!frame_api.collect)return -ENOSYS;
   code=iosgpu_backend_snapshot_ready();if(code)return code;
  }
  const char *temporary=getenv("TMPDIR");char cache[4096];
  if(!temporary||temporary[0]!='/'||strlen(temporary)>sizeof(cache)-sizeof("/metal-runtime-cache"))return -EINVAL;
  snprintf(cache,sizeof(cache),"%s/metal-runtime-cache",temporary);
  uint8_t error[1024]={0};uint32_t context=next_metal++;
  void *metal=(fields[2]?metal_open_shared:metal_open)(context,(const uint8_t *)cache,(uint32_t)strlen(cache),error,sizeof(error));
  if(!metal){fprintf(stderr,"IOSMETAL_OPEN_FAILED %s\n",error);return !strncmp((const char *)error,"fatal:",6)?-EIO:-ENODEV;}
  contexts[empty].id=context;contexts[empty].metal=metal;contexts[empty].shared=(int)fields[2];return context;
 }
 if(op==IOSGPU_METAL_CALL&&size>=4){
  uint32_t magic;memcpy(&magic,input,4);
  if(magic==IOSGPU_SURFACE_MAGIC){
   if(size!=sizeof(struct iosgpu_surface_request))return -EINVAL;
   struct iosgpu_surface_request request;memcpy(&request,input,sizeof(request));
   if(found>=0){if(!contexts[found].shared)return -ENOTSUP;return iosgpu_backend_surface_call(id,contexts[found].metal,&frame_api,&request,output,capacity,written);}
   return iosgpu_backend_surface_call(id,NULL,NULL,&request,output,capacity,written);
  }
 }
 if(found>=0){
  if(op==IOSGPU_CLOSE){if(size||capacity)return -EINVAL;if(contexts[found].shared)iosgpu_backend_snapshot_producer_closed();metal_close(contexts[found].metal);memset(&contexts[found],0,sizeof(contexts[found]));return 0;}
  if(op!=IOSGPU_METAL_CALL)return -EINVAL;
  return metal_call(contexts[found].metal,input,size,output,capacity,written);
 }
 if(op==IOSGPU_METAL_CALL||id>=0x10000)return -ENOENT;
 return iosgpu_backend_call(op,id,input,size,output,capacity,written);
}
