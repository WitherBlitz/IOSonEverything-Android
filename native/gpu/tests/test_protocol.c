#include <assert.h>
#include <stdint.h>
#include "../protocol.h"
int main(void) {
 struct iosgpu_region r;
 assert(iosgpu_validate_region(8,8,4,4,2,2,12,24,&r)==0);
 assert(r.row_bytes==8 && r.span==20);
 assert(iosgpu_validate_region(8,8,7,7,2,2,12,24,&r)!=0);
 assert(iosgpu_validate_region(8,8,0,0,2,2,7,24,&r)!=0);
 assert(iosgpu_validate_region(8,8,0,0,2,2,12,19,&r)!=0);
 assert(iosgpu_validate_region(UINT32_MAX,UINT32_MAX,0,0,UINT32_MAX,UINT32_MAX,UINT32_MAX,UINT32_MAX,&r)!=0);
 assert(iosgpu_validate_region(8,8,0,0,0,1,4,4,&r)!=0);
 assert(iosgpu_valid_buffer(0x1000,1024));
 assert(!iosgpu_valid_buffer(UINT64_MAX-3,8));
 assert(!iosgpu_valid_buffer(0,4));
 assert(!iosgpu_valid_buffer(0x1000,IOSGPU_MAX_BYTES+1));
 return 0;
}
