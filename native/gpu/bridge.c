/* Bounded exec-worker proxy. SPDX-License-Identifier: AGPL-3.0-or-later. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <android/log.h>
#include "worker_protocol.h"
#include "worker_shared.h"
#ifndef IOSGPU_RPC_TIMEOUT_MS
#define IOSGPU_RPC_TIMEOUT_MS 10000u
#endif
#define IOSGPU_REAP_TIMEOUT_MS 250u
extern char **environ;
static pthread_mutex_t proxy_mutex=PTHREAD_MUTEX_INITIALIZER;
static pid_t worker_pid=-1;
static int worker_socket=-1,worker_broken;
static uint64_t worker_sequence=1;
static struct iosgpu_shared_response *worker_shared;
/* Opt-in aggregate timing only; never inspect command payloads or guest addresses. */
static int perf_enabled=-1;
static uint64_t perf_since;
static struct {uint64_t calls,ns,in_bytes,out_bytes;} perf_ops[IOSGPU_METAL_CALL+1];
static uint64_t perf_now(void) {
 struct timespec now;if(clock_gettime(CLOCK_MONOTONIC,&now))return 0;
 return (uint64_t)now.tv_sec*1000000000u+(uint64_t)now.tv_nsec;
}
/* All profiler state, including the one-time environment read, is under proxy_mutex. */
static uint64_t perf_begin(void) {
 if(perf_enabled<0){perf_enabled=0;for(unsigned i=0;environ[i];i++)
  if(!strcmp(environ[i],"IOSVM_GPU_PROFILE=1")){perf_enabled=1;break;}}
 return perf_enabled?perf_now():0;
}
static void perf_end(uint32_t operation,uint32_t size,uint32_t written,uint64_t began) {
 if(!began)return;uint64_t now=perf_now();if(now<began)return;
 if(!perf_since)perf_since=began;
 perf_ops[operation].calls++;perf_ops[operation].ns+=now-began;
 perf_ops[operation].in_bytes+=size;perf_ops[operation].out_bytes+=written;
 if(now-perf_since<5000000000u)return;
 for(unsigned i=0;i<=IOSGPU_METAL_CALL;i++)if(perf_ops[i].calls){
  __android_log_print(ANDROID_LOG_INFO,"IosGpuPerf",
   "op=%u calls=%llu avg_us=%llu total_us=%llu in_bytes=%llu out_bytes=%llu span_ms=%llu",
   i,(unsigned long long)perf_ops[i].calls,
   (unsigned long long)(perf_ops[i].ns/perf_ops[i].calls/1000u),
   (unsigned long long)(perf_ops[i].ns/1000u),(unsigned long long)perf_ops[i].in_bytes,
   (unsigned long long)perf_ops[i].out_bytes,(unsigned long long)((now-perf_since)/1000000u));
 }
 memset(perf_ops,0,sizeof(perf_ops));perf_since=now;
}
static int64_t monotonic_ms(void) {
 struct timespec now;
 if(clock_gettime(CLOCK_MONOTONIC,&now))return -1;
 return (int64_t)now.tv_sec*1000+now.tv_nsec/1000000;
}
static int remaining_ms(int64_t deadline) {
 int64_t now=monotonic_ms();
 if(now<0)return -EIO;
 if(now>=deadline)return 0;
 return deadline-now>INT_MAX?INT_MAX:(int)(deadline-now);
}
static int exact_io(int fd,void *buffer,size_t size,int sending,int64_t deadline) {
 uint8_t *at=buffer;
 while(size){
  int left=remaining_ms(deadline);if(left<=0)return left<0?left:-ETIMEDOUT;
  struct pollfd p={fd,sending?POLLOUT:POLLIN,0};
  int ready=poll(&p,1,left);
  if(ready<0){if(errno==EINTR)continue;return -EIO;}
  if(!ready)return -ETIMEDOUT;
  if(p.revents&POLLNVAL)return -EIO;
  if(!(p.revents&(sending?POLLOUT:POLLIN))){
   if(p.revents&(POLLERR|POLLHUP))return -EIO;
   continue;
  }
  ssize_t n=sending?send(fd,at,size,MSG_DONTWAIT|MSG_NOSIGNAL):recv(fd,at,size,MSG_DONTWAIT);
  if(n<0){if(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK)continue;return -EIO;}
  if(!n)return -EIO;
  at+=(size_t)n;size-=(size_t)n;
 }
 return 0;
}
/* A kernel-stuck child cannot be allowed to replace a deadline with blocking
 * waitpid. It is killed, then reaped here or on a later broken-session call. */
