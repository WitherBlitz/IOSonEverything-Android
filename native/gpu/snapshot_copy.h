/* Trusted worker only. SPDX-License-Identifier: AGPL-3.0-or-later */
#ifndef IOSGPU_SNAPSHOT_COPY_H
#define IOSGPU_SNAPSHOT_COPY_H
#include <stdint.h>
#include <android/hardware_buffer.h>
struct iosmetal_frame;
struct iosgpu_frame_api {
 int (*prepare)(void *,uint64_t,struct iosmetal_frame *);
 int (*submit)(void *,uint64_t,int32_t *);
 int (*cancel)(void *,uint64_t);
 int (*returned)(void *,uint64_t,int32_t);
 int (*collect)(void *);
};
struct iosgpu_snapshot_copy;
struct iosgpu_snapshot_target {AHardwareBuffer *buffer;void *image;uint32_t texture,width,height;};
#ifndef IOSGPU_SNAPSHOT_API
#define IOSGPU_SNAPSHOT_API
#endif
IOSGPU_SNAPSHOT_API struct iosgpu_snapshot_copy *iosgpu_snapshot_copy_create(void *shared_parent);
/* Destination must be a live target from this copy owner with the exact shape.
 * A successful copy completes its GPU read, returns and collects the source
 * lease before returning. Errors after an indeterminate submission poison the
 * owner; retain it and its targets until worker exit. Serialized host calls only. */
IOSGPU_SNAPSHOT_API int iosgpu_snapshot_copy(struct iosgpu_snapshot_copy *,void *metal,uint64_t source,uint32_t destination_texture,uint32_t width,uint32_t height,const struct iosgpu_frame_api *);
/* False means poisoned: retain until worker exit instead of destroying storage. */
IOSGPU_SNAPSHOT_API int iosgpu_snapshot_copy_destroy(struct iosgpu_snapshot_copy *);
/* Purge completed producer imports before closing a healthy Metal context;
 * immutable destination targets stay alive for their compositor consumers. */
IOSGPU_SNAPSHOT_API int iosgpu_snapshot_copy_clear_imports(struct iosgpu_snapshot_copy *);
IOSGPU_SNAPSHOT_API void iosgpu_snapshot_copy_stats(const struct iosgpu_snapshot_copy *,uint64_t stats[4]);
IOSGPU_SNAPSHOT_API int iosgpu_snapshot_target_create(struct iosgpu_snapshot_copy *,uint32_t,uint32_t,struct iosgpu_snapshot_target *);
/* Destroy only after gfxstream and every tracked consumer release this target.
 * Clears the caller's target on success; duplicate/foreign owners are refused. */
IOSGPU_SNAPSHOT_API int iosgpu_snapshot_target_destroy(struct iosgpu_snapshot_copy *,struct iosgpu_snapshot_target *);
#endif
