/* Authored bounded reader for this test application's diagnostic only. */
#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static unsigned found;
static void read_owned_compositor_tail(const char *path){
 int fd=open(path,O_RDONLY|O_NOFOLLOW);if(fd<0)return;struct stat info;
 if(fstat(fd,&info)||!S_ISREG(info.st_mode)||info.st_size<0||info.st_size>512*1024*1024){close(fd);return;}
 off_t offset=info.st_size>65536?info.st_size-65536:0;
 if(lseek(fd,offset,SEEK_SET)!=offset){close(fd);return;}
 char data[65537];size_t used=0;while(used<65536){ssize_t n=read(fd,data+used,65536-used);if(n<=0)break;used+=(size_t)n;}close(fd);data[used]=0;found++;
 printf("GLES_COMPOSITOR_OWN_TAIL path=%s size=%lld offset=%lld bytes=%zu\n%s\n",path,(long long)info.st_size,(long long)offset,used,data);fflush(NULL);
}
static void read_log(const char *path){
 int fd=open(path,O_RDONLY|O_NOFOLLOW);if(fd<0)return;struct stat info;
 if(fstat(fd,&info)||!S_ISREG(info.st_mode)||info.st_size<0||info.st_size>65536){close(fd);return;}
 char data[65537];size_t used=0;while(used<65536){ssize_t n=read(fd,data+used,65536-used);if(n<=0)break;used+=(size_t)n;}close(fd);data[used]=0;found++;
 printf("METAL_VISIBLE_OWN_LOG path=%s bytes=%zu\n%s\n",path,used,data);fflush(NULL);
}
int main(void){
 alarm(20);
 read_owned_compositor_tail("/mnt8/mobile/iosgpu-backboardd-job-macro-scope-v2.log");
 read_owned_compositor_tail("/mnt8/private/var/mobile/iosgpu-backboardd-job-macro-scope-v2.log");
 read_owned_compositor_tail("/mnt9/private/var/mobile/iosgpu-backboardd-job-macro-scope-v2.log");
 const char *roots[]={"/mnt8/mobile/Containers/Data/Application","/mnt8/private/var/mobile/Containers/Data/Application","/mnt9/private/var/mobile/Containers/Data/Application"};
 for(unsigned i=0;i<sizeof(roots)/sizeof(roots[0]);i++){
  DIR *directory=opendir(roots[i]);printf("METAL_VISIBLE_LOG_ROOT index=%u available=%u\n",i,directory!=NULL);if(!directory)continue;
  struct dirent *entry;unsigned count=0;while(count++<512&&(entry=readdir(directory))){if(entry->d_name[0]=='.'||strchr(entry->d_name,'/'))continue;
   char path[2048];int n=snprintf(path,sizeof(path),"%s/%s/Library/Logs/IOSMetalVisible.log",roots[i],entry->d_name);if(n>0&&(size_t)n<sizeof(path))read_log(path);
  }closedir(directory);
 }
 read_log("/mnt8/mobile/Library/Logs/IOSMetalVisible.log");read_log("/mnt8/root/Library/Logs/IOSMetalVisible.log");
 printf("METAL_VISIBLE_DIAGNOSTIC_DONE files=%u\n",found);fflush(NULL);return found?0:1;
}
