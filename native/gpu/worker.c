/* Renderer process entry point. SPDX-License-Identifier: AGPL-3.0-or-later. */
#define _GNU_SOURCE
#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>
#include "renderer.h"
#include "worker_protocol.h"
#include "worker_shared.h"
#include "snapshot_backend.h"
static int worker_exact_io(void *buffer,size_t size,int sending) {
 uint8_t *at=buffer;
 while(size){
  ssize_t n=sending?send(IOSGPU_WORKER_FD,at,size,MSG_NOSIGNAL):recv(IOSGPU_WORKER_FD,at,size,0);
  if(n<0){if(errno==EINTR)continue;return -1;}
  if(!n)return -1;
  at+=(size_t)n;size-=(size_t)n;
 }
 return 0;
}
static int worker_loop(struct iosgpu_shared_response *shared) {
 uint64_t sequence=1;
 while(sequence){
  struct iosgpu_worker_request request;
  if(worker_exact_io(&request,sizeof(request),0))return 0;
  if(!iosgpu_worker_request_valid(&request,sequence))return 3;
  if(!iosgpu_shared_request_ready(shared,sequence))return 3;
  const uint8_t *input=request.size?iosgpu_shared_request_buffer(shared):NULL;
  uint8_t *output=request.capacity?shared->bytes:NULL;
  atomic_store_explicit(&shared->sequence,0,memory_order_release);
  if(request.capacity)memset(output,0,request.capacity);
  uint32_t written=0;
  int64_t result=iosgpu_route_call(request.operation,request.context,input,request.size,
   output,request.capacity,&written);
  if(written>request.capacity||(result<0&&written))return 3;
  if(result<0){static unsigned refused;refused++;if(refused<=12||refused%1000==0)fprintf(stderr,"IOSGPU_WORKER_REFUSED count=%u op=%u context=%u result=%lld\n",refused,request.operation,request.context,(long long)result);}
  struct iosgpu_worker_reply reply={IOSGPU_WORKER_REPLY_MAGIC,IOSGPU_WORKER_VERSION,
   sequence,result,written,0};
  atomic_store_explicit(&shared->sequence,sequence,memory_order_release);
  int failed=worker_exact_io(&reply,sizeof(reply),1);
  if(failed)return 0;
  sequence++;
 }
 return 3;
}
int main(int argc,char **argv) {
 if(argc!=3||strcmp(argv[1],"--iosgpu-worker"))return 2;
 char *end=NULL;errno=0;long parent=strtol(argv[2],&end,10);
 if(errno||!end||*end||parent<=1||parent>INT_MAX)return 2;
 if(getppid()!=(pid_t)parent||prctl(PR_SET_PDEATHSIG,SIGKILL)||getppid()!=(pid_t)parent)return 2;
 int type=0;socklen_t type_size=sizeof(type);
 if(getsockopt(IOSGPU_WORKER_FD,SOL_SOCKET,SO_TYPE,&type,&type_size)||type!=SOCK_STREAM)return 2;
 struct iosgpu_shared_response *shared=iosgpu_shared_map(IOSGPU_WORKER_SHARED_FD,0);
 close(IOSGPU_WORKER_SHARED_FD);
 if(!shared)return 2;
 int result=worker_loop(shared);munmap(shared,IOSGPU_SHARED_SIZE);
 uint64_t stats[8];iosgpu_backend_snapshot_stats(stats);
 fprintf(stderr,"IOSGPU_WORKER_FINAL result=%d published=%llu resolved=%llu dropped=%llu live=%llu charged=%llu copies=%llu imports=%llu reuses=%llu\n",result,(unsigned long long)stats[0],(unsigned long long)stats[1],(unsigned long long)stats[2],(unsigned long long)stats[3],(unsigned long long)stats[4],(unsigned long long)stats[5],(unsigned long long)stats[6],(unsigned long long)stats[7]);
 /* This expendable process owns all renderer storage. Process-global gfxstream
  * C++ destructors can race its render threads; let process teardown retire
  * the driver contexts, including deliberately retained poisoned storage. */
 _exit(result);
}
