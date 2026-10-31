/* Authored exact-size cache policy. Caller serializes access. AGPL-3.0-or-later. */
#ifndef IOSMETAL_REPLY_CACHE_H
#define IOSMETAL_REPLY_CACHE_H
#include <stddef.h>
enum { IOSM_REPLY_CACHE_SLOTS=2,IOSM_REPLY_CACHE_MIN=4*1024*1024,IOSM_REPLY_CACHE_LIMIT=32*1024*1024 };
struct iosm_reply_cache {void *memory[IOSM_REPLY_CACHE_SLOTS];size_t size[IOSM_REPLY_CACHE_SLOTS];size_t bytes;unsigned count;};
static inline void *iosm_reply_cache_take(struct iosm_reply_cache *cache,size_t size){
 for(unsigned i=0;i<cache->count;i++)if(cache->size[i]==size){
  void *p=cache->memory[i];cache->bytes-=size;
  for(unsigned j=i+1;j<cache->count;j++){cache->memory[j-1]=cache->memory[j];cache->size[j-1]=cache->size[j];}
  cache->count--;cache->memory[cache->count]=NULL;cache->size[cache->count]=0;return p;
 }
 return NULL;
}
static inline void iosm_reply_cache_put(struct iosm_reply_cache *cache,void *memory,size_t size,void (*destroy)(void *)){
 if(!memory)return;
 if(size<IOSM_REPLY_CACHE_MIN||size>IOSM_REPLY_CACHE_LIMIT){destroy(memory);return;}
 while(cache->count&&(cache->count==IOSM_REPLY_CACHE_SLOTS||cache->bytes>IOSM_REPLY_CACHE_LIMIT-size)){
  void *old=cache->memory[0];cache->bytes-=cache->size[0];
  for(unsigned j=1;j<cache->count;j++){cache->memory[j-1]=cache->memory[j];cache->size[j-1]=cache->size[j];}
  cache->count--;cache->memory[cache->count]=NULL;cache->size[cache->count]=0;destroy(old);
 }
 cache->memory[cache->count]=memory;cache->size[cache->count]=size;cache->count++;cache->bytes+=size;
}
static inline void iosm_reply_cache_clear(struct iosm_reply_cache *cache,void (*destroy)(void *)){
 for(unsigned i=0;i<cache->count;i++){destroy(cache->memory[i]);cache->memory[i]=NULL;cache->size[i]=0;}
 cache->count=0;cache->bytes=0;
}
#endif
