/* Read only this project's exact two logs from the stopped lab's Data volume. */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
static int execute(const char *path,char *const args[]){int child=fork();if(child<0)return 1;if(!child){execv(path,args);_exit(127);}int status=0;if(waitpid(child,&status,0)!=child)return 1;return status;}
static int read_log(const char *path){
 int fd=open(path,O_RDONLY|O_NOFOLLOW);if(fd<0){printf("OWNED_LOG_MISSING path=%s errno=%d\n",path,errno);return 1;}
 struct stat st;if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_size<0||st.st_size>64*1024*1024){close(fd);return 1;}
 off_t offset=st.st_size>262144?st.st_size-262144:0;if(lseek(fd,offset,SEEK_SET)!=offset){close(fd);return 1;}
 printf("OWNED_LOG_BEGIN path=%s bytes=%lld offset=%lld\n",path,(long long)st.st_size,(long long)offset);fflush(NULL);
 char data[4096];size_t total=0;while(total<262144){ssize_t n=read(fd,data,sizeof(data));if(n<0){close(fd);return 1;}if(!n)break;if(fwrite(data,1,(size_t)n,stdout)!=(size_t)n){close(fd);return 1;}total+=(size_t)n;}
 close(fd);printf("\nOWNED_LOG_END bytes=%zu\n",total);fflush(NULL);return 0;
}
int main(void){alarm(40);if(getuid()!=0)return 1;
 char *mount_args[]={"/sbin/mount_apfs","-o","rdonly","/dev/disk0s1s2","/mnt8",NULL};int mounted=execute(mount_args[0],mount_args);printf("OWNED_LOG_DATA_MOUNT read_only=true status=%d\n",mounted);fflush(NULL);if(mounted)return 1;
 int result=read_log("/mnt8/mobile/iosgpu-backboardd-job-macro-scope-v2.log");result|=read_log("/mnt8/mobile/Containers/Data/Application/694E3184-23DB-4FC8-BCFA-374C86780D8F/Library/Logs/IOSMetalVisible.log");
 char *unmount_args[]={"/sbin/umount","/mnt8",NULL};int unmounted=execute(unmount_args[0],unmount_args);printf("OWNED_LOG_DATA_UNMOUNT status=%d\n",unmounted);result|=unmounted;
 printf("OWNED_LOG_RESULT pass=%s\n",result?"false":"true");if(!result)puts("GPUPREP lab tool installation PASSED");fflush(NULL);return result?1:0;
}
