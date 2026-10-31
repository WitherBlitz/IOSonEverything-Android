/* SPDX-License-Identifier: AGPL-3.0-or-later */
#include <stdint.h>
int64_t iosgpu_backend_call(uint32_t,uint32_t,const void *,uint32_t,void *,uint32_t,uint32_t *);
uint32_t iosgpu_backend_context_count(void);
int64_t iosgpu_route_call(uint32_t,uint32_t,const void *,uint32_t,void *,uint32_t,uint32_t *);
