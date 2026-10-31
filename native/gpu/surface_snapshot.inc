/* Included by renderer.c: every entry shares the renderer ownership mutex.
 * SPDX-License-Identifier: AGPL-3.0-or-later */
#include <sys/random.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#define SNAPSHOT_SPARE (32u*1024u*1024u)
static struct iosgpu_surface_registry surface_registry;
static struct iosgpu_snapshot_copy *surface_copy;
static void *surface_parent;
static int surface_failed;
static uint64_t surface_published,surface_resolved,surface_dropped;
static __typeof__(&stream_renderer_platform_create_shared_egl_context) surface_parent_create;
static __typeof__(&stream_renderer_platform_destroy_shared_egl_context) surface_parent_destroy;
static __typeof__(&stream_renderer_import_resource) surface_import;
static int (*surface_register)(AHardwareBuffer *),(*surface_unregister)(AHardwareBuffer *);
static PFNEGLGETNATIVECLIENTBUFFERANDROIDPROC surface_client;
static size_t snapshot_reserved_locked(void){return surface_copy?SNAPSHOT_SPARE:0;}
static int snapshot_ready_locked(void){
 if(surface_failed)return -EIO;if(surface_copy)return 0;
 int result=initialize();if(result)return result;
 if(memory_used>MEMORY_BUDGET-SNAPSHOT_SPARE)return -ENOSPC;
 surface_parent_create=dlsym(renderer_library,"stream_renderer_platform_create_shared_egl_context");
 surface_parent_destroy=dlsym(renderer_library,"stream_renderer_platform_destroy_shared_egl_context");
 surface_import=dlsym(renderer_library,"stream_renderer_import_resource");
 void *egl=dlopen("libEGL.so",RTLD_NOW|RTLD_LOCAL);
 if(!egl||!surface_parent_create||!surface_parent_destroy||!surface_import)return -ENOSYS;
 surface_register=dlsym(egl,"ios_egl_ahb_register");surface_unregister=dlsym(egl,"ios_egl_ahb_unregister");
 surface_client=(void *)eglGetProcAddress("eglGetNativeClientBufferANDROID");
 if(!surface_register||!surface_unregister||!surface_client)return -ENOSYS;
 surface_parent=surface_parent_create();if(!surface_parent)return -ENODEV;
 surface_copy=iosgpu_snapshot_copy_create(surface_parent);
 if(!surface_copy){surface_parent_destroy(surface_parent);surface_parent=NULL;return -ENODEV;}return 0;
}
int iosgpu_backend_snapshot_ready(void){pthread_mutex_lock(&mutex);int result=snapshot_ready_locked();pthread_mutex_unlock(&mutex);return result;}
static struct resource *snapshot_resource_locked(uint32_t id){
 for(unsigned n=0;n<RESOURCES;n++)if(resources[n].id==id&&resources[n].snapshot)return &resources[n];return NULL;
}
static int snapshot_drop_locked(struct resource *r){
 if(r->snapshot==1){api.resource_unref(r->id);r->snapshot=2;if(surface_unregister(r->target.buffer)){surface_failed=1;return -EIO;}}
 if(!iosgpu_snapshot_target_destroy(surface_copy,&r->target)){surface_failed=1;return -EIO;}
 memory_used-=r->bytes;memset(r,0,sizeof(*r));surface_dropped++;return 0;
}
static int64_t snapshot_unref_locked(uint32_t context,uint32_t resource){
 uint32_t drop=0;int result=iosgpu_surface_unref(&surface_registry,context,resource,&drop);if(result)return result;
 if(drop){struct resource *r=snapshot_resource_locked(drop);if(!r){surface_failed=1;return -EIO;}return snapshot_drop_locked(r);}return 0;
}
static void snapshot_context_closed_locked(uint32_t context){
 uint32_t drops[IOSGPU_SNAPSHOT_SLOTS];size_t count=0;
 if(iosgpu_surface_consumer_closed(&surface_registry,context,drops,IOSGPU_SNAPSHOT_SLOTS,&count)){surface_failed=1;return;}
 for(size_t n=0;n<count;n++){struct resource *r=snapshot_resource_locked(drops[n]);if(r)(void)snapshot_drop_locked(r);else surface_failed=1;}
}
static size_t snapshot_credit_locked(uint32_t owner,uint32_t surface){
 for(unsigned n=0;n<IOSGPU_SNAPSHOT_SLOTS;n++){
  struct iosgpu_surface_record *s=&surface_registry.records[n];if(!s->resource||!s->current||s->owner!=owner||s->meta.surface!=surface)continue;
  for(unsigned k=0;k<IOSGPU_SNAPSHOT_CONSUMERS;k++)if(s->consumers[k].count)return 0;
  struct resource *r=snapshot_resource_locked(s->resource);return r?r->bytes:0;
 }return 0;
}
static int snapshot_capability_locked(uint32_t owner,struct iosgpu_surface_meta *meta){
 /* The public token names the live IOSurface, while resource IDs continue to
  * name immutable generations. A metadata read may precede a later publish;
  * resolving that stable token must atomically acquire the latest target. */
 for(unsigned n=0;n<IOSGPU_SNAPSHOT_SLOTS;n++){
  struct iosgpu_surface_record *s=&surface_registry.records[n];
  if(s->resource&&s->current&&s->owner==owner&&s->meta.surface==meta->surface&&s->meta.width==meta->width&&s->meta.height==meta->height){memcpy(meta->capability,s->meta.capability,sizeof(meta->capability));return 0;}
 }
 for(unsigned attempt=0;attempt<8;attempt++){
  size_t at=0;while(at<sizeof(meta->capability)){ssize_t n=getrandom((char *)meta->capability+at,sizeof(meta->capability)-at,0);if(n<0&&errno==EINTR)continue;if(n<=0)return -EIO;at+=(size_t)n;}
  if(!meta->capability[0]&&!meta->capability[1])continue;
  unsigned n=0;for(;n<IOSGPU_SNAPSHOT_SLOTS;n++){struct iosgpu_surface_record *s=&surface_registry.records[n];if(s->resource&&s->meta.capability[0]==meta->capability[0]&&s->meta.capability[1]==meta->capability[1])break;}
  if(n==IOSGPU_SNAPSHOT_SLOTS)return 0;
 }return -EIO;
}
static int snapshot_publish_locked(uint32_t owner,void *metal,const struct iosgpu_frame_api *frame,
 const struct iosgpu_surface_request *request,void *output,uint32_t *written){
 uint32_t id=(uint32_t)request->argument[1],w=(uint32_t)request->argument[2],h=(uint32_t)request->argument[3];
 int result=iosgpu_surface_preflight(&surface_registry,owner,id,w,h);if(result)return result;
 if(!surface_copy||surface_failed)return -EIO;
 struct resource *slot=NULL;for(unsigned n=0;n<RESOURCES;n++)if(!resources[n].id){slot=&resources[n];break;}
 if(!slot||next_resource>=INT32_MAX)return -ENOSPC;
 size_t credit=snapshot_credit_locked(owner,id),estimate=(size_t)w*h*4,limit=MEMORY_BUDGET-SNAPSHOT_SPARE;
 if(memory_used<credit||memory_used-credit>limit||estimate>limit-(memory_used-credit))return -ENOSPC;
 struct iosgpu_surface_meta meta={.magic=IOSGPU_SURFACE_MAGIC,.version=1,.surface=id,.width=w,.height=h};
 result=snapshot_capability_locked(owner,&meta);if(result)return result;
 struct iosgpu_snapshot_target target={0};result=iosgpu_snapshot_target_create(surface_copy,w,h,&target);
 if(result){if(result==-EIO){surface_failed=1;memory_used+=SNAPSHOT_SPARE;}return result;}
 AHardwareBuffer_Desc desc;AHardwareBuffer_describe(target.buffer,&desc);size_t bytes=(size_t)desc.stride*h*4;
 if(bytes>SNAPSHOT_SPARE||bytes>limit-(memory_used-credit)){
  if(!iosgpu_snapshot_target_destroy(surface_copy,&target)){surface_failed=1;memory_used+=bytes;}return -ENOSPC;
 }
 uint32_t resource=next_resource++;
 struct create create={resource,2,67,(1u<<1)|(1u<<3),w,h,1,1,0,0,0};
 result=api.resource_create(&create,NULL,0);
 if(result){if(!iosgpu_snapshot_target_destroy(surface_copy,&target)){surface_failed=1;memory_used+=bytes;}return -EIO;}
 *slot=(struct resource){.id=resource,.w=w,.h=h,.bytes=bytes,.snapshot=2,.target=target};memory_used+=bytes;
 if(surface_register(target.buffer)){api.resource_unref(resource);(void)snapshot_drop_locked(slot);return -EIO;}
 slot->snapshot=1;
 struct stream_renderer_handle handle={.os_handle=(int64_t)(uintptr_t)surface_client(target.buffer),.handle_type=STREAM_HANDLE_TYPE_PLATFORM_EGL_NATIVE_PIXMAP};
 struct stream_renderer_import_data data={.flags=STREAM_RENDERER_IMPORT_FLAG_RESOURCE_EXISTS};
 if(surface_import(resource,&handle,&data)){(void)snapshot_drop_locked(slot);return -EIO;}
 result=iosgpu_snapshot_copy(surface_copy,metal,request->argument[0],target.texture,w,h,frame);
 if(result){(void)snapshot_drop_locked(slot);return result;}
 uint32_t drop=0;result=iosgpu_surface_publish(&surface_registry,owner,&meta,resource,&drop);
 if(result){(void)snapshot_drop_locked(slot);return result;}
 if(drop){struct resource *old=snapshot_resource_locked(drop);if(!old||snapshot_drop_locked(old)){surface_failed=1;/* committed immutable mapping remains valid */}}
 memcpy(output,&meta,sizeof(meta));*written=sizeof(meta);surface_published++;
 if(surface_published<=3||surface_published%60==0){struct timespec at;clock_gettime(CLOCK_MONOTONIC,&at);fprintf(stderr,"IOSGPU_SNAPSHOT_PUBLISH count=%llu width=%u height=%u host_us=%llu cpu_pixel_uploads=0\n",(unsigned long long)surface_published,w,h,(unsigned long long)at.tv_sec*1000000+(unsigned long long)at.tv_nsec/1000);}
 return 0;
}
int64_t iosgpu_backend_surface_call(uint32_t context,void *metal,const struct iosgpu_frame_api *frame,
 const struct iosgpu_surface_request *request,void *output,uint32_t capacity,uint32_t *written){
 if(!written)return -EINVAL;*written=0;
 if(!request||request->magic!=IOSGPU_SURFACE_MAGIC||request->version!=1||request->reserved||request->argument[5])return -EINVAL;
 if(request->command==IOSGPU_SURFACE_PUBLISH){
  if(!metal||!frame||context<0x10000||capacity!=sizeof(struct iosgpu_surface_meta)||!output||!request->argument[0]||!request->argument[1]||request->argument[1]>UINT32_MAX||request->argument[2]>UINT32_MAX||request->argument[3]>UINT32_MAX||request->argument[4])return -EINVAL;
 }else if(request->command==IOSGPU_SURFACE_RESOLVE||request->command==IOSGPU_SURFACE_RETIRE){
  if(capacity||request->argument[2]>UINT32_MAX||request->argument[3]>UINT32_MAX||request->argument[4]>UINT32_MAX)return -EINVAL;
  if(request->command==IOSGPU_SURFACE_RESOLVE){if(metal||frame||!context||context>=0x10000)return -EINVAL;}
  else if(!metal||context<0x10000)return -EINVAL;
 }else return -EINVAL;
 pthread_mutex_lock(&mutex);int64_t result;
 if(request->command==IOSGPU_SURFACE_PUBLISH)result=snapshot_publish_locked(context,metal,frame,request,output,written);
 else{
  struct iosgpu_surface_meta meta={.magic=IOSGPU_SURFACE_MAGIC,.version=1,.surface=(uint32_t)request->argument[2],.width=(uint32_t)request->argument[3],.height=(uint32_t)request->argument[4],.capability={request->argument[0],request->argument[1]}};
  if(request->command==IOSGPU_SURFACE_RESOLVE){
   uint32_t resource=0;
   if(!find_context(context))result=-ENOENT;
   else if((result=iosgpu_surface_resolve(&surface_registry,context,&meta,&resource))==0){api.ctx_attach((int)context,(int)resource);result=resource;surface_resolved++;
    if(surface_resolved<=3||surface_resolved%60==0)fprintf(stderr,"IOSGPU_SNAPSHOT_RESOLVE count=%llu cpu_pixel_uploads=0\n",(unsigned long long)surface_resolved);}
  }else{
   uint32_t drop=0;result=iosgpu_surface_retire(&surface_registry,context,&meta,&drop);
   if(!result&&drop){struct resource *r=snapshot_resource_locked(drop);if(!r){surface_failed=1;result=-EIO;}else result=snapshot_drop_locked(r);}
  }
 }
 pthread_mutex_unlock(&mutex);return result;
}
void iosgpu_backend_snapshot_producer_closed(void){
 pthread_mutex_lock(&mutex);if(surface_copy&&!iosgpu_snapshot_copy_clear_imports(surface_copy))surface_failed=1;pthread_mutex_unlock(&mutex);
}
void iosgpu_backend_snapshot_stats(uint64_t values[8]){
 if(!values)return;pthread_mutex_lock(&mutex);uint64_t copied[4]={0};iosgpu_snapshot_copy_stats(surface_copy,copied);uint64_t live=0;
 for(unsigned n=0;n<RESOURCES;n++)if(resources[n].id&&resources[n].snapshot)live++;
 uint64_t stats[]={surface_published,surface_resolved,surface_dropped,live,memory_used,copied[0],copied[1],copied[2]};memcpy(values,stats,sizeof(stats));pthread_mutex_unlock(&mutex);
}
