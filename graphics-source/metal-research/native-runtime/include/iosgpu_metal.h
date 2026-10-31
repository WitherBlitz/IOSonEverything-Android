/* SPDX-License-Identifier: AGPL-3.0-or-later */
#ifndef IOSGPU_METAL_H
#define IOSGPU_METAL_H
#include <stdint.h>
#define IOSMETAL_WIRE_MAGIC UINT32_C(0x314c544d)
#define IOSMETAL_WIRE_VERSION 1u
#define IOSMETAL_HEADER_BYTES 24u
/* Request: LE u32 magic/version/op/body-size, u64 sequence (starts at1).
 * Response: LE u32 magic/version, i32 status, u32 body-size, u64 sequence.
 * Negative inner status carries bounded UTF8 diagnostic. Host pointers below
 * never appear in this wire contract. A context belongs to exactly one owner.
 * Calls are serialized by the trusted worker. Each context admits 1024 live
 * objects. All Metal contexts together admit256MiB buffer/texture/shader source
 * bytes, including source/resources retained by functions/pipelines/commands.
 * Perqueue32 uncompleted commands are admitted without blocking on runtime64.
 * A structurally valid request with the expected sequence consumes it even on
 * semantic/body/capacity errors. Invalid headers/sequences consume nothing.
 */
enum iosmetal_command {
 IOSMETAL_INFO=1,IOSMETAL_BUFFER_NEW,IOSMETAL_BUFFER_UPLOAD,IOSMETAL_BUFFER_READ,
 IOSMETAL_LIBRARY_NEW,IOSMETAL_FUNCTION_NEW,IOSMETAL_COMPUTE_PIPELINE_NEW,
 IOSMETAL_QUEUE_NEW,IOSMETAL_COMMAND_NEW,IOSMETAL_COMPUTE_ENCODER_NEW,
 IOSMETAL_COMPUTE_PIPELINE_SET,IOSMETAL_BUFFER_SET,IOSMETAL_DISPATCH,
 IOSMETAL_ENCODER_END,IOSMETAL_COMMAND_COMMIT,IOSMETAL_COMMAND_STATUS,
 IOSMETAL_OBJECT_RELEASE,IOSMETAL_TEXTURE_NEW,IOSMETAL_TEXTURE_UPLOAD,
 IOSMETAL_TEXTURE_READ,IOSMETAL_RENDER_PIPELINE_NEW,IOSMETAL_RENDER_ENCODER_NEW,
 IOSMETAL_RENDER_PIPELINE_SET,IOSMETAL_DRAW,IOSMETAL_LIBRARY_NAMES,
 IOSMETAL_TEXTURE_SET,IOSMETAL_SAMPLER_NEW,IOSMETAL_SAMPLER_SET,
 IOSMETAL_RENDER_PIPELINE_VERTEX_LAYOUT_NEW,
 IOSMETAL_RENDER_PIPELINE_COLOR_STATE_NEW,IOSMETAL_BLEND_COLOR_SET,
 IOSMETAL_ENCODER_BATCH,IOSMETAL_FEATURES
};
/* FEATURES: empty request, four u32 version1, flags1(encoder batch), maximum
 *256 records, maximum65536-byte body. Unsupported query selects legacy calls.
 * ENCODER_BATCH: u32 count1..256, then count records(u32 opcode/body-size,body).
 * Fixed-size encoder operations only:11/12/13/14/23/24/26/28/31. No recursive
 * batch, creates, transfers, reads, releases or commits. Entire framing is
 * validated before effects. Replyu32 applied count; semantic execution failure
 * poisons the context so a partially encoded batch cannot later be committed.
 */
/* TEXTURE_SET/SAMPLER_SET: u64 encoder/resource (zero unbinds), u32 index/stage.
 * Stages: 0compute,1vertex,2fragment. Texture slots0..30, sampler slots0..15.
 * SAMPLER_NEW: six u32 min/mag filter, S/T/R address mode, normalized flag1.
 * Initial subset: nearest0/linear1 filters; clamp-edge0/repeat2; no mipmaps,
 * anisotropy, comparison or nondefault LOD clamps. Other fields are refused.
 */
