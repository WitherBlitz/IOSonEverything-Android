/* Follow only this project's two diagnostic files during a normal lab boot. */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>
static const char *paths[]={
 "/private/var/mobile/iosgpu-backboardd-job-macro-scope-v2.log",
 "/var/mobile/Containers/Data/Application/694E3184-23DB-4FC8-BCFA-374C86780D8F/Library/Logs/IOSMetalVisible.log"};
int main(void){
 alarm(800);setvbuf(stdout,NULL,_IOLBF,0);off_t offsets[2]={0,0};int opened[2]={0,0};
 puts("CONNECTION_LOG_FOLLOW normal_boot=true paths=2 read_only=true");
 for(unsigned tick=0;tick<750;tick++){
  for(unsigned i=0;i<2;i++){
   int fd=open(paths[i],O_RDONLY|O_NOFOLLOW);if(fd<0){if(tick%60==0)printf("CONNECTION_LOG_WAIT index=%u errno=%d\n",i,errno);continue;}
   struct stat st;if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_size<0||st.st_size>64*1024*1024){close(fd);continue;}
   if(!opened[i]){offsets[i]=st.st_size>65536?st.st_size-65536:0;opened[i]=1;}
   if(st.st_size<offsets[i])offsets[i]=0;
   if(st.st_size>offsets[i]&&lseek(fd,offsets[i],SEEK_SET)==offsets[i]){
    printf("CONNECTION_LOG_BEGIN index=%u offset=%lld\n",i,(long long)offsets[i]);
    char data[4096];size_t count=0;while(count<65536){ssize_t n=read(fd,data,sizeof(data));if(n<=0)break;fwrite(data,1,(size_t)n,stdout);count+=(size_t)n;offsets[i]+=n;}
    printf("\nCONNECTION_LOG_END index=%u bytes=%zu\n",i,count);
   }
   close(fd);
  }
  sleep(1);
 }
 printf("CONNECTION_LOG_RESULT files=%d\n",opened[0]+opened[1]);return !(opened[0]&&opened[1]);
}
