#ifndef IOSGPU_PROXY_TEST_SHIM_H
#define IOSGPU_PROXY_TEST_SHIM_H
#include <stddef.h>
#include <stdint.h>
#include <stdarg.h>
#include <limits.h>
typedef int pid_t;
typedef int ssize_t;
typedef unsigned socklen_t;
typedef int pthread_mutex_t;
typedef struct { int count,kind[8],from[8],to[8]; } posix_spawn_file_actions_t;
typedef long long off_t;
struct stat { unsigned st_mode; off_t st_size; };
#define _Atomic
#define memory_order_acquire 1
#define memory_order_release 2
#define atomic_init(p,v) (*(p)=(v))
#define atomic_is_lock_free(p) ((void)(p),1)
#define atomic_load_explicit(p,o) ((void)(o),*(p))
#define atomic_store_explicit(p,v,o) ((void)(o),*(p)=(v))
#define F_GET_SEALS 5
#define F_ADD_SEALS 6
#define F_SEAL_GROW 1
#define F_SEAL_SHRINK 2
#define F_SEAL_SEAL 4
#define MFD_CLOEXEC 1
#define MFD_ALLOW_SEALING 2
#define PROT_READ 1
#define PROT_WRITE 2
#define MAP_SHARED 1
#define MAP_FAILED ((void *)-1)
#define S_ISREG(m) ((m)==0100000u)
typedef struct {const char *dli_fname;} Dl_info;
struct timespec {long tv_sec,tv_nsec;};
struct pollfd {int fd;short events,revents;};
#define PTHREAD_MUTEX_INITIALIZER 0
#define CLOCK_MONOTONIC 1
#define ANDROID_LOG_INFO 4
int __android_log_print(int,const char *,const char *,...);
#define POLLIN 1
#define POLLOUT 4
#define POLLERR 8
#define POLLHUP 16
#define POLLNVAL 32
#define AF_UNIX 1
#define SOCK_STREAM 1
#define SOCK_CLOEXEC 0x100
#define SOL_SOCKET 1
#define SO_TYPE 3
#define MSG_DONTWAIT 1
#define MSG_NOSIGNAL 2
#define F_DUPFD_CLOEXEC 1
#define F_GETFL 2
#define F_SETFL 3
#define O_NONBLOCK 4
#define WNOHANG 1
#define SIGKILL 9
#define PR_SET_PDEATHSIG 1
#define EINVAL 22
#define EINTR 4
#define EAGAIN 11
#define EWOULDBLOCK EAGAIN
#define EBUSY 16
#define EIO 5
#define ECHILD 10
#define EPROTO 71
#define ETIMEDOUT 110
extern int test_errno;
#define errno test_errno
void *memcpy(void *,const void *,size_t);
void *memset(void *,int,size_t);
void *malloc(size_t);
void *calloc(size_t,size_t);
void free(void *);
char *strdup(const char *);
char *strrchr(const char *,int);
int strncmp(const char *,const char *,size_t);
int strcmp(const char *,const char *);
int snprintf(char *,size_t,const char *,...);
long strtol(const char *,char **,int);
int clock_gettime(int,struct timespec *);
int poll(struct pollfd *,unsigned long,int);
ssize_t send(int,const void *,size_t,int);
ssize_t recv(int,void *,size_t,int);
int close(int);
int kill(pid_t,int);
pid_t getpid(void);
pid_t getppid(void);
pid_t waitpid(pid_t,int *,int);
int socketpair(int,int,int,int *);
int fcntl(int,int,...);
int dladdr(const void *,Dl_info *);
int pthread_mutex_trylock(pthread_mutex_t *);
int pthread_mutex_unlock(pthread_mutex_t *);
int posix_spawn_file_actions_init(posix_spawn_file_actions_t *);
int posix_spawn_file_actions_addclose(posix_spawn_file_actions_t *,int);
int posix_spawn_file_actions_adddup2(posix_spawn_file_actions_t *,int,int);
int posix_spawn_file_actions_destroy(posix_spawn_file_actions_t *);
int posix_spawn(pid_t *,const char *,const posix_spawn_file_actions_t *,const void *,char *const *,char *const *);
int prctl(int,...);
int getsockopt(int,int,int,void *,socklen_t *);
int memfd_create(const char *,unsigned);
int ftruncate(int,off_t);
int fstat(int,struct stat *);
void *mmap(void *,size_t,int,int,int,off_t);
int munmap(void *,size_t);
#endif
