/* Firmware-free unit harness for the real helper, with a modeled QEMU MMU probe.
 * This checks RPC control flow and page-sized copies; it does not replace a
 * full-system ARM MMU integration test. SPDX-License-Identifier: AGPL-3.0-or-later */
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#define EINVAL 22
#define EFAULT 14
#define ENOMEM 12
#define ENOSYS 38
#define EPROTO 71
#define EACCES 13
#define ENOSPC 28
#define TARGET_PAGE_SIZE 4096u
#define TARGET_PAGE_MASK (~(uint64_t)(TARGET_PAGE_SIZE - 1))
#define TLB_INVALID_MASK 1
#define TLB_MMIO 2
#define TLB_WATCHPOINT 4
#define HELPER(name) helper_##name
typedef uint64_t vaddr;
typedef enum { MMU_DATA_LOAD, MMU_DATA_STORE } MMUAccessType;
typedef struct { uint64_t xregs[32];struct {uint64_t ttbr0_el[4];}cp15; } CPUARMState;
typedef CPUARMState CPUState;
#define env_cpu(env) (env)
static uint8_t pages[4][TARGET_PAGE_SIZE], allocations[2][8192];
static unsigned rights[4], mmio[4], watched[4], allocation_count;
static unsigned backend_calls, debug_calls, mmio_calls, bad_probe, probes;
static unsigned backend_written, revoke_output, capacity_tail;
static int64_t backend_result;
#define OWNER_TTBR UINT64_C(0x123400001000)
static uint8_t captured[64];
void *memcpy(void *d, const void *s, size_t n) {
 uint8_t *to=d;const uint8_t *from=s;for(size_t i=0;i<n;i++)to[i]=from[i];return d;
}
void *memset(void *d, int c, size_t n) {
 uint8_t *to=d;for(size_t i=0;i<n;i++)to[i]=(uint8_t)c;return d;
}
static int cpu_mmu_index(CPUState *cpu, int ifetch) {
 (void)cpu;if(ifetch)bad_probe++;return 7;
}
static int probe_access_flags(CPUARMState *env,vaddr address,int size,
 MMUAccessType access,int mmu_idx,int nonfault,void **host,uintptr_t ra) {
 (void)env;probes++;*host=NULL;
 if(mmu_idx!=7||!nonfault||ra||size<0||
    (unsigned)size>TARGET_PAGE_SIZE-(address&(TARGET_PAGE_SIZE-1)))bad_probe++;
 if(address<0x1000||address>=0x5000)return TLB_INVALID_MASK;
 unsigned p=(unsigned)((address-0x1000)/TARGET_PAGE_SIZE);
 if(!(rights[p]&(access==MMU_DATA_LOAD?1u:2u)))return TLB_INVALID_MASK;
 if(mmio[p])return TLB_MMIO;
 *host=pages[p]+(address&(TARGET_PAGE_SIZE-1));
 return watched[p]?TLB_WATCHPOINT:0;
}
static int cpu_memory_rw_debug(CPUState *cpu,vaddr address,void *buffer,size_t n,int write) {
 (void)cpu;debug_calls++;
 while(n){
  if(address<0x1000||address>=0x5000)return -1;
  unsigned p=(unsigned)((address-0x1000)/TARGET_PAGE_SIZE);
  size_t at=(size_t)(address&(TARGET_PAGE_SIZE-1)),k=TARGET_PAGE_SIZE-at;
  if(k>n)k=n;if(mmio[p])mmio_calls++;
  if(write)memcpy(pages[p]+at,buffer,k);else memcpy(buffer,pages[p]+at,k);
  address+=k;buffer=(uint8_t *)buffer+k;n-=k;
 }
 return 0;
}
static void *g_try_malloc(size_t n) {
 if(n>8192||allocation_count>=2)return NULL;return allocations[allocation_count++];
}
static void *g_try_malloc0(size_t n) {void *p=g_try_malloc(n);if(p)memset(p,0,n);return p;}
static void g_free(void *p) {(void)p;}
char *getenv(const char *name) {(void)name;return NULL;}
void *dlopen(const char *name,int flags) {(void)name;(void)flags;return NULL;}
void *dlsym(void *handle,const char *name) {(void)handle;(void)name;return NULL;}
#include "pthread.h"
int pthread_once(pthread_once_t *once,void (*function)(void)) {(void)once;(void)function;return 0;}
int pthread_mutex_lock(pthread_mutex_t *mutex) {(void)mutex;return 0;}
int pthread_mutex_unlock(pthread_mutex_t *mutex) {(void)mutex;return 0;}
#define g_atomic_int_get(p) (*(p))
#define g_atomic_int_set(p,v) (*(p)=(v))
static int64_t g_get_monotonic_time(void){return 1;}
static void *stderr;
int fprintf(void *stream,const char *format,...){(void)stream;(void)format;return 0;}
#include "../../../third_party/inferno/target/arm/tcg/iosgpu-helper.c.inc"
static int64_t backend(uint32_t op,uint32_t context,const void *request,uint32_t size,
 void *reply,uint32_t capacity,uint32_t *written) {
 (void)context;backend_calls++;
 if(size){size_t n=size>sizeof(captured)?sizeof(captured):size;memcpy(captured,request,n);}
 if(capacity)memset(reply,0xa5,capacity);
 *written=backend_written?backend_written:capacity;
 if(revoke_output)rights[1]=1;
 if(capacity_tail)*written=1;
 return op==IOSGPU_PING?(int64_t)IOSGPU_REPLY:backend_result;
}
static void reset(void) {
 memset(pages,0,sizeof(pages));memset(captured,0,sizeof(captured));
 for(unsigned i=0;i<4;i++){rights[i]=3;mmio[i]=watched[i]=0;}
 allocation_count=backend_calls=debug_calls=mmio_calls=bad_probe=probes=0;
 backend_written=revoke_output=capacity_tail=0;iosgpu_rpc=backend;
 backend_result=0;memset(iosgpu_owners,0,sizeof(iosgpu_owners));
 iosgpu_owners[0].context=1;iosgpu_owners[0].ttbr=OWNER_TTBR;
}
static CPUARMState call_as(uint32_t op,uint32_t context,uint64_t input,uint64_t size,uint64_t output,uint64_t capacity,uint64_t ttbr) {
 CPUARMState env={0};env.xregs[0]=op;env.xregs[1]=context;env.xregs[2]=input;
 env.xregs[3]=size;env.xregs[4]=output;env.xregs[5]=capacity;env.xregs[16]=IOSGPU_MAGIC;
 env.cp15.ttbr0_el[1]=ttbr;
 helper_iosgpu(&env);return env;
}
static CPUARMState call(uint32_t op,uint64_t input,uint64_t size,uint64_t output,uint64_t capacity) {
 return call_as(op,1,input,size,output,capacity,OWNER_TTBR);
}
static int rejected(CPUARMState env) {return (int64_t)env.xregs[0]==-EFAULT&&env.xregs[1]==0&&backend_calls==0;}
__attribute__((visibility("default"))) unsigned run_tests(void) {
 unsigned failures=0;CPUARMState env;
 reset();env=call(IOSGPU_WRITE,0x999000,8,0,0);if(!rejected(env))failures|=1u<<0;
 reset();rights[0]=0;env=call(IOSGPU_WRITE,0x1000,8,0,0);if(!rejected(env))failures|=1u<<1;
 reset();mmio[0]=1;env=call(IOSGPU_WRITE,0x1000,8,0,0);if(!rejected(env)||mmio_calls)failures|=1u<<2;
 reset();rights[1]=1;env=call(IOSGPU_READ,0,0,0x2000,8);if(!rejected(env)||pages[1][0])failures|=1u<<3;
 reset();mmio[1]=1;env=call(IOSGPU_READ,0,0,0x2000,8);if(!rejected(env)||mmio_calls)failures|=1u<<4;
 reset();env=call(IOSGPU_READ,0,0,0x999000,8);if(!rejected(env))failures|=1u<<5;
 reset();for(unsigned i=0;i<16;i++){pages[0][4088+i%8]=(uint8_t)(i%8+1);pages[1][i%8]=(uint8_t)(i%8+9);}
 env=call(IOSGPU_WRITE,0x1ff8,16,0,0);
 if((int64_t)env.xregs[0]||backend_calls!=1||captured[0]!=1||captured[7]!=8||captured[8]!=9||captured[15]!=16||bad_probe)failures|=1u<<6;
 reset();rights[1]=0;env=call(IOSGPU_WRITE,0x1ff8,16,0,0);if(!rejected(env))failures|=1u<<7;
 reset();backend_written=9;env=call(IOSGPU_READ,0,0,0x2000,8);
 if((int64_t)env.xregs[0]!=-EPROTO||env.xregs[1]||pages[1][0])failures|=1u<<8;
 reset();revoke_output=1;env=call(IOSGPU_READ,0,0,0x2000,8);
 if((int64_t)env.xregs[0]!=-EFAULT||env.xregs[1]||backend_calls!=1||pages[1][0])failures|=1u<<9;
 reset();watched[0]=1;env=call(IOSGPU_WRITE,0x1000,8,0,0);if(!rejected(env))failures|=1u<<10;
 reset();rights[1]=0;capacity_tail=1;env=call(IOSGPU_READ,0,0,0x1ffc,8);if(!rejected(env))failures|=1u<<11;
 reset();env=call(IOSGPU_READ,0,0,0x2000,8);
 if((int64_t)env.xregs[0]||env.xregs[1]!=8||pages[1][0]!=0xa5||debug_calls||!probes||bad_probe)failures|=1u<<12;
 reset();env=call_as(IOSGPU_READ,1,0,0,0x2000,8,OWNER_TTBR+(UINT64_C(1)<<48));
 if((int64_t)env.xregs[0]!=-EACCES||env.xregs[1]||backend_calls||pages[1][0])failures|=1u<<13;
 reset();env=call(IOSGPU_CLOSE,0,0,0,0);
 if((int64_t)env.xregs[0]||backend_calls!=1||iosgpu_owners[0].context)failures|=1u<<14;
 reset();backend_result=2;env=call_as(IOSGPU_OPEN,0,0,0,0,0,OWNER_TTBR+1);
 if((int64_t)env.xregs[0]!=2||iosgpu_owners[1].context!=2||iosgpu_owners[1].ttbr!=OWNER_TTBR+1)failures|=1u<<15;
 return failures;
}
