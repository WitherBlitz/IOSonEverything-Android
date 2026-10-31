/* Pure ownership policy, called only by the serialized worker. AGPL-3.0-or-later */
#ifndef IOSGPU_SURFACE_REGISTRY_H
#define IOSGPU_SURFACE_REGISTRY_H
#include "surface_protocol.h"
#define IOSGPU_SNAPSHOT_SLOTS 32u
#define IOSGPU_SNAPSHOT_RESIDENT_LIMIT 31u /* one native target reserved for replacement */
#define IOSGPU_SNAPSHOT_OWNER_SURFACES 3u
#define IOSGPU_SNAPSHOT_CONSUMERS 16u
#define IOSGPU_SNAPSHOT_NAME_REFS 1024u
struct iosgpu_surface_consumer {uint32_t context,count;};
struct iosgpu_surface_record {
 struct iosgpu_surface_meta meta;
 uint32_t owner,resource,current;
 struct iosgpu_surface_consumer consumers[IOSGPU_SNAPSHOT_CONSUMERS];
};
struct iosgpu_surface_registry {struct iosgpu_surface_record records[IOSGPU_SNAPSHOT_SLOTS];};
#ifndef IOSGPU_REGISTRY_API
#define IOSGPU_REGISTRY_API
#endif
IOSGPU_REGISTRY_API int iosgpu_surface_preflight(const struct iosgpu_surface_registry *,uint32_t owner,uint32_t surface,uint32_t width,uint32_t height);
/* Output resource IDs are release obligations for the GPU owner, not pointers.
 * Unchanged outputs/state on failure. Publish receives a fresh immutable target. */
IOSGPU_REGISTRY_API int iosgpu_surface_publish(struct iosgpu_surface_registry *,uint32_t owner,const struct iosgpu_surface_meta *,uint32_t resource,uint32_t *drop);
IOSGPU_REGISTRY_API int iosgpu_surface_resolve(struct iosgpu_surface_registry *,uint32_t consumer,const struct iosgpu_surface_meta *,uint32_t *resource);
IOSGPU_REGISTRY_API int iosgpu_surface_unref(struct iosgpu_surface_registry *,uint32_t consumer,uint32_t resource,uint32_t *drop);
/* Retire only after guest materialization, metadata removal and seed advance. */
IOSGPU_REGISTRY_API int iosgpu_surface_retire(struct iosgpu_surface_registry *,uint32_t owner,const struct iosgpu_surface_meta *,uint32_t *drop);
/* Call after the actual consumer context/GL bindings are destroyed. Capacity32. */
IOSGPU_REGISTRY_API int iosgpu_surface_consumer_closed(struct iosgpu_surface_registry *,uint32_t consumer,uint32_t *drops,size_t capacity,size_t *written);
#endif
