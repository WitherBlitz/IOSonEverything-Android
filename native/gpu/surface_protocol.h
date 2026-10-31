/* Value-only guest association protocol. SPDX-License-Identifier: AGPL-3.0-or-later */
#ifndef IOSGPU_SURFACE_PROTOCOL_H
#define IOSGPU_SURFACE_PROTOCOL_H
#include <stddef.h>
#include <stdint.h>
#define IOSGPU_SURFACE_MAGIC UINT32_C(0x31534649)
#define IOSGPU_SURFACE_VERSION 1u
#define IOSGPU_SURFACE_KEY "IOSVMHostSnapshotV1"
enum iosgpu_surface_command {IOSGPU_SURFACE_PUBLISH=1,IOSGPU_SURFACE_RESOLVE=2,IOSGPU_SURFACE_RETIRE=3};
/* Serialized in the existing METAL_CALL operation; no native FD or pointer. */
struct iosgpu_surface_request {uint32_t magic,version,command,reserved;uint64_t argument[6];};
struct iosgpu_surface_meta {uint32_t magic,version,surface,width,height,reserved;uint64_t capability[2];};
_Static_assert(sizeof(struct iosgpu_surface_request)==64,"surface control wire");
_Static_assert(sizeof(struct iosgpu_surface_meta)==40,"surface metadata wire");
_Static_assert(offsetof(struct iosgpu_surface_meta,capability)==24,"surface capability offset");
static inline int iosgpu_surface_meta_valid(const struct iosgpu_surface_meta *m){
 return m&&m->magic==IOSGPU_SURFACE_MAGIC&&m->version==IOSGPU_SURFACE_VERSION&&m->surface&&m->width&&m->height&&m->width<=8192&&m->height<=8192&&(uint64_t)m->width*m->height<=8u*1024u*1024u&&!m->reserved&&(m->capability[0]||m->capability[1]);
}
#endif
