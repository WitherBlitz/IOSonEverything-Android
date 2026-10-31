/* Snapshot mapping and per-name references. SPDX-License-Identifier: AGPL-3.0-or-later */
#include "surface_registry.h"
#include <errno.h>
#include <string.h>
static int producer(uint32_t id){return id>=0x10000;}
static int consumer(uint32_t id){return id&&id<0x10000;}
static uint32_t references(const struct iosgpu_surface_record *r){
 uint32_t count=0;for(unsigned n=0;n<IOSGPU_SNAPSHOT_CONSUMERS;n++)count+=r->consumers[n].count;return count;
}
static int equal(const struct iosgpu_surface_meta *a,const struct iosgpu_surface_meta *b){
 return a->surface==b->surface&&a->width==b->width&&a->height==b->height&&a->capability[0]==b->capability[0]&&a->capability[1]==b->capability[1];
}
static struct iosgpu_surface_record *current(struct iosgpu_surface_registry *r,const struct iosgpu_surface_meta *meta){
 for(unsigned n=0;n<IOSGPU_SNAPSHOT_SLOTS;n++){struct iosgpu_surface_record *s=&r->records[n];if(s->resource&&s->current&&equal(&s->meta,meta))return s;}return NULL;
}
int iosgpu_surface_preflight(const struct iosgpu_surface_registry *r,uint32_t owner,uint32_t surface,uint32_t width,uint32_t height){
 if(!r||!producer(owner)||!surface||!width||!height||width>8192||height>8192||(uint64_t)width*height>8u*1024u*1024u)return -EINVAL;
 uint32_t active=0,owned=0;const struct iosgpu_surface_record *old=NULL;
 for(unsigned n=0;n<IOSGPU_SNAPSHOT_SLOTS;n++){
  const struct iosgpu_surface_record *s=&r->records[n];if(!s->resource)continue;active++;
  if(s->meta.surface==surface&&s->owner!=owner)return -EACCES;
  if(s->meta.surface==surface&&(s->meta.width!=width||s->meta.height!=height))return -EINVAL;
  if(s->current&&s->owner==owner){owned++;if(s->meta.surface==surface)old=s;}
 }
 if(!old&&owned>=IOSGPU_SNAPSHOT_OWNER_SURFACES)return -ENOSPC;
 // The native allocator has one extra target for an atomic replacement. An
 // old snapshot with no consumer can be retired at commit, yielding no growth.
 uint32_t growth=old&&!references(old)?0:1;
 if(active+growth>IOSGPU_SNAPSHOT_RESIDENT_LIMIT)return -ENOSPC;return 0;
}
int iosgpu_surface_publish(struct iosgpu_surface_registry *r,uint32_t owner,const struct iosgpu_surface_meta *input,uint32_t resource,uint32_t *drop){
 if(!r||!drop||!iosgpu_surface_meta_valid(input)||resource<0x30000)return -EINVAL;
 struct iosgpu_surface_meta meta=*input;
 int result=iosgpu_surface_preflight(r,owner,meta.surface,meta.width,meta.height);if(result)return result;
 struct iosgpu_surface_record *old=NULL,*slot=NULL;
 for(unsigned n=0;n<IOSGPU_SNAPSHOT_SLOTS;n++){
  struct iosgpu_surface_record *s=&r->records[n];
  if(!s->resource){if(!slot)slot=s;continue;}
  if(s->current&&s->owner==owner&&s->meta.surface==meta.surface)old=s;
 }
 /* A stable token may name successive immutable targets of the same live
  * surface. A current record anchors this permission: retired tokens cannot
  * be resurrected, and another surface/owner cannot borrow the capability. */
 for(unsigned n=0;n<IOSGPU_SNAPSHOT_SLOTS;n++){
  struct iosgpu_surface_record *s=&r->records[n];if(!s->resource)continue;
  if(s->resource==resource)return -EEXIST;
  if(s->meta.capability[0]==meta.capability[0]&&s->meta.capability[1]==meta.capability[1]&&
     !(old&&equal(&old->meta,&meta)&&s->owner==owner&&equal(&s->meta,&meta)))return -EEXIST;
 }
 uint32_t retired=0;if(old&&!references(old)){slot=old;retired=old->resource;}
 if(!slot)return -ENOSPC;
 if(old)old->current=0;
 memset(slot,0,sizeof(*slot));slot->owner=owner;slot->resource=resource;slot->current=1;slot->meta=meta;*drop=retired;return 0;
}
int iosgpu_surface_resolve(struct iosgpu_surface_registry *r,uint32_t context,const struct iosgpu_surface_meta *meta,uint32_t *resource){
 if(!r||!consumer(context)||!resource||!iosgpu_surface_meta_valid(meta))return -EINVAL;
 struct iosgpu_surface_record *s=current(r,meta);if(!s)return -ENOENT;
 struct iosgpu_surface_consumer *slot=NULL;
 for(unsigned n=0;n<IOSGPU_SNAPSHOT_CONSUMERS;n++){
  struct iosgpu_surface_consumer *c=&s->consumers[n];
  if(c->context==context){if(c->count>=IOSGPU_SNAPSHOT_NAME_REFS)return -ENOSPC;slot=c;break;}
  if(!c->count&&!slot)slot=c;
 }
 if(!slot)return -ENOSPC;slot->context=context;slot->count++;*resource=s->resource;return 0;
}
int iosgpu_surface_unref(struct iosgpu_surface_registry *r,uint32_t context,uint32_t resource,uint32_t *drop){
 if(!r||!consumer(context)||!resource||!drop)return -EINVAL;
 for(unsigned n=0;n<IOSGPU_SNAPSHOT_SLOTS;n++){
  struct iosgpu_surface_record *s=&r->records[n];if(s->resource!=resource)continue;
  for(unsigned m=0;m<IOSGPU_SNAPSHOT_CONSUMERS;m++){
   struct iosgpu_surface_consumer *c=&s->consumers[m];if(c->context!=context||!c->count)continue;
   if(!--c->count)c->context=0;
   uint32_t retired=!s->current&&!references(s)?s->resource:0;
   if(retired)memset(s,0,sizeof(*s));*drop=retired;return 0;
  }
  return -ENOENT;
 }return -ENOENT;
}
int iosgpu_surface_retire(struct iosgpu_surface_registry *r,uint32_t owner,const struct iosgpu_surface_meta *meta,uint32_t *drop){
 if(!r||!producer(owner)||!drop||!iosgpu_surface_meta_valid(meta))return -EINVAL;
 struct iosgpu_surface_record *s=current(r,meta);if(!s||s->owner!=owner)return -ENOENT;
 s->current=0;uint32_t retired=references(s)?0:s->resource;
 if(retired)memset(s,0,sizeof(*s));*drop=retired;return 0;
}
int iosgpu_surface_consumer_closed(struct iosgpu_surface_registry *r,uint32_t context,uint32_t *drops,size_t capacity,size_t *written){
 if(!r||!consumer(context)||!drops||!written||capacity<IOSGPU_SNAPSHOT_SLOTS)return -EINVAL;
 size_t count=0;
 for(unsigned n=0;n<IOSGPU_SNAPSHOT_SLOTS;n++){
  struct iosgpu_surface_record *s=&r->records[n];if(!s->resource)continue;
  for(unsigned m=0;m<IOSGPU_SNAPSHOT_CONSUMERS;m++)if(s->consumers[m].context==context)memset(&s->consumers[m],0,sizeof(s->consumers[m]));
  if(!s->current&&!references(s)){drops[count++]=s->resource;memset(s,0,sizeof(*s));}
 }*written=count;return 0;
}
