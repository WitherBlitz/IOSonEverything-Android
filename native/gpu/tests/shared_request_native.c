/* Real POSIX spawn/memfd integration, authored backend only. AGPL-3.0-or-later. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "../worker_protocol.h"
#ifdef WORKER_BACKEND
int64_t iosgpu_route_call(uint32_t op,uint32_t context,const void *input,uint32_t size,
 void *output,uint32_t capacity,uint32_t *written) {
 *written=0;
 if(fcntl(IOSGPU_WORKER_SHARED_FD,F_GETFD)!=-1||errno!=EBADF)return -EIO;
 if(op==IOSGPU_PING)return IOSGPU_REPLY;
 if(op==IOSGPU_METAL_CALL){
  if(size!=1440u*3120u*4u||capacity!=16||
     (const uint8_t *)input!=(uint8_t *)output+IOSGPU_MAX_BYTES)return -EIO;
  const uint8_t *bytes=input;
  for(uint32_t i=0;i<size;i++)if(bytes[i]!=(uint8_t)(i*11u+context))return -EINVAL;
  for(uint32_t i=0;i<16;i++)((uint8_t *)output)[i]=bytes[i]^0xa5;
  *written=16;return 0;
 }
 if(op==IOSGPU_READ){
  if(context==2){memset(output,0xee,capacity/2);_exit(23);}
  if(context==3){memset(output,0xee,capacity/2);return -EIO;}
  if(context==4){memset(output,0xee,capacity/2);return -EINVAL;}
  uint8_t *p=output;for(uint32_t i=0;i<capacity;i++)p[i]=(uint8_t)(i*17u+context);
  *written=capacity;return 0;
 }
 if(op==IOSGPU_RESOURCE_DOWNLOAD){
  if(size!=24||capacity!=32)return -EINVAL;
  const uint32_t *a=input;if(a[3]!=2||a[4]!=2||a[5]!=12)return -EINVAL;
  memset(output,0x31,8);memset((uint8_t *)output+12,0x72,8);*written=20;return 0;
 }
 return -EINVAL;
}
#else
#include "../bridge.c"
int __android_log_print(int priority,const char *tag,const char *format,...){(void)priority;(void)tag;(void)format;return 0;}
static unsigned checks,failures;
static void check(int yes,const char *label){checks++;if(!yes){failures++;fprintf(stderr,"FAIL %s\n",label);}}
static int unchanged(const uint8_t *p,size_t n){for(size_t i=0;i<n;i++)if(p[i]!=0x7b)return 0;return 1;}
int main(int argc,char **argv){
 if(argc!=2)return 2;alarm(15);uint32_t written;int64_t result;
 if(!strcmp(argv[1],"normal")||!strcmp(argv[1],"negative")){
  result=iosvm_gpu_rpc(IOSGPU_PING,0,NULL,0,NULL,0,&written);
  check(result==IOSGPU_REPLY&&!written,"ping");
  enum{SIZE=1440*3120*4};uint8_t *out=malloc(SIZE+64);if(!out)return 2;
  uint8_t *input=malloc(SIZE+64);if(!input)return 2;
  for(unsigned frame=0;frame<3;frame++){
   memset(input,0x7b,SIZE+64);memset(out,0x7b,64);
   for(unsigned i=0;i<SIZE;i++)input[32+i]=(uint8_t)(i*11u+200+frame);
   result=iosvm_gpu_rpc(IOSGPU_METAL_CALL,200+frame,input+32,SIZE,out+32,16,&written);
   check(result==0&&written==16,"backend consumed exact non-overlapping mapped request payload");
   unsigned bad=0;for(unsigned i=0;i<16;i++)if(out[32+i]!=(uint8_t)(input[32+i]^0xa5))bad++;
   check(!bad&&unchanged(out,32)&&unchanged(out+48,16),"upload reply and destination guards");
   bad=0;for(unsigned i=0;i<SIZE;i++)if(input[32+i]!=(uint8_t)(i*11u+200+frame))bad++;
   check(!bad&&unchanged(input,32)&&unchanged(input+32+SIZE,32),"request bytes and source guards remain unchanged");
  }
  free(input);
  for(unsigned frame=0;frame<3;frame++){
   memset(out,0x7b,SIZE+64);result=iosvm_gpu_rpc(IOSGPU_READ,100+frame,NULL,0,out+32,SIZE,&written);
   check(result==0&&written==SIZE,"full read size");
   unsigned bad=0;for(unsigned i=0;i<SIZE;i++){
    uint8_t expected=(uint8_t)(i*17u+100+frame);
    if(!strcmp(argv[1],"negative")&&frame==1&&i==731)expected^=8;
    if(out[32+i]!=expected)bad++;
   }
   check(bad==0,"every byte");check(unchanged(out,32)&&unchanged(out+32+SIZE,32),"tail guards");
   check(worker_sequence==frame+6,"successive release/acquire generation");
  }
  uint32_t region[]={1,0,0,2,2,12};memset(out,0x7b,32);
  result=iosvm_gpu_rpc(IOSGPU_RESOURCE_DOWNLOAD,1,region,sizeof(region),out,32,&written);
  check(result==0&&written==20,"padded rectangle span in excess capacity");
  for(unsigned i=0;i<20;i++)check(out[i]==(i<8?0x31:i<12?0:0x72),"rows and reset padding");
  check(unchanged(out+20,12),"unpublished excess capacity");
  memset(out,0x7b,64);result=iosvm_gpu_rpc(IOSGPU_READ,4,NULL,0,out,64,&written);
  check(result==-EINVAL&&!written&&unchanged(out,64)&&!worker_broken,"semantic error preserves destination");
  result=iosvm_gpu_rpc(IOSGPU_PING,0,NULL,0,NULL,0,&written);
  check(result==IOSGPU_REPLY&&!written&&!worker_broken,"semantic error remains nonfatal");free(out);
 }else if(!strcmp(argv[1],"die")||!strcmp(argv[1],"fatal")){
  uint8_t out[64];memset(out,0x7b,sizeof(out));
  result=iosvm_gpu_rpc(IOSGPU_READ,!strcmp(argv[1],"die")?2:3,NULL,0,out,sizeof(out),&written);
  check(result==-EIO&&!written&&unchanged(out,sizeof(out)),"partial shared response never publishes");
  check(worker_broken&&!worker_shared&&worker_socket<0,"broken resources released");
  result=iosvm_gpu_rpc(IOSGPU_PING,0,NULL,0,NULL,0,&written);
  check(result==-EIO&&!written,"broken worker cannot respawn");
 }else return 2;
 break_worker();check(!worker_shared&&worker_socket<0&&worker_pid<0,"mapping closed and worker reaped");
 printf("SHARED_NATIVE_RESULT mode=%s checks=%u failures=%u\n",argv[1],checks,failures);
 return failures?1:0;
}
#endif
