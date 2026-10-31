#pragma once
typedef int pthread_once_t;
typedef int pthread_mutex_t;
#define PTHREAD_ONCE_INIT 0
#define PTHREAD_MUTEX_INITIALIZER 0
int pthread_once(pthread_once_t *, void (*)(void));
int pthread_mutex_lock(pthread_mutex_t *);
int pthread_mutex_unlock(pthread_mutex_t *);