static void reap_worker(int wait_briefly) {
 if(worker_pid<=0)return;
 int64_t now=monotonic_ms(),end=now<0?0:now+IOSGPU_REAP_TIMEOUT_MS;
 for(;;){
  pid_t got=waitpid(worker_pid,NULL,WNOHANG);
  if(got==worker_pid||(got<0&&errno==ECHILD)){worker_pid=-1;return;}
  if(got<0&&errno!=EINTR)return;
  if(!wait_briefly||remaining_ms(end)<=0)return;
  (void)poll(NULL,0,2);
 }
}
static void break_worker(void) {
 worker_broken=1;
 if(worker_socket>=0){close(worker_socket);worker_socket=-1;}
 if(worker_pid>0)(void)kill(worker_pid,SIGKILL);
 reap_worker(1);
 if(worker_shared){munmap(worker_shared,IOSGPU_SHARED_SIZE);worker_shared=NULL;}
}
static char **worker_environment(const char *directory,size_t directory_size) {
 size_t count=0,used=0;while(environ[count])count++;
 char **copy=calloc(count+2,sizeof(*copy));if(!copy)return NULL;
 for(size_t i=0;i<count;i++){
  if(!strncmp(environ[i],"LD_PRELOAD=",11)||!strncmp(environ[i],"IOSVM_WRITER_",13)||
     !strncmp(environ[i],"LD_LIBRARY_PATH=",16))continue;
  copy[used]=strdup(environ[i]);
  if(!copy[used]){while(used)free(copy[--used]);free(copy);return NULL;}
  used++;
 }
 /* An exec child has no Java classloader namespace. Its packaged gfxstream
  * runtime dependencies must resolve beside the worker, not through the VMM's
  * inherited loader path. Only this child's environment is changed. */
 static const char prefix[]="LD_LIBRARY_PATH=";
 copy[used]=malloc(sizeof(prefix)+directory_size);
 if(!copy[used]){while(used)free(copy[--used]);free(copy);return NULL;}
 memcpy(copy[used],prefix,sizeof(prefix)-1);
 memcpy(copy[used]+sizeof(prefix)-1,directory,directory_size);
 copy[used][sizeof(prefix)-1+directory_size]=0;
 return copy;
}
static void free_environment(char **copy) {
 if(copy){for(size_t i=0;copy[i];i++)free(copy[i]);free(copy);}
}
__attribute__((visibility("default"))) int64_t iosvm_gpu_rpc(uint32_t,uint32_t,
 const void *,uint32_t,void *,uint32_t,uint32_t *);
