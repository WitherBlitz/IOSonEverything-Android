/* Regression against our own adapter classes, public IOSurface data only. */
#import <IOSurface/IOSurfaceRef.h>
@interface IOSMDevice:NSObject
- (void)beginSubmission;
- (BOOL)sharedFrames;
@end
static NSCondition *retirementCondition;
static CAMetalLayer *retirementLayer;
static BOOL retirementGuard;
static unsigned retirementLockFailures,retirementLockChecks;
@interface IOSMetalRetirementDevice:IOSMDevice
@end
@implementation IOSMetalRetirementDevice
- (void)beginSubmission{
 if(retirementGuard){
  dispatch_semaphore_t ready=dispatch_semaphore_create(0);NSCondition *condition=retirementCondition;CAMetalLayer *layer=retirementLayer;
  dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{[condition lock];[condition unlock];@synchronized(layer){}dispatch_semaphore_signal(ready);});
  retirementLockChecks++;if(dispatch_semaphore_wait(ready,dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC)))retirementLockFailures++;
 }
 [super beginSubmission];
}
@end
static void retirementPaint(CAMetalLayer *layer,id<MTLDevice> device){
 @autoreleasepool{
  id<CAMetalDrawable> drawable=[layer nextDrawable];if(!drawable)@throw [NSException exceptionWithName:@"SnapshotRetirement" reason:@"No drawable" userInfo:nil];
  /* state/condition are properties of our authored IOSMDrawable/IOSMLayerState. */
  retirementCondition=[[(id)drawable valueForKey:@"state"]valueForKey:@"condition"];
  id<MTLCommandQueue> queue=[device newCommandQueue];id<MTLCommandBuffer> command=[queue commandBuffer];MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
  pass.colorAttachments[0].texture=drawable.texture;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=MTLClearColorMake(.25,.5,1,1);
  id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];[encoder endEncoding];[command presentDrawable:drawable];[command commit];[command waitUntilCompleted];
  if(![NSThread isMainThread])dispatch_sync(dispatch_get_main_queue(),^{});
  if(command.status!=MTLCommandBufferStatusCompleted||command.error)@throw [NSException exceptionWithName:@"SnapshotRetirement" reason:command.error.description?:@"Commit failed" userInfo:nil];
 }
}
static BOOL materialized(id content,NSUInteger width){
 if(!content||CFGetTypeID((__bridge CFTypeRef)content)!=IOSurfaceGetTypeID())return NO;IOSurfaceRef surface=(__bridge IOSurfaceRef)content;
 CFTypeRef marker=IOSurfaceCopyValue(surface,CFSTR("IOSVMHostSnapshotV1"));if(marker){CFRelease(marker);return NO;}
 if(IOSurfaceGetWidth(surface)!=width||IOSurfaceGetHeight(surface)!=width||IOSurfaceLock(surface,kIOSurfaceLockReadOnly,NULL))return NO;
 const uint8_t expected[]={255,128,64,255};const uint8_t *pixels=IOSurfaceGetBaseAddress(surface);size_t row=IOSurfaceGetBytesPerRow(surface);BOOL good=pixels&&row>=width*4;
 if(good)for(NSUInteger y=0;y<width;y++)for(NSUInteger x=0;x<width;x++)if(memcmp(pixels+y*row+x*4,expected,4))good=NO;
 IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,NULL);return good;
}
static int retirementTest(void){
 @autoreleasepool{
  IOSMetalRetirementDevice *ownedDevice=[IOSMetalRetirementDevice new];if(![ownedDevice respondsToSelector:@selector(sharedFrames)]||![ownedDevice sharedFrames]){puts("METAL_SNAPSHOT_RETIREMENT_RESULT pass=false reason=shared-mode-unavailable");return 42;}
  id<MTLDevice> device=(id<MTLDevice>)ownedDevice;CAMetalLayer *layer=[CAMetalLayer layer];layer.device=device;layer.drawableSize=CGSizeMake(8,8);retirementLayer=layer;
  puts("METAL_SNAPSHOT_STAGE initial-paint");retirementPaint(layer,device);id first=layer.contents;
  puts("METAL_SNAPSHOT_STAGE resize");retirementGuard=YES;@autoreleasepool{layer.drawableSize=CGSizeMake(16,16);retirementPaint(layer,device);}retirementGuard=NO;
  BOOL resized=materialized(first,8);id second=layer.contents;
  puts("METAL_SNAPSHOT_STAGE clear-device");retirementGuard=YES;@autoreleasepool{layer.device=nil;}retirementGuard=NO;BOOL invalidated=materialized(second,16);
  BOOL pass=resized&&invalidated&&!retirementLockFailures&&retirementLockChecks>=2;
  printf("METAL_SNAPSHOT_RETIREMENT_RESULT pass=%s resize_materialized=%u invalidation_materialized=%u lock_checks=%u lock_failures=%u\n",pass?"true":"false",resized,invalidated,retirementLockChecks,retirementLockFailures);
  retirementLayer=nil;retirementCondition=nil;fflush(NULL);return pass?0:1;
 }
}
