/* Private bounded request/response staging, never guest memory. AGPL-3.0-or-later. */
#ifndef IOSGPU_WORKER_SHARED_H
#define IOSGPU_WORKER_SHARED_H
#include <fcntl.h>
#include <stdatomic.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include "worker_protocol.h"
#define IOSGPU_SHARED_MAGIC UINT32_C(0x49575333)
#define IOSGPU_SHARED_SEALS (F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL)
struct iosgpu_shared_response {
 uint32_t magic,version,capacity,reserved;
 _Atomic uint64_t sequence;
 _Atomic uint64_t request_sequence;
 uint8_t padding[32];
 uint8_t bytes[];
};
_Static_assert(offsetof(struct iosgpu_shared_response,bytes)==64,"shared payload ABI");
#define IOSGPU_SHARED_SIZE (offsetof(struct iosgpu_shared_response,bytes)+(size_t)IOSGPU_MAX_BYTES*2u)
static inline uint8_t *iosgpu_shared_request_buffer(struct iosgpu_shared_response *p) {
 return p->bytes+IOSGPU_MAX_BYTES;
}
static inline int iosgpu_shared_header_valid(const struct iosgpu_shared_response *p) {
 if(p->magic!=IOSGPU_SHARED_MAGIC||p->version!=IOSGPU_WORKER_VERSION||
    p->capacity!=IOSGPU_MAX_BYTES||p->reserved)return 0;
 for(unsigned i=0;i<sizeof(p->padding);i++)if(p->padding[i])return 0;
 return 1;
}
static inline struct iosgpu_shared_response *iosgpu_shared_map(int fd,int initialize) {
 struct stat st;int seals=fcntl(fd,F_GET_SEALS);
 if(seals<0||(seals&IOSGPU_SHARED_SEALS)!=IOSGPU_SHARED_SEALS||fstat(fd,&st)||
    !S_ISREG(st.st_mode)||st.st_size!=(off_t)IOSGPU_SHARED_SIZE)return NULL;
 struct iosgpu_shared_response *p=mmap(NULL,IOSGPU_SHARED_SIZE,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
 if(p==MAP_FAILED)return NULL;
 if(initialize){
  memset(p,0,offsetof(struct iosgpu_shared_response,bytes));
  p->magic=IOSGPU_SHARED_MAGIC;p->version=IOSGPU_WORKER_VERSION;p->capacity=IOSGPU_MAX_BYTES;
  atomic_init(&p->sequence,0);
  atomic_init(&p->request_sequence,0);
 }
 /* The parent may publish request1 before the exec child reaches mmap. Only
  * the response generation must still be zero at worker startup. */
 if(!atomic_is_lock_free(&p->sequence)||!atomic_is_lock_free(&p->request_sequence)||!iosgpu_shared_header_valid(p)||
    atomic_load_explicit(&p->sequence,memory_order_acquire)!=0){
  munmap(p,IOSGPU_SHARED_SIZE);return NULL;
 }
 return p;
}
static inline struct iosgpu_shared_response *iosgpu_shared_create(int *fd_out) {
 *fd_out=-1;
 int fd=memfd_create("iosgpu-response",MFD_CLOEXEC|MFD_ALLOW_SEALING);
 if(fd<0)return NULL;
 if(ftruncate(fd,(off_t)IOSGPU_SHARED_SIZE)||fcntl(fd,F_ADD_SEALS,IOSGPU_SHARED_SEALS)){
  close(fd);return NULL;
 }
 struct iosgpu_shared_response *p=iosgpu_shared_map(fd,1);
 if(!p){close(fd);return NULL;}
 *fd_out=fd;return p;
}
static inline int iosgpu_shared_ready(const struct iosgpu_shared_response *p,uint64_t expected) {
 return expected!=0&&iosgpu_shared_header_valid(p)&&
  atomic_load_explicit(&p->sequence,memory_order_acquire)==expected;
}
static inline int iosgpu_shared_request_ready(const struct iosgpu_shared_response *p,uint64_t expected) {
 return expected!=0&&iosgpu_shared_header_valid(p)&&
  atomic_load_explicit(&p->request_sequence,memory_order_acquire)==expected;
}
#endif