static int start_worker(void) {
 Dl_info info;char path[4096],parent[32];
 if(!dladdr((void *)iosvm_gpu_rpc,&info)||!info.dli_fname)return -EIO;
 const char *slash=strrchr(info.dli_fname,'/');
 static const char name[]="/libios_gpu_worker.so";
 if(!slash||(size_t)(slash-info.dli_fname)>sizeof(path)-sizeof(name))return -EIO;
 snprintf(path,sizeof(path),"%.*s%s",(int)(slash-info.dli_fname),info.dli_fname,name);
 snprintf(parent,sizeof(parent),"%ld",(long)getpid());
 char **child_environment=worker_environment(info.dli_fname,(size_t)(slash-info.dli_fname));
 if(!child_environment)return -EIO;
 int sockets[2]={-1,-1};
 if(socketpair(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0,sockets)){
  free_environment(child_environment);return -EIO;
 }
 int shared_fd=-1;
 struct iosgpu_shared_response *shared=iosgpu_shared_create(&shared_fd);
 if(!shared){close(sockets[0]);close(sockets[1]);free_environment(child_environment);return -EIO;}
 /* Both dup sources must survive installing fd3 and fd4, including when the
  * process started with either destination unused. */
 if(sockets[1]<=IOSGPU_WORKER_SHARED_FD){
  int moved=fcntl(sockets[1],F_DUPFD_CLOEXEC,IOSGPU_WORKER_SHARED_FD+1);
  if(moved<0){close(shared_fd);munmap(shared,IOSGPU_SHARED_SIZE);close(sockets[0]);close(sockets[1]);free_environment(child_environment);return -EIO;}
  close(sockets[1]);sockets[1]=moved;
 }
 if(shared_fd<=IOSGPU_WORKER_SHARED_FD){
  int moved=fcntl(shared_fd,F_DUPFD_CLOEXEC,IOSGPU_WORKER_SHARED_FD+1);
  if(moved<0){close(shared_fd);munmap(shared,IOSGPU_SHARED_SIZE);close(sockets[0]);close(sockets[1]);free_environment(child_environment);return -EIO;}
  close(shared_fd);shared_fd=moved;
 }
 posix_spawn_file_actions_t actions;
 int initialized=posix_spawn_file_actions_init(&actions)==0;
 int code=initialized?0:EIO;
 if(!code)code=posix_spawn_file_actions_addclose(&actions,sockets[0]);
 if(!code)code=posix_spawn_file_actions_adddup2(&actions,sockets[1],IOSGPU_WORKER_FD);
 if(!code)code=posix_spawn_file_actions_adddup2(&actions,shared_fd,IOSGPU_WORKER_SHARED_FD);
 if(!code)code=posix_spawn_file_actions_addclose(&actions,sockets[1]);
 if(!code)code=posix_spawn_file_actions_addclose(&actions,shared_fd);
 char *arguments[]={path,"--iosgpu-worker",parent,NULL};
 pid_t child=-1;
 if(!code)code=posix_spawn(&child,path,&actions,NULL,arguments,child_environment);
 if(initialized)posix_spawn_file_actions_destroy(&actions);
 close(sockets[1]);close(shared_fd);free_environment(child_environment);
 if(code){close(sockets[0]);munmap(shared,IOSGPU_SHARED_SIZE);return -EIO;}
 worker_pid=child;worker_socket=sockets[0];worker_shared=shared;
 int flags=fcntl(worker_socket,F_GETFL);
 if(flags<0||fcntl(worker_socket,F_SETFL,flags|O_NONBLOCK)){break_worker();return -EIO;}
 return 0;
}
static int take_proxy_lock(int64_t deadline) {
 for(;;){
  int code=pthread_mutex_trylock(&proxy_mutex);
  if(!code)return 0;
  if(code!=EBUSY)return -EIO;
  int left=remaining_ms(deadline);if(left<=0)return left<0?left:-ETIMEDOUT;
  (void)poll(NULL,0,1);
 }
}
__attribute__((visibility("default"))) int64_t iosvm_gpu_rpc(uint32_t operation,uint32_t context,
 const void *request,uint32_t size,void *reply,uint32_t capacity,uint32_t *written) {
 if(!written)return -EINVAL;
 *written=0;
 if(operation>IOSGPU_METAL_CALL||size>IOSGPU_MAX_BYTES||capacity>IOSGPU_MAX_BYTES||
    (size&&!request)||(capacity&&!reply))return -EINVAL;
 int64_t now=monotonic_ms();if(now<0)return -EIO;
 int64_t deadline=now+IOSGPU_RPC_TIMEOUT_MS;
 int code=take_proxy_lock(deadline);if(code)return code;
 uint64_t perf_began=perf_begin();
 int64_t result=-EIO;
 if(worker_broken){reap_worker(0);goto done;}
 if(worker_socket<0&&(code=start_worker()))goto failed;
 if(!worker_sequence){code=-EIO;goto failed;}
 struct iosgpu_worker_request outgoing={IOSGPU_WORKER_REQUEST_MAGIC,IOSGPU_WORKER_VERSION,
  operation,context,size,capacity,worker_sequence};
 if(!worker_shared||!iosgpu_shared_header_valid(worker_shared)){code=-EIO;goto failed;}
 if(size)memcpy(iosgpu_shared_request_buffer(worker_shared),request,size);
 atomic_store_explicit(&worker_shared->request_sequence,worker_sequence,memory_order_release);
 code=exact_io(worker_socket,&outgoing,sizeof(outgoing),1,deadline);
 struct iosgpu_worker_reply incoming;
 if(!code)code=exact_io(worker_socket,&incoming,sizeof(incoming),0,deadline);
 if(code)goto failed;
 if(!iosgpu_worker_reply_valid(&incoming,worker_sequence,capacity)){code=-EIO;goto failed;}
 /* Fixed-length reads must be complete before any destination is published.
  * A resource caller may provide excess capacity, so validate its region span. */
 if(incoming.result>=0){
  if(operation==IOSGPU_READ&&incoming.written!=capacity){code=-EIO;goto failed;}
  if(operation==IOSGPU_RESOURCE_DOWNLOAD){
   uint32_t region[6];
   if(size!=sizeof(region)){code=-EIO;goto failed;}
   memcpy(region,request,sizeof(region));
   uint64_t row=(uint64_t)region[3]*4u;
   uint64_t span=region[4]?((uint64_t)region[4]-1u)*region[5]+row:0;
   if(!row||!region[4]||region[5]<row||span>capacity||incoming.written!=span){code=-EIO;goto failed;}
  }
 }
 /* The worker publishes a generation only after completing the output. A
  * failed/partial response is never copied into the caller's destination. */
 if(!worker_shared||!iosgpu_shared_ready(worker_shared,worker_sequence)||
    !iosgpu_shared_request_ready(worker_shared,worker_sequence)){code=-EIO;goto failed;}
 int left=remaining_ms(deadline);
 if(left<=0){code=left<0?left:-ETIMEDOUT;goto failed;}
 if(incoming.result==-EIO||incoming.result==-EPROTO||incoming.result==-ETIMEDOUT){
  code=incoming.result==-ETIMEDOUT?-ETIMEDOUT:-EIO;goto failed;
 }
 if(incoming.written)memcpy(reply,worker_shared->bytes,incoming.written);
 *written=incoming.written;result=incoming.result;worker_sequence++;goto done;
failed:
 break_worker();result=code==-ETIMEDOUT?-ETIMEDOUT:-EIO;
done:
 perf_end(operation,size,*written,perf_began);pthread_mutex_unlock(&proxy_mutex);return result;
}
