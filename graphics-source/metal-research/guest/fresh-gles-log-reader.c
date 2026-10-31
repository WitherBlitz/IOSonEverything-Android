/* Bounded diagnostic for the authored compositor's exact existing log only. */
extern int open(const char *,int,...),close(int),printf(const char *,...);
extern long read(int,void *,unsigned long);
extern long long lseek(int,long long,int);
extern unsigned sleep(unsigned),alarm(unsigned);
extern int fflush(void *),strncmp(const char *,const char *,unsigned long);
extern char *strstr(const char *,const char *);
struct file_stat {int dev;unsigned short mode,nlink;unsigned long long ino;unsigned int uid,gid;int rdev;
 long long atime[2],mtime[2],ctime[2],birth[2],size,blocks;int blksize;unsigned int flags,gen;int spare;long long qspare[2];};
extern int fstat(int,struct file_stat *);
_Static_assert(sizeof(struct file_stat)==144,"Darwin stat ABI");
int main(void){
 const char *path="/private/var/mobile/iosgpu-backboardd-job-macro-scope-v2.log";
 int fd=-1;long long position=0;unsigned total=0,used=0;char line[2048];
 alarm(1500);
 for(unsigned round=0;round<1200&&total<16*1024*1024;){
  if(fd<0){fd=open(path,0);if(fd>=0){struct file_stat st={0};
   if(fstat(fd,&st)||st.size<0||st.size>512*1024*1024){close(fd);return 1;}
   position=lseek(fd,0,2);if(position<0){close(fd);return 1;}
   printf("FRESH_GLES starting at EOF offset=%lld old_bytes_skipped=true\n",position);fflush((void *)0);
  }}
  if(fd>=0){struct file_stat st={0};
   if(fstat(fd,&st)||st.size<0||st.size>512*1024*1024)break;
   if(st.size<position){position=lseek(fd,0,0);used=0;printf("FRESH_GLES current log reset\n");}
   char data[4096];long n=read(fd,data,sizeof(data));if(n<0)break;
   if(n>0){position+=n;total+=(unsigned)n;
    for(long i=0;i<n;i++){
     if(data[i]=='\n'){line[used]=0;
      if(!strncmp(line,"IOSGPU",6)||!strncmp(line,"IOSMETAL",8)||!strncmp(line,"gfx:",4)||(!strncmp(line,"redwood-gl:",11)&&strstr(line,"frame")))printf("FRESH_GLES %s\n",line);
      used=0;
     }else if(used<sizeof(line)-1)line[used++]=data[i];
    }
    fflush((void *)0);continue;
   }
  }
  sleep(1);round++;
 }
 if(fd>=0)close(fd);printf("FRESH_GLES done fresh_bytes=%u offset=%lld\n",total,position);fflush((void *)0);return 0;
}
