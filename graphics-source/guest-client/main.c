extern int gfx_test_main(int,char **);
extern int printf(const char *,...);
extern int fflush(void *);
int main(void){char *args[]={"guest-gfx-test","1",(void *)0};
 printf("IOSGPU guest-origin GL test starting\n");fflush((void *)0);
 int result=gfx_test_main(2,args);printf("IOSGPU guest-origin GL test result=%d\n",result);fflush((void *)0);return result;
}
