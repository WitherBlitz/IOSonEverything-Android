// Authored adapter ABI; SPDX-License-Identifier: AGPL-3.0-or-later
#import <Metal/Metal.h>
typedef id<MTLDevice> (*IOSMetalCreateDeviceFn)(void) NS_RETURNS_RETAINED;
__attribute__((visibility("default"))) id<MTLDevice> IOSMetalCreateDevice(void) NS_RETURNS_RETAINED;
