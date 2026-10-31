/* App-local gfxstream host transport. MIT upstream API pattern from HackiOS host_test/host.c;
 * new bounded ownership/lifetime implementation, SPDX-License-Identifier: AGPL-3.0-or-later. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <time.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "protocol.h"
#include "renderer.h"
#include "snapshot_backend.h"
#include "surface_registry.h"
#include "gfxstream/virtio-gpu-gfxstream-renderer-unstable.h"
struct iov { void *base;size_t len; };
struct box { uint32_t x,y,z,w,h,d; };
struct create { uint32_t handle,target,format,bind,width,height,depth,array_size,last_level,nr_samples,flags; };
struct param { uint64_t key,value; };
struct fence { uint32_t flags;uint64_t id;uint32_t context;uint8_t ring; };
static struct {
 int (*init)(struct param *,uint64_t);
 int (*context_create)(uint32_t,uint32_t,const char *,uint32_t);
 void (*context_destroy)(uint32_t);
 int (*resource_create)(struct create *,struct iov *,uint32_t);
 void (*resource_unref)(uint32_t);
 int (*attach_iov)(int,struct iov *,int);
 void (*ctx_attach)(int,int);
 int (*write)(uint32_t,uint32_t,int,uint32_t,uint32_t,struct box *,uint64_t,struct iov *,unsigned);
 int (*read)(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,struct box *,uint64_t,struct iov *,int);
} api;
#define PIPE_BYTES (1u<<20)
#define CONTEXTS 16
#define RESOURCES 1024
#define MEMORY_BUDGET (256u*1024u*1024u)
struct context { uint32_t id,pipe;uint8_t *memory; };
struct resource { uint32_t id,context,w,h;size_t bytes;uint8_t *memory;int snapshot;struct iosgpu_snapshot_target target; };
static struct context contexts[CONTEXTS];
static struct resource resources[RESOURCES];
static uint32_t next_context=1,next_pipe=0x10000,next_resource=0x30000;
static size_t memory_used;
static int initialized;
static void *renderer_library;
static int snapshot_drop_locked(struct resource *);
static int64_t snapshot_unref_locked(uint32_t,uint32_t);
static void snapshot_context_closed_locked(uint32_t);
static size_t snapshot_reserved_locked(void);
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static void fence_callback(void *cookie,struct fence *f){(void)cookie;(void)f;}
static int initialize(void) {
 if(initialized)return initialized>0?0:-EIO;
 initialized=-1;
 Dl_info info;char path[4096];
 if(!dladdr((void *)iosgpu_backend_call,&info)||!info.dli_fname)return -EIO;
 const char *slash=strrchr(info.dli_fname,'/');
 if(!slash||(size_t)(slash-info.dli_fname)>sizeof(path)-64)return -ENAMETOOLONG;
 snprintf(path,sizeof(path),"%.*s/libgfxstream_backend.so",(int)(slash-info.dli_fname),info.dli_fname);
 void *library=dlopen(path,RTLD_NOW|RTLD_LOCAL);
 if(!library){fprintf(stderr,"iosgpu: %s\n",dlerror());return -ENOENT;}
#define LOAD(member,name) do { *(void **)(&api.member)=dlsym(library,name);if(!api.member)return -ENOTSUP; } while(0)
 LOAD(init,"stream_renderer_init");LOAD(context_create,"stream_renderer_context_create");
 LOAD(context_destroy,"stream_renderer_context_destroy");LOAD(resource_create,"stream_renderer_resource_create");
 LOAD(resource_unref,"stream_renderer_resource_unref");LOAD(attach_iov,"stream_renderer_resource_attach_iov");
 LOAD(ctx_attach,"stream_renderer_ctx_attach_resource");LOAD(write,"stream_renderer_transfer_write_iov");
 LOAD(read,"stream_renderer_transfer_read_iov");
#undef LOAD
 setenv("ANDROID_EMU_RENDERER","host",1);
 struct param params[]={{1,0},{2,25},{3,(uint64_t)(uintptr_t)fence_callback},{4,64},{5,64}};
 if(api.init(params,5))return -EIO;
 renderer_library=library;
 initialized=1;return 0;
}
static struct context *find_context(uint32_t id){
 for(unsigned i=0;i<CONTEXTS;i++)if(contexts[i].id==id&&id)return &contexts[i];return NULL;
}
static struct resource *find_resource(uint32_t context,uint32_t id){
 for(unsigned i=0;i<RESOURCES;i++)if(resources[i].id==id&&id&&resources[i].context==context)return &resources[i];return NULL;
}
static int transfer(struct context *c,int write,uint32_t n){
 struct box b={0,0,0,n,1,1};struct iov v={c->memory,PIPE_BYTES};
 int code=write?api.write(c->pipe,c->id,0,0,0,&b,0,&v,1):api.read(c->pipe,c->id,0,0,0,&b,0,&v,1);
 return code?-EIO:0;
}
static void drop_resource(struct resource *r){
 if(r->snapshot){(void)snapshot_drop_locked(r);return;}
 api.resource_unref(r->id);memory_used-=r->bytes;free(r->memory);memset(r,0,sizeof(*r));
}
static int64_t open_context(void){
 int code=initialize();if(code)return code;
 struct context *c=NULL;
 for(unsigned i=0;i<CONTEXTS;i++)if(!contexts[i].id){c=&contexts[i];break;}
 if(!c||next_context>=0x10000||next_pipe>=0x30000)return -ENOSPC;
 uint8_t *memory=calloc(1,PIPE_BYTES);if(!memory)return -ENOMEM;
 uint32_t id=next_context++,pipe=next_pipe++;
 if(api.context_create(id,6,"iosgpu",8)){free(memory);return -EIO;}
 struct create create={pipe,0,64,1u<<17,PIPE_BYTES,1,1,1,0,0,0};
 if(api.resource_create(&create,NULL,0)){api.context_destroy(id);free(memory);return -EIO;}
 struct iov v={memory,PIPE_BYTES};
 if(api.attach_iov((int)pipe,&v,1)){api.resource_unref(pipe);api.context_destroy(id);free(memory);return -EIO;}
 api.ctx_attach((int)id,(int)pipe);*c=(struct context){id,pipe,memory};
 static const char service[]="pipe:opengles";memcpy(memory,service,sizeof(service));
 if(transfer(c,1,sizeof(service))){api.resource_unref(pipe);api.context_destroy(id);free(memory);memset(c,0,sizeof(*c));return -EIO;}
 return id;
}
static int64_t create_resource(struct context *c,uint32_t w,uint32_t h){
 uint64_t n=(uint64_t)w*h*4;
 if(!w||!h||w>8192||h>8192||n>IOSGPU_MAX_BYTES)return -EINVAL;
 size_t limit=MEMORY_BUDGET-snapshot_reserved_locked();
 if(memory_used>limit||n>limit-memory_used||next_resource>=INT32_MAX)return -ENOSPC;
 struct resource *r=NULL;
 for(unsigned i=0;i<RESOURCES;i++)if(!resources[i].id){r=&resources[i];break;}
 if(!r)return -ENOSPC;
 uint8_t *memory=calloc(1,(size_t)n);if(!memory)return -ENOMEM;
 uint32_t id=next_resource++;
 struct create create={id,2,1,(1u<<1)|(1u<<3),w,h,1,1,0,0,0};
 if(api.resource_create(&create,NULL,0)){free(memory);return -EIO;}
 struct iov v={memory,(size_t)n};
 if(api.attach_iov((int)id,&v,1)){api.resource_unref(id);free(memory);return -EIO;}
 api.ctx_attach((int)c->id,(int)id);
 *r=(struct resource){.id=id,.context=c->id,.w=w,.h=h,.bytes=(size_t)n,.memory=memory};memory_used+=(size_t)n;return id;
}
static int64_t dispatch(uint32_t op,uint32_t context,const uint8_t *request,uint32_t size,
 uint8_t *reply,uint32_t capacity,uint32_t *written){
 if(op==IOSGPU_OPEN)return context||size||capacity?-EINVAL:open_context();
 struct context *c=find_context(context);if(!c)return -ENOENT;
 if(op==IOSGPU_CLOSE){
  if(size||capacity)return -EINVAL;
  for(unsigned i=0;i<RESOURCES;i++)if(resources[i].id&&resources[i].context==context)drop_resource(&resources[i]);
  api.resource_unref(c->pipe);api.context_destroy(c->id);snapshot_context_closed_locked(c->id);free(c->memory);memset(c,0,sizeof(*c));return 0;
 }
 if(op==IOSGPU_WRITE||op==IOSGPU_READ){
  if((op==IOSGPU_WRITE&&(!size||capacity))||(op==IOSGPU_READ&&(size||!capacity)))return -EINVAL;
  uint32_t n=op==IOSGPU_WRITE?size:capacity,at=0;
  while(at<n){uint32_t k=n-at>PIPE_BYTES?PIPE_BYTES:n-at;
   if(op==IOSGPU_WRITE)memcpy(c->memory,request+at,k);
   int code=transfer(c,op==IOSGPU_WRITE,k);if(code)return code;
   if(op==IOSGPU_READ)memcpy(reply+at,c->memory,k);at+=k;
  }
  if(op==IOSGPU_READ)*written=n;return 0;
 }
 if(op==IOSGPU_RESOURCE_CREATE){
  if(size!=8||capacity)return -EINVAL;
  uint32_t dims[2];memcpy(dims,request,8);return create_resource(c,dims[0],dims[1]);
 }
 if(op==IOSGPU_RESOURCE_UNREF){
  if(size!=4||capacity)return -EINVAL;uint32_t id;memcpy(&id,request,4);
  for(unsigned n=0;n<RESOURCES;n++)if(resources[n].id==id&&resources[n].snapshot)return snapshot_unref_locked(context,id);
  struct resource *r=find_resource(context,id);if(!r)return -ENOENT;drop_resource(r);return 0;
 }
 if(op==IOSGPU_RESOURCE_UPLOAD||op==IOSGPU_RESOURCE_DOWNLOAD){
  if(size<24)return -EINVAL;
  uint32_t a[6];memcpy(a,request,24);
  struct resource *r=find_resource(context,a[0]);if(!r)return -ENOENT;
  int upload=op==IOSGPU_RESOURCE_UPLOAD;
  if((upload&&capacity)||(!upload&&size!=24))return -EINVAL;
  struct iosgpu_region region;
  if(iosgpu_validate_region(r->w,r->h,a[1],a[2],a[3],a[4],a[5],upload?size-24:capacity,&region))return -EINVAL;
  size_t pitch=(size_t)r->w*4;uint64_t offset=(uint64_t)a[2]*pitch+(uint64_t)a[1]*4;
  struct box b={a[1],a[2],0,a[3],a[4],1};struct iov v={r->memory,r->bytes};
  if(upload)for(uint32_t y=0;y<a[4];y++)memcpy(r->memory+offset+(size_t)y*pitch,request+24+(size_t)y*a[5],region.row_bytes);
  int code=upload?api.write(r->id,c->id,0,0,0,&b,offset,&v,1):api.read(r->id,c->id,0,0,0,&b,offset,&v,1);
  if(code)return -EIO;
  if(!upload){for(uint32_t y=0;y<a[4];y++)memcpy(reply+(size_t)y*a[5],r->memory+offset+(size_t)y*pitch,region.row_bytes);*written=(uint32_t)region.span;}
  return 0;
 }
 return -EINVAL;
}
uint32_t iosgpu_backend_context_count(void){
 uint32_t count=0;for(unsigned i=0;i<CONTEXTS;i++)if(contexts[i].id)count++;return count;
}
int64_t iosgpu_backend_call(uint32_t op,uint32_t context,const void *request,uint32_t size,
 void *reply,uint32_t capacity,uint32_t *written){
 if(!written||size>IOSGPU_MAX_BYTES||capacity>IOSGPU_MAX_BYTES||(size&&!request)||(capacity&&!reply))return -EINVAL;
 *written=0;if(op==IOSGPU_PING)return context||size||capacity?-EINVAL:(int64_t)IOSGPU_REPLY;
 pthread_mutex_lock(&mutex);
 int64_t code=dispatch(op,context,request,size,reply,capacity,written);
 pthread_mutex_unlock(&mutex);return code;
}
#include "surface_snapshot.inc"