/* RENDER_PIPELINE_VERTEX_LAYOUT_NEW: old pipeline prefix (u64 vertex/fragment,
 * u32 color format), then u32 attribute count; each u32 index/format, u64 offset,
 * u32 buffer index. Then u32 layout count; each u32 buffer index, u64 stride,
 * u32 step function, u64 step rate. Max31 records each; indices0..30, no duplicates.
 * Offsets/strides/rates must fit runtime u32; dynamic stride is unsupported.
 * Old RENDER_PIPELINE_NEW remains the exact original20-byte descriptor.
 */
/* RENDER_PIPELINE_COLOR_STATE_NEW: full VERTEX_LAYOUT_NEW body (empty counts
 * represent no stage-in attributes), then eight u32 enabled(0/1), srcRGB,
 * dstRGB, RGBoperation, srcAlpha, dstAlpha, alphaOperation, writeMask(0..15).
 * Factors/operations use public Metal numeric enums; unsupported runtime
 * combinations return their descriptor diagnostics. Old21/29 are unchanged.
 * BLEND_COLOR_SET: u64 render encoder, four LE f32 bit patterns RGBA. All must
 * be finite. Values follow the runtime's Metal blend-constant semantics.
 */
void *iosmetal_open(uint32_t owner,const uint8_t *private_cache,uint32_t cache_length,
                   uint8_t *error,uint32_t error_capacity);
int64_t iosmetal_call(void *context,const uint8_t *request,uint32_t size,
                     uint8_t *reply,uint32_t capacity,uint32_t *written);
void iosmetal_close(void *context);
/* Serialized trusted-host API only, never a guest wire struct. Source commands
 * must be complete. Export copies pixels on the GPU into one of three AHBs.
 * The caller waits ready_fd on the GPU before reading buffer, then returns a
 * consumer sync-file fd (or -1 after real completion). fd ownership transfers
 * on successful calls only; ready_fd may be -1 for an already completed fence.
 * Output is untouched on failure. Tokens belong to one open context/epoch.
 * Reuse requires both completions; collect:0 drained,-11 busy. Close retains an
 * undrained context until worker exit instead of freeing live GPU allocations.
 * Buffer is borrowed until return. Do not AHardwareBuffer_release that borrow.
 * The shared open enables extra extensions; legacy iosmetal_open is unchanged.
 */
struct iosmetal_frame {uint32_t version,width,height,format;uint64_t token;
 void *buffer;int32_t ready_fd;uint32_t reserved;};
void *iosmetal_open_shared_frames(uint32_t,const uint8_t *,uint32_t,uint8_t *,uint32_t);
int32_t iosmetal_frame_export(void *,uint64_t,struct iosmetal_frame *);
/* Preferred resource path: prepare reserves storage without any GPU write.
 * Import/create the consumer's EGL image now; then submit returns its producer
 * fence. Cache imports for unchanged AHB storage; finish any setup GPU work
 * before submit (e.g. creation-only glFinish). A prepared descriptor is not readable;
 * ready_fd=-1 there is a placeholder, not completion. No wire operations are
 * admitted until every prepared frame is submitted or cancelled. Cancel only
 * after discarding consumer references; it never cancels submitted GPU work.
 * Convenience export skips this setup opportunity; synchronize creation/use of
 * new consumer resources with its producer. Cached sampling uses GPU waits.
 */
int32_t iosmetal_frame_prepare(void *,uint64_t,struct iosmetal_frame *);
int32_t iosmetal_frame_submit(void *,uint64_t,int32_t *ready_fd);
int32_t iosmetal_frame_cancel(void *,uint64_t);
int32_t iosmetal_frame_return(void *,uint64_t,int32_t);
int32_t iosmetal_frame_collect(void *);
int32_t iosmetal_frame_stats(void *,uint64_t *five_counters);
#endif
