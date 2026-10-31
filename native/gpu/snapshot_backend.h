/* Serialized trusted-host snapshot routing. SPDX-License-Identifier: AGPL-3.0-or-later */
#ifndef IOSGPU_SNAPSHOT_BACKEND_H
#define IOSGPU_SNAPSHOT_BACKEND_H
#include "snapshot_copy.h"
#include "surface_protocol.h"
int iosgpu_backend_snapshot_ready(void);
int64_t iosgpu_backend_surface_call(uint32_t context,void *metal,const struct iosgpu_frame_api *,const struct iosgpu_surface_request *,void *output,uint32_t capacity,uint32_t *written);
void iosgpu_backend_snapshot_producer_closed(void);
/* Published,resolved,dropped,live snapshots,charged bytes,copies,imports,reuses. */
void iosgpu_backend_snapshot_stats(uint64_t values[8]);
#endif
