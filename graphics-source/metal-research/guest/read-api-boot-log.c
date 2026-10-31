/* Authored reader for one owned test log only. SPDX-License-Identifier: AGPL-3.0-or-later */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/mount.h>
#include <sys/wait.h>
#include <unistd.h>
static int run(char *const argv[]){pid_t child=fork();if(child<0)return -1;if(child==0){execv(argv[0],argv);_exit(127);}int status=0;if(waitpid(child,&status,0)!=child)return -1;return WIFEXITED(status)?WEXITSTATUS(status):-1;}
static int read_log(const char *path){
 int fd=open(path,O_RDONLY|O_NOFOLLOW);if(fd<0){printf("METAL_API_BOOT_LOG_READ pass=false open_errno=%d\n",errno);return 1;}
 struct stat state;if(fstat(fd,&state)){close(fd);puts("METAL_API_BOOT_LOG_READ pass=false reason=fstat");return 1;}
 printf("METAL_API_BOOT_LOG_METADATA uid=%u mode=%o bytes=%lld mtime=%lld\n",state.st_uid,state.st_mode,(long long)state.st_size,(long long)state.st_mtimespec.tv_sec);
 if(!S_ISREG(state.st_mode)||state.st_uid!=0||state.st_size<=0||state.st_size>65536){close(fd);puts("METAL_API_BOOT_LOG_READ pass=false reason=metadata");return 1;}
 char bytes[65537];size_t used=0;while(used<(size_t)state.st_size){ssize_t n=read(fd,bytes+used,(size_t)state.st_size-used);if(n<=0){close(fd);puts("METAL_API_BOOT_LOG_READ pass=false reason=short-read");return 1;}used+=(size_t)n;}
 close(fd);bytes[used]=0;
 int pass=strstr(bytes,"METAL_API_RESULT pass=true checks=157 failures=0")&&strstr(bytes,"published_on_main=1")&&strstr(bytes,"METAL_API_COMMAND_STREAM setters=257 reverse_commit=true callback_reentrant=true mismatches=0");
 printf("METAL_API_BOOT_LOG_BEGIN bytes=%zu mtime=%lld\n%s\nMETAL_API_BOOT_LOG_READ pass=%s uid=%u bytes=%zu\n",used,(long long)state.st_mtimespec.tv_sec,bytes,pass?"true":"false",getuid(),used);fflush(NULL);return pass?0:1;
}
int main(int argc,char **argv){
 if(argc>2||(argc==2&&strcmp(argv[1],"--clear")))return 2;int clear=argc==2;alarm(20);
 // This executable runs in recovery, outside the System-volume chroot.
 // Its one known Data volume is normally mounted only after the patch hook.
 if(mkdir("/mnt8",0755)&&errno!=EEXIST)return 2;
 char *mount_args[]={"/sbin/mount_apfs","-o",clear?"rw":"ro","/dev/disk0s1s2","/mnt8",NULL};
 int mounted=run(mount_args);printf("METAL_API_BOOT_LOG_DATA_MOUNT status=%d readonly=%u\n",mounted,!clear);fflush(NULL);if(mounted)return 2;
 const char *path="/mnt8/tmp/IOSMetalAPI-direct-readback.log";int result;
 if(clear){result=unlink(path);if(result&&errno==ENOENT)result=0;printf("METAL_API_BOOT_LOG_CLEAR pass=%s data_volume=true\n",result?"false":"true");}
 else result=read_log(path);
 int unmounted=unmount("/mnt8",0);printf("METAL_API_BOOT_LOG_DATA_UNMOUNT status=%d errno=%d\n",unmounted,unmounted?errno:0);fflush(NULL);return result||unmounted?1:0;
}
