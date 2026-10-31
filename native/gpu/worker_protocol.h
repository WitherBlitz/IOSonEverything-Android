/* Private same-architecture worker wire; SPDX-License-Identifier: AGPL-3.0-or-later. */
#ifndef IOSGPU_WORKER_PROTOCOL_H
#define IOSGPU_WORKER_PROTOCOL_H
#include <stddef.h>
#include <stdint.h>
#include "protocol.h"
#define IOSGPU_WORKER_REQUEST_MAGIC UINT32_C(0x49575031)
#define IOSGPU_WORKER_REPLY_MAGIC UINT32_C(0x49575231)
#define IOSGPU_WORKER_VERSION 3u
#define IOSGPU_WORKER_FD 3
#define IOSGPU_WORKER_SHARED_FD 4
struct iosgpu_worker_request {
 uint32_t magic,version,operation,context,size,capacity;
 uint64_t sequence;
};
struct iosgpu_worker_reply {
 uint32_t magic,version;
 uint64_t sequence;
 int64_t result;
 uint32_t written,reserved;
};
_Static_assert(sizeof(struct iosgpu_worker_request)==32,"worker request ABI");
_Static_assert(offsetof(struct iosgpu_worker_request,sequence)==24,"request sequence ABI");
_Static_assert(sizeof(struct iosgpu_worker_reply)==32,"worker reply ABI");
_Static_assert(offsetof(struct iosgpu_worker_reply,result)==16,"reply result ABI");
static inline int iosgpu_worker_request_valid(const struct iosgpu_worker_request *r,uint64_t expected) {
 return r->magic==IOSGPU_WORKER_REQUEST_MAGIC&&r->version==IOSGPU_WORKER_VERSION&&
  r->sequence==expected&&expected!=0&&r->operation<=IOSGPU_METAL_CALL&&
  r->size<=IOSGPU_MAX_BYTES&&r->capacity<=IOSGPU_MAX_BYTES;
}
static inline int iosgpu_worker_reply_valid(const struct iosgpu_worker_reply *r,uint64_t expected,uint32_t capacity) {
 return r->magic==IOSGPU_WORKER_REPLY_MAGIC&&r->version==IOSGPU_WORKER_VERSION&&
  r->sequence==expected&&expected!=0&&r->reserved==0&&r->written<=capacity&&
  (r->result>=0||r->written==0);
}
#endif
