/* IOSonEverything experimental guest GPU call contract. SPDX-License-Identifier: AGPL-3.0-or-later */
#ifndef IOSVM_GPU_PROTOCOL_H
#define IOSVM_GPU_PROTOCOL_H
#include <stdint.h>
#define IOSGPU_MAGIC UINT64_C(0x494f534750553031)
#define IOSGPU_REPLY UINT32_C(0x47505531)
#define IOSGPU_HLT 0x4f53
#define IOSGPU_MAX_BYTES (32u*1024u*1024u)
enum iosgpu_op { IOSGPU_PING=0,IOSGPU_OPEN,IOSGPU_WRITE,IOSGPU_READ,IOSGPU_CLOSE,
 IOSGPU_RESOURCE_CREATE,IOSGPU_RESOURCE_UNREF,IOSGPU_RESOURCE_UPLOAD,IOSGPU_RESOURCE_DOWNLOAD,
 IOSGPU_METAL_CALL };
#define IOSGPU_METAL_OPEN_MAGIC UINT32_C(0x4c544d49)
/* OPEN size0 keeps the GLES ABI. Metal OPEN is four LE u32 words:
 * magic, version1, flags0, reserved0. Cache paths are always host supplied. */
struct iosgpu_region { uint32_t row_bytes; uint64_t span; };
static inline int iosgpu_valid_buffer(uint64_t address,uint64_t size) {
 return size==0 || (address!=0 && size<=IOSGPU_MAX_BYTES && address<=UINT64_MAX-size);
}
static inline int iosgpu_validate_region(uint32_t width,uint32_t height,uint32_t x,uint32_t y,
 uint32_t w,uint32_t h,uint32_t stride,uint32_t available,struct iosgpu_region *region) {
 uint64_t row=(uint64_t)w*4,span;
 if(!w||!h||x>width||y>height||w>width-x||h>height-y||row>stride)return -1;
 span=(uint64_t)(h-1)*stride+row;
 if(span>IOSGPU_MAX_BYTES||span>available)return -1;
 region->row_bytes=(uint32_t)row;region->span=span;return 0;
}
#endif
