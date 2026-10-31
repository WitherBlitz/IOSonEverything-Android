/* Actual proxy/worker control flow with deterministic OS/driver substitutes.
 * Does not prove real posix_spawn/SELinux behavior. SPDX-License-Identifier: AGPL-3.0-or-later. */
#include "worker_proxy_stubs/shim.h"
#include "../worker_protocol.h"
#include "../worker_shared.h"
enum { NORMAL, TIMEOUT, BAD_SEQUENCE, TOO_LARGE, TRUNCATED, FATAL_BACKEND,
 VALIDATION_ERROR, LOCKED, NEVER_REAP, PARENT_CHANGED, BAD_REQUEST, DRIBBLE, WRITE_STALL,
 SHORT_SUCCESS, REGION_SUCCESS, STALE_SHARED, MEMFD_FAIL, SEAL_FAIL, MAP_FAIL,
 WRONG_SHARED_SIZE, BAD_SHARED_HEADER, STALE_REQUEST };
static int mode,role,clock_ms,spawned,killed,reaped,filtered,bad_actions,parent_checks;
static int send_interrupted,recv_interrupted,backend_calls,backend_request_mismatch;
static uint8_t arena[65536],outgoing_bytes[256],incoming_bytes[256];
static size_t arena_at,outgoing_at,incoming_at,incoming_size;
static union { uint64_t alignment; uint8_t bytes[IOSGPU_SHARED_SIZE]; } shared_store;
int test_errno;
char **environ;
int __android_log_print(int priority,const char *tag,const char *format,...){(void)priority;(void)tag;(void)format;return 0;}
void *memcpy(void *d,const void *s,size_t n){uint8_t *p=d;const uint8_t *q=s;for(size_t i=0;i<n;i++)p[i]=q[i];return d;}
void *memset(void *d,int c,size_t n){uint8_t *p=d;for(size_t i=0;i<n;i++)p[i]=(uint8_t)c;return d;}
static size_t length(const char *s){size_t n=0;while(s[n])n++;return n;}
void *malloc(size_t n){n=(n+7)&~(size_t)7;if(n>sizeof(arena)-arena_at)return NULL;void *p=arena+arena_at;arena_at+=n;return p;}
void *calloc(size_t n,size_t s){if(s&&n>SIZE_MAX/s)return NULL;void *p=malloc(n*s);if(p)memset(p,0,n*s);return p;}
void free(void *p){(void)p;}
char *strdup(const char *s){size_t n=length(s)+1;char *p=malloc(n);if(p)memcpy(p,s,n);return p;}
char *strrchr(const char *s,int c){char *p=NULL;do{if(*s==c)p=(char *)s;}while(*s++);return p;}
int strncmp(const char *a,const char *b,size_t n){for(size_t i=0;i<n;i++){if(a[i]!=b[i])return (unsigned char)a[i]-(unsigned char)b[i];if(!a[i])return 0;}return 0;}
int strcmp(const char *a,const char *b){return strncmp(a,b,SIZE_MAX);}
int snprintf(char *dst,size_t capacity,const char *format,...){
 va_list ap;va_start(ap,format);size_t n=0;
 if(!strcmp(format,"%ld")){long v=va_arg(ap,long);if(v!=7){va_end(ap);return -1;}if(capacity>1){dst[0]='7';dst[1]=0;}n=1;}
 else if(!strcmp(format,"%.*s%s")){int take=va_arg(ap,int);const char *src=va_arg(ap,const char *),*tail=va_arg(ap,const char *);
  for(int i=0;i<take;i++){if(n+1<capacity)dst[n]=src[i];n++;}
  for(size_t i=0;tail[i];i++){if(n+1<capacity)dst[n]=tail[i];n++;}
  if(capacity)dst[n<capacity?n:capacity-1]=0;
 }else n=(size_t)-1;
 va_end(ap);return (int)n;
}
long strtol(const char *s,char **end,int base){(void)base;long n=0;while(*s>='0'&&*s<='9')n=n*10+*s++-'0';*end=(char *)s;return n;}
int clock_gettime(int which,struct timespec *now){if(which!=CLOCK_MONOTONIC)return -1;clock_ms++;now->tv_sec=clock_ms/1000;now->tv_nsec=(clock_ms%1000)*1000000;return 0;}
int poll(struct pollfd *p,unsigned long count,int timeout){
 if(!count){clock_ms+=timeout;return 0;}
 if(mode==TIMEOUT){clock_ms+=timeout;return 0;}
 if(mode==DRIBBLE)clock_ms+=8;
 p->revents=p->events;return 1;
}
static void make_reply(void){
 if(outgoing_at<sizeof(struct iosgpu_worker_request))return;
 struct iosgpu_worker_request r;memcpy(&r,outgoing_bytes,sizeof(r));
 struct iosgpu_worker_reply p={IOSGPU_WORKER_REPLY_MAGIC,IOSGPU_WORKER_VERSION,r.sequence,
  r.operation==IOSGPU_PING?(int64_t)IOSGPU_REPLY:0,r.capacity,0};
 if(mode==BAD_SEQUENCE)p.sequence++;
 if(mode==TOO_LARGE)p.written=r.capacity+1;
 if(mode==SHORT_SUCCESS)p.written=r.capacity-1;
 if(mode==REGION_SUCCESS)p.written=16;
 if(mode==FATAL_BACKEND){p.result=-EIO;p.written=0;}
 if(mode==VALIDATION_ERROR){p.result=-EINVAL;p.written=0;}
 memcpy(incoming_bytes,&p,sizeof(p));
 struct iosgpu_shared_response *shared=(void *)shared_store.bytes;
 for(unsigned i=0;i<r.capacity;i++)shared->bytes[i]=0xa5;
 shared->sequence=mode==STALE_SHARED?0:r.sequence;
 if(mode==STALE_REQUEST)shared->request_sequence=0;
 if(mode==BAD_SHARED_HEADER)shared->capacity--;
 incoming_size=sizeof(p);
 if(mode==TRUNCATED)incoming_size=sizeof(p)/2;
}
ssize_t send(int fd,const void *data,size_t size,int flags){
 (void)fd;(void)flags;
 if(mode==WRITE_STALL){errno=EAGAIN;return -1;}
 if(!send_interrupted++){errno=EINTR;return -1;}
 size_t n=size>3?3:size;if(outgoing_at+n>sizeof(outgoing_bytes))return -1;
 memcpy(outgoing_bytes+outgoing_at,data,n);outgoing_at+=n;if(!role)make_reply();return (ssize_t)n;
}
ssize_t recv(int fd,void *data,size_t size,int flags){
 (void)fd;(void)flags;
 if(!recv_interrupted++){errno=EINTR;return -1;}
 if(incoming_at>=incoming_size)return 0;
 size_t n=incoming_size-incoming_at;if(n>size)n=size;if(n>2)n=2;
 memcpy(data,incoming_bytes+incoming_at,n);incoming_at+=n;return (ssize_t)n;
}
int close(int fd){(void)fd;return 0;}
int kill(pid_t pid,int signal){if(pid==42&&signal==SIGKILL)killed++;return 0;}
pid_t getpid(void){return 7;}
pid_t getppid(void){parent_checks++;return mode==PARENT_CHANGED&&parent_checks>1?8:7;}
pid_t waitpid(pid_t pid,int *status,int flags){(void)status;(void)flags;if(mode==NEVER_REAP)return 0;reaped++;return pid;}
int socketpair(int domain,int type,int protocol,int *s){(void)domain;(void)type;(void)protocol;s[0]=3;s[1]=4;return 0;}
int fcntl(int fd,int command,...){(void)fd;if(command==F_GET_SEALS)return mode==SEAL_FAIL?0:IOSGPU_SHARED_SEALS;return command==F_DUPFD_CLOEXEC?6:0;}
int memfd_create(const char *name,unsigned flags){(void)name;(void)flags;return mode==MEMFD_FAIL?-1:5;}
int ftruncate(int fd,off_t size){(void)fd;(void)size;return 0;}
int fstat(int fd,struct stat *st){(void)fd;st->st_mode=0100000u;st->st_size=(off_t)IOSGPU_SHARED_SIZE+(mode==WRONG_SHARED_SIZE);return 0;}
void *mmap(void *address,size_t size,int prot,int flags,int fd,off_t offset){(void)address;(void)size;(void)prot;(void)flags;(void)fd;(void)offset;return mode==MAP_FAIL?MAP_FAILED:shared_store.bytes;}
int munmap(void *address,size_t size){(void)address;(void)size;return 0;}
int dladdr(const void *ptr,Dl_info *info){(void)ptr;info->dli_fname="/test/libios_gpu.so";return 1;}
int pthread_mutex_trylock(pthread_mutex_t *mutex){(void)mutex;return mode==LOCKED?EBUSY:0;}
int pthread_mutex_unlock(pthread_mutex_t *mutex){(void)mutex;return 0;}
int posix_spawn_file_actions_init(posix_spawn_file_actions_t *a){memset(a,0,sizeof(*a));return 0;}
int posix_spawn_file_actions_addclose(posix_spawn_file_actions_t *a,int fd){int n=a->count++;a->kind[n]=1;a->from[n]=fd;return 0;}
int posix_spawn_file_actions_adddup2(posix_spawn_file_actions_t *a,int from,int to){int n=a->count++;a->kind[n]=2;a->from[n]=from;a->to[n]=to;return 0;}
int posix_spawn_file_actions_destroy(posix_spawn_file_actions_t *a){(void)a;return 0;}
int posix_spawn(pid_t *pid,const char *path,const posix_spawn_file_actions_t *a,const void *attr,char *const *args,char *const *env){
 (void)attr;spawned++;*pid=42;
 if(strcmp(path,"/test/libios_gpu_worker.so")||strcmp(args[1],"--iosgpu-worker")||strcmp(args[2],"7"))bad_actions++;
 if(a->count!=5||a->kind[0]!=1||a->from[0]!=3||a->kind[1]!=2||a->from[1]!=6||a->to[1]!=3||a->kind[2]!=2||a->from[2]!=5||a->to[2]!=4||a->kind[3]!=1||a->from[3]!=6||a->kind[4]!=1||a->from[4]!=5)bad_actions++;
 int library_path=0;filtered=1;for(unsigned i=0;env[i];i++){
  if(!strncmp(env[i],"LD_PRELOAD=",11)||!strncmp(env[i],"IOSVM_WRITER_",13))filtered=0;
  if(!strcmp(env[i],"LD_LIBRARY_PATH=/test"))library_path++;
 }
 if(library_path!=1)filtered=0;
 return 0;
}
int prctl(int option,...){return option==PR_SET_PDEATHSIG?0:-1;}
int getsockopt(int fd,int level,int option,void *value,socklen_t *size){(void)fd;(void)level;(void)option;*(int *)value=SOCK_STREAM;*size=sizeof(int);return 0;}
#define IOSGPU_RPC_TIMEOUT_MS 100u
#include "../bridge.c"
#define main isolated_worker_main
#include "../worker.c"
#undef main
int64_t iosgpu_route_call(uint32_t op,uint32_t context,const void *request,uint32_t size,void *reply,uint32_t capacity,uint32_t *written){
 (void)op;(void)context;backend_calls++;
 if(size){
  if(size!=8||(const uint8_t *)request!=(uint8_t *)reply+IOSGPU_MAX_BYTES)backend_request_mismatch=1;
  else for(unsigned i=0;i<size;i++)if(((const uint8_t *)request)[i]!=(uint8_t)(i+31))backend_request_mismatch=1;
 }
 if(capacity)memset(reply,0xa5,capacity);*written=capacity;return 0;
}
static void reset(int new_mode){
 static char *environment[]={"LD_PRELOAD=must-not-leak","IOSVM_WRITER_LOCK=must-not-leak","LD_LIBRARY_PATH=/parent-path","KEEP=value",NULL};
 environ=environment;mode=new_mode;role=clock_ms=spawned=killed=reaped=filtered=bad_actions=parent_checks=0;
 send_interrupted=recv_interrupted=backend_calls=backend_request_mismatch=0;arena_at=outgoing_at=incoming_at=incoming_size=0;
 worker_pid=-1;worker_socket=-1;worker_broken=0;worker_sequence=1;
 worker_shared=NULL;
 memset(shared_store.bytes,0,sizeof(shared_store.bytes));
 struct iosgpu_shared_response *shared=(void *)shared_store.bytes;
 shared->magic=IOSGPU_SHARED_MAGIC;shared->version=IOSGPU_WORKER_VERSION;shared->capacity=IOSGPU_MAX_BYTES;
}
static int run_worker(int malformed,int changed_parent){
 reset(changed_parent?PARENT_CHANGED:NORMAL);role=1;
 ((struct iosgpu_shared_response *)(void *)shared_store.bytes)->request_sequence=1;
 struct iosgpu_worker_request r={IOSGPU_WORKER_REQUEST_MAGIC,IOSGPU_WORKER_VERSION,IOSGPU_READ,1,0,8,1};
 if(malformed)r.capacity=IOSGPU_MAX_BYTES+1;
 memcpy(incoming_bytes,&r,sizeof(r));incoming_size=sizeof(r);
 char *argv[]={"/test/libios_gpu_worker.so","--iosgpu-worker","7",NULL};
 return isolated_worker_main(3,argv);
}
static int run_worker_upload(int stale){
 reset(NORMAL);role=1;
 struct iosgpu_shared_response *shared=(void *)shared_store.bytes;
 shared->request_sequence=stale?0:1;
 for(unsigned i=0;i<8;i++)iosgpu_shared_request_buffer(shared)[i]=(uint8_t)(i+31);
 struct iosgpu_worker_request r={IOSGPU_WORKER_REQUEST_MAGIC,IOSGPU_WORKER_VERSION,IOSGPU_METAL_CALL,1,8,8,1};
 memcpy(incoming_bytes,&r,sizeof(r));incoming_size=sizeof(r);
 char *argv[]={"/test/libios_gpu_worker.so","--iosgpu-worker","7",NULL};
 return isolated_worker_main(3,argv);
}
__attribute__((visibility("default"))) unsigned run_tests(void){
 unsigned failures=0,written;int64_t result;uint8_t output[8];
 reset(NORMAL);written=99;result=iosvm_gpu_rpc(IOSGPU_READ,1,NULL,0,output,8,&written);
 if(result||written!=8||output[0]!=0xa5||!filtered||bad_actions||spawned!=1||!send_interrupted||!recv_interrupted)failures|=1u<<0;
 int fatal_modes[]={TIMEOUT,BAD_SEQUENCE,TOO_LARGE,TRUNCATED,FATAL_BACKEND};
 for(unsigned i=0;i<5;i++){
  reset(fatal_modes[i]);written=99;memset(output,0x7b,sizeof(output));
  result=iosvm_gpu_rpc(IOSGPU_READ,1,NULL,0,output,8,&written);
  if(result!=(i==0?-ETIMEDOUT:-EIO)||written||output[0]!=0x7b||!worker_broken||killed!=1||reaped!=1)failures|=1u<<(i+1);
  int spawns=spawned;result=iosvm_gpu_rpc(IOSGPU_PING,0,NULL,0,NULL,0,&written);
  if(result!=-EIO||spawned!=spawns||written)failures|=1u<<6;
 }
 reset(VALIDATION_ERROR);result=iosvm_gpu_rpc(IOSGPU_PING,1,NULL,0,NULL,0,&written);
 if(result!=-EINVAL||written||worker_broken||killed)failures|=1u<<7;
 reset(LOCKED);result=iosvm_gpu_rpc(IOSGPU_PING,0,NULL,0,NULL,0,&written);
 if(result!=-ETIMEDOUT||written||spawned||clock_ms>110)failures|=1u<<8;
 reset(NORMAL);result=iosvm_gpu_rpc(IOSGPU_READ,1,NULL,0,output,IOSGPU_MAX_BYTES+1,&written);
 if(result!=-EINVAL||written||spawned)failures|=1u<<9;
 reset(NEVER_REAP);worker_pid=42;worker_socket=3;break_worker();
 if(!worker_broken||killed!=1||worker_pid!=42||clock_ms>260)failures|=1u<<10;
 if(run_worker(0,0)!=0||backend_calls!=1||outgoing_at!=32)failures|=1u<<11;
 if(run_worker(1,0)!=3||backend_calls)failures|=1u<<12;
 if(run_worker(0,1)!=2||backend_calls)failures|=1u<<13;
 reset(DRIBBLE);result=iosvm_gpu_rpc(IOSGPU_READ,1,NULL,0,output,8,&written);
 if(result!=-ETIMEDOUT||written||killed!=1||!worker_broken)failures|=1u<<14;
 reset(WRITE_STALL);result=iosvm_gpu_rpc(IOSGPU_PING,0,NULL,0,NULL,0,&written);
 if(result!=-ETIMEDOUT||written||killed!=1||!worker_broken)failures|=1u<<15;
 reset(NORMAL);result=iosvm_gpu_rpc(9,0x10000,NULL,0,output,8,&written);
 struct iosgpu_worker_request metal={IOSGPU_WORKER_REQUEST_MAGIC,IOSGPU_WORKER_VERSION,9,0x10000,0,8,1};
 if(result||written!=8||output[0]!=0xa5||!iosgpu_worker_request_valid(&metal,1))failures|=1u<<16;
 reset(SHORT_SUCCESS);memset(output,0x7b,sizeof(output));
 result=iosvm_gpu_rpc(IOSGPU_READ,1,NULL,0,output,8,&written);
 if(result!=-EIO||written||output[0]!=0x7b||!worker_broken||!killed)failures|=1u<<17;
 uint32_t region[]={1,0,0,2,2,8};uint8_t pixels[32];
 reset(SHORT_SUCCESS);memset(pixels,0x7b,sizeof(pixels));
 result=iosvm_gpu_rpc(IOSGPU_RESOURCE_DOWNLOAD,1,region,sizeof(region),pixels,16,&written);
 if(result!=-EIO||written||pixels[0]!=0x7b||pixels[15]!=0x7b||!worker_broken||!killed)failures|=1u<<18;
 reset(REGION_SUCCESS);memset(pixels,0x7b,sizeof(pixels));
 result=iosvm_gpu_rpc(IOSGPU_RESOURCE_DOWNLOAD,1,region,sizeof(region),pixels,sizeof(pixels),&written);
 if(result||written!=16||pixels[0]!=0xa5||pixels[15]!=0xa5||pixels[16]!=0x7b||worker_broken)failures|=1u<<19;
 reset(NORMAL);result=iosvm_gpu_rpc(IOSGPU_READ,1,NULL,0,output,8,&written);
 if(result||written!=8||incoming_size!=sizeof(struct iosgpu_worker_reply))failures|=1u<<20;
 reset(STALE_SHARED);memset(output,0x7b,sizeof(output));
 result=iosvm_gpu_rpc(IOSGPU_READ,1,NULL,0,output,8,&written);
 if(result!=-EIO||written||output[0]!=0x7b||!worker_broken||!killed)failures|=1u<<21;
 int setup_modes[]={MEMFD_FAIL,SEAL_FAIL,MAP_FAIL,WRONG_SHARED_SIZE};
 for(unsigned i=0;i<4;i++){
  reset(setup_modes[i]);result=iosvm_gpu_rpc(IOSGPU_PING,0,NULL,0,NULL,0,&written);
  if(result!=-EIO||written||spawned||!worker_broken)failures|=1u<<(22+i);
 }
 reset(BAD_SHARED_HEADER);memset(output,0x7b,sizeof(output));
 result=iosvm_gpu_rpc(IOSGPU_READ,1,NULL,0,output,8,&written);
 if(result!=-EIO||written||output[0]!=0x7b||!worker_broken||!killed)failures|=1u<<26;
 reset(NORMAL);result=iosvm_gpu_rpc(IOSGPU_READ,1,NULL,0,output,8,&written);
 outgoing_at=incoming_at=incoming_size=0;
 result|=iosvm_gpu_rpc(IOSGPU_READ,1,NULL,0,output,8,&written);
 if(result||written!=8||worker_sequence!=3||worker_shared->sequence!=2||spawned!=1)failures|=1u<<27;
 reset(NORMAL);role=1;
 ((struct iosgpu_shared_response *)(void *)shared_store.bytes)->sequence=9;
 char *argv[]={"/test/libios_gpu_worker.so","--iosgpu-worker","7",NULL};
 if(isolated_worker_main(3,argv)!=2||backend_calls)failures|=1u<<28;
 uint8_t request[8];for(unsigned i=0;i<8;i++)request[i]=(uint8_t)(i+31);
 reset(NORMAL);result=iosvm_gpu_rpc(IOSGPU_METAL_CALL,1,request,8,output,8,&written);
 int mismatch=0;for(unsigned i=0;i<8;i++)if(iosgpu_shared_request_buffer(worker_shared)[i]!=request[i])mismatch=1;
 if(result||written!=8||outgoing_at!=32||mismatch||worker_shared->request_sequence!=1)failures|=1u<<29;
 if(run_worker_upload(0)!=0||backend_calls!=1||backend_request_mismatch||incoming_at!=32||outgoing_at!=32)failures|=1u<<30;
 reset(STALE_REQUEST);memset(output,0x7b,sizeof(output));
 result=iosvm_gpu_rpc(IOSGPU_READ,1,NULL,0,output,8,&written);
 if(result!=-EIO||written||output[0]!=0x7b||!worker_broken||!killed)failures|=1u<<31;
 if(run_worker_upload(1)!=3||backend_calls||outgoing_at)failures|=1u<<31;
 return failures;
}
