/* Authored bounded encoder command stream. AGPL-3.0-or-later. */
#ifndef IOSM_COMMAND_BATCH_H
#define IOSM_COMMAND_BATCH_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define IOSM_BATCH_MAX_OPERATIONS 256u
#define IOSM_BATCH_MAX_BYTES 65536u
struct iosm_command_batch {uint32_t count,used;uint8_t bytes[IOSM_BATCH_MAX_BYTES];};
static inline uint32_t iosm_batch_body_size(uint32_t op){switch(op){case 11:case 23:return 16;case 12:return 32;case 13:return 60;case 14:return 8;case 24:return 44;case 26:case 28:case 31:return 24;default:return 0;}}
static inline void iosm_batch_clear(struct iosm_command_batch *batch){batch->count=0;batch->used=4;memset(batch->bytes,0,4);}
static inline void iosm_batch_write32(uint8_t *out,uint32_t value){for(unsigned i=0;i<4;i++)out[i]=(uint8_t)(value>>(8*i));}
/* 1:queued,0:flush before retry,-1:invalid input/state. No mutation on0/-1. */
static inline int iosm_batch_push(struct iosm_command_batch *batch,uint32_t op,const void *body,size_t length){
 uint32_t expected=iosm_batch_body_size(op);if(!expected||length!=expected||!body||batch->used<4||batch->used>IOSM_BATCH_MAX_BYTES||batch->count>IOSM_BATCH_MAX_OPERATIONS)return -1;
 if(batch->count==IOSM_BATCH_MAX_OPERATIONS||8u+length>IOSM_BATCH_MAX_BYTES-batch->used)return 0;
 uint8_t *record=batch->bytes+batch->used;iosm_batch_write32(record,op);iosm_batch_write32(record+4,(uint32_t)length);memcpy(record+8,body,length);
 batch->used+=(uint32_t)(8+length);batch->count++;iosm_batch_write32(batch->bytes,batch->count);return 1;
}
#endif
