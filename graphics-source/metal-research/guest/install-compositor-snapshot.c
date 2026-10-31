/* Update only our three authored guest libraries in the stopped lab clone.
 * Preserve exact previous bytes and refuse unknown content. AGPL-3.0-or-later */
#include <CommonCrypto/CommonDigest.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "compositor-payloads.inc"
struct item {const char *name;const unsigned char *bytes;size_t size;const char **allowed;};
static struct item items[]={{"iosgpu-compositor.dylib",compositor,sizeof(compositor),gles_allowed},{"iosgpu-compositor-arm64e.dylib",compositor,sizeof(compositor),gles_allowed},{"iosmetal-driver.dylib",driver,sizeof(driver),metal_allowed}};
static int digest(const unsigned char *data,size_t size,const char *hex){unsigned char d[32];char text[65];CC_SHA256(data,(CC_LONG)size,d);for(unsigned n=0;n<32;n++)snprintf(text+n*2,3,"%02x",d[n]);return !strcmp(text,hex);}
static unsigned char *load(const char *path,size_t *size,int absent){
 int fd=open(path,O_RDONLY|O_NOFOLLOW);if(fd<0){if(absent&&errno==ENOENT){*size=0;return NULL;}return NULL;}
 struct stat st;if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_uid||st.st_size<=0||st.st_size>2*1024*1024){close(fd);return NULL;}
 unsigned char *data=malloc((size_t)st.st_size);if(!data){close(fd);return NULL;}size_t at=0;
 while(at<(size_t)st.st_size){ssize_t n=read(fd,data+at,(size_t)st.st_size-at);if(n<=0){free(data);close(fd);return NULL;}at+=(size_t)n;}close(fd);*size=at;return data;
}
static int allowed(struct item *item,const unsigned char *data,size_t size){if(size==item->size&&!memcmp(data,item->bytes,size))return 1;for(unsigned n=0;item->allowed[n];n++)if(digest(data,size,item->allowed[n]))return 1;return 0;}
static int save(const char *path,const unsigned char *data,size_t size){
 char temp[512];if(snprintf(temp,sizeof(temp),"%s.snapshot-new",path)>=(int)sizeof(temp))return 1;
 int fd=open(temp,O_CREAT|O_EXCL|O_WRONLY|O_NOFOLLOW,0755);if(fd<0)return 1;size_t at=0;int bad=0;
 while(at<size){ssize_t n=write(fd,data+at,size-at);if(n<=0){bad=1;break;}at+=(size_t)n;}
 if(!bad&&(fchmod(fd,0755)||fsync(fd)))bad=1;if(close(fd))bad=1;if(!bad&&rename(temp,path))bad=1;if(bad)unlink(temp);return bad;
}
static int run(void){
 struct stat st;const char *dirs[]={"/mnt9","/mnt9/usr","/mnt9/usr/lib"};
 for(unsigned n=0;n<3;n++)if(lstat(dirs[n],&st)||!S_ISDIR(st.st_mode)||st.st_uid)return 10;
 unsigned char *original[3]={0};size_t sizes[3]={0};char targets[3][256],backups[3][320];
 for(unsigned n=0;n<3;n++){
  snprintf(targets[n],sizeof(targets[n]),"/mnt9/usr/lib/%s",items[n].name);snprintf(backups[n],sizeof(backups[n]),"%s.before-compositor-snapshots",targets[n]);
  original[n]=load(targets[n],&sizes[n],0);if(!original[n]||!allowed(&items[n],original[n],sizes[n]))return 20+(int)n;
  size_t size=SIZE_MAX;unsigned char *backup=load(backups[n],&size,1);if(size!=0&&(!backup||!allowed(&items[n],backup,size)))return 30+(int)n;free(backup);
 }
 for(unsigned n=0;n<3;n++){
  if(lstat(backups[n],&st)){if(errno!=ENOENT||save(backups[n],original[n],sizes[n]))return 40+(int)n;}
  if(save(targets[n],items[n].bytes,items[n].size))return 50+(int)n;
  size_t size=0;unsigned char *data=load(targets[n],&size,0);int ok=data&&size==items[n].size&&!memcmp(data,items[n].bytes,size);free(data);free(original[n]);if(!ok)return 60+(int)n;
  printf("COMPOSITOR_SNAPSHOT_INSTALLED file=%s bytes=%zu exact_owned_bytes=true\n",items[n].name,items[n].size);
 }
 sync();return 0;
}
int main(void){alarm(60);int result=run();printf("COMPOSITOR_SNAPSHOT_INSTALL_RESULT pass=%s code=%d errno=%d backups_preserved=true\n",result?"false":"true",result,errno);if(!result)puts("GPUPREP lab tool installation PASSED");fflush(NULL);return result?1:0;}
