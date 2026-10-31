// Authored public CAMetalLayer adapter. SPDX-License-Identifier: AGPL-3.0-or-later
// Shared mode associates an ordinary IOSurface with an immutable host snapshot.
// CPU materialization happens only when normally discarding the surface pool.
#import <QuartzCore/QuartzCore.h>
#import <IOSurface/IOSurfaceRef.h>
#import <objc/runtime.h>
#include <math.h>

@class IOSMLayerState;
@interface IOSMLayerFrame:NSObject{IOSurfaceRef _surface;struct iosgpu_surface_meta _snapshot;BOOL _materializable;}
@property(nonatomic,strong) IOSMTexture *texture;
@property(nonatomic) BOOL leased;
- (IOSurfaceRef)publishSnapshot;
@end
@implementation IOSMLayerFrame
- (IOSurfaceRef)publishSnapshot{
 IOSMTexture *texture=self.texture;if(![texture.backendDevice sharedFrames])return NULL;
 _materializable=NO;
 if(!_surface){
  NSDictionary *properties=@{(__bridge NSString *)kIOSurfaceWidth:@(texture.width),(__bridge NSString *)kIOSurfaceHeight:@(texture.height),(__bridge NSString *)kIOSurfaceBytesPerElement:@4,(__bridge NSString *)kIOSurfaceBytesPerRow:@(texture.width*4),(__bridge NSString *)kIOSurfacePixelFormat:@(0x42475241u)};
  _surface=IOSurfaceCreate((__bridge CFDictionaryRef)properties);if(!_surface)return NULL;
 }
 if(IOSurfaceLock(_surface,0,NULL))return NULL;
 struct iosgpu_surface_request request={IOSGPU_SURFACE_MAGIC,1,IOSGPU_SURFACE_PUBLISH,0,{texture.handle,IOSurfaceGetID(_surface),texture.width,texture.height,0,0}};
 struct iosgpu_surface_meta meta={0};int64_t result=[texture.backendDevice surfaceControl:&request meta:&meta];
 if(!result){CFDataRef value=CFDataCreate(kCFAllocatorDefault,(const UInt8 *)&meta,sizeof(meta));if(!value){IOSurfaceUnlock(_surface,0,NULL);invalid(@"Unable to create snapshot association");}IOSurfaceSetValue(_surface,CFSTR(IOSGPU_SURFACE_KEY),value);CFRelease(value);_snapshot=meta;_materializable=YES;}
 if(IOSurfaceUnlock(_surface,0,NULL))invalid(@"Unable to publish snapshot seed");
 if(result){if(result==-ENOSPC||result==-ENOBUFS||result==-ENOMEM||result==-ENOTSUP||result==-ENODEV)return NULL;invalid([NSString stringWithFormat:@"GPU snapshot publication failed: %lld",(long long)result]);}
 return _surface;
}
- (void)dealloc{
 if(!_surface)return;
 if(!_snapshot.surface){CFRelease(_surface);return;}
 /* Existing CA objects can outlive this pool. Preserve the last successful
  * image before removing its host association. Failure keeps the bounded host
  * mapping and this IOSurface reference alive until the worker/process exits. */
 @try{
  if(!_materializable){fprintf(stderr,"IOSMETAL_SNAPSHOT_RETAIN materialization_unavailable=1\n");return;}
  IOSMDevice *device=_texture.backendDevice;[device beginSubmission];
  @try{
   NSData *pixels=[_texture displayPixels];size_t row=_texture.width*4;
   if(IOSurfaceLock(_surface,0,NULL))return;
   void *base=IOSurfaceGetBaseAddress(_surface);size_t stride=IOSurfaceGetBytesPerRow(_surface);
   if(!base||stride<row||pixels.length!=row*_texture.height){IOSurfaceUnlock(_surface,0,NULL);return;}
   for(NSUInteger y=0;y<_texture.height;y++)memcpy((uint8_t *)base+y*stride,(const uint8_t *)pixels.bytes+y*row,row);
   IOSurfaceRemoveValue(_surface,CFSTR(IOSGPU_SURFACE_KEY));if(IOSurfaceUnlock(_surface,0,NULL))return;
   struct iosgpu_surface_request request={IOSGPU_SURFACE_MAGIC,1,IOSGPU_SURFACE_RETIRE,0,{_snapshot.capability[0],_snapshot.capability[1],_snapshot.surface,_snapshot.width,_snapshot.height,0}};
   int64_t result=[device surfaceControl:&request meta:NULL];fprintf(stderr,"IOSMETAL_SNAPSHOT_MATERIALIZED width=%lu height=%lu retire=%lld\n",(unsigned long)_texture.width,(unsigned long)_texture.height,(long long)result);
   CFRelease(_surface);_surface=NULL;
  }@finally{[device endSubmission];}
 }@catch(NSException *error){fprintf(stderr,"IOSMETAL_SNAPSHOT_RETAIN materialization_failed=%s\n",error.reason.UTF8String);}
}
@end
@interface IOSMDrawable:NSObject<CAMetalDrawable,IOSMetalDrawableLease>
@property(nonatomic,strong) IOSMLayerState *state;
@property(nonatomic,strong) IOSMLayerFrame *frame;
@property(nonatomic) NSUInteger drawableID;
@property(nonatomic) BOOL presentStarted;
@property(nonatomic,weak) id reservedCommand;
@end
@interface IOSMLayerState:NSObject
@property(nonatomic,weak) CAMetalLayer *layer;
@property(nonatomic,strong) IOSMDevice *device;
@property(nonatomic,strong) NSCondition *condition;
@property(nonatomic,strong) NSMutableArray<IOSMLayerFrame *> *frames;
@property(nonatomic) CGSize size;
@property(nonatomic) BOOL framebufferOnly;
@property(nonatomic) NSUInteger maximumDrawableCount;
@property(nonatomic) NSUInteger nextID;
@property(nonatomic) BOOL invalidated;
- (id<CAMetalDrawable>)acquire;
@end
static char iosmetal_layer_key;
static IOSMLayerState *layerState(CAMetalLayer *layer){return objc_getAssociatedObject(layer,&iosmetal_layer_key);}
@implementation IOSMLayerState
- (instancetype)init{if((self=[super init])){_condition=[NSCondition new];_frames=[NSMutableArray array];_maximumDrawableCount=3;_nextID=1;}return self;}
- (id<CAMetalDrawable>)acquire{
 /* Last-reference destruction may materialize old GPU frames. Keep every
  * removed frame alive until after the pool condition has been unlocked. */
 NSMutableArray *retired __attribute__((objc_precise_lifetime))=[NSMutableArray new];
 [_condition lock];
 @try{
  NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:1.0];
  while(YES){
   if(_invalidated||!_layer)return nil;
   CGSize size=_size;if(size.width==0&&size.height==0){size=_layer.bounds.size;size.width*=_layer.contentsScale;size.height*=_layer.contentsScale;}
   if(size.width<=0||size.height<=0)return nil;
   if(!isfinite(size.width)||!isfinite(size.height)||size.width!=floor(size.width)||size.height!=floor(size.height)||size.width>8192||size.height>8192||size.width*size.height>8u*1024*1024)invalid(@"Drawable dimensions exceed this adapter's texture bounds");
   NSUInteger leased=0;for(IOSMLayerFrame *candidate in _frames)if(candidate.leased)leased++;
   if(leased>=_maximumDrawableCount){if(![_condition waitUntilDate:deadline])return nil;continue;}
   IOSMLayerFrame *frame=nil;
   for(IOSMLayerFrame *candidate in [_frames copy]){
    if(candidate.leased)continue;
    if(candidate.texture.width!=(NSUInteger)size.width||candidate.texture.height!=(NSUInteger)size.height||candidate.texture.isFramebufferOnly!=_framebufferOnly){[retired addObject:candidate];[_frames removeObject:candidate];continue;}
    frame=candidate;break;
   }
   if(!frame&&_frames.count<_maximumDrawableCount){
    MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:(NSUInteger)size.width height:(NSUInteger)size.height mipmapped:NO];shape.storageMode=MTLStorageModeShared;shape.usage=_framebufferOnly?MTLTextureUsageRenderTarget:(MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead|MTLTextureUsageShaderWrite);
    IOSMTexture *texture=(IOSMTexture *)[_device newTextureWithDescriptor:shape];if(!texture)return nil;texture.framebufferOnlyValue=_framebufferOnly;
    frame=[IOSMLayerFrame new];frame.texture=texture;[_frames addObject:frame];
   }
   if(frame){
    if(_nextID==NSUIntegerMax)invalid(@"Drawable identifier space exhausted");
    IOSMDrawable *drawable=[IOSMDrawable new];drawable.state=self;drawable.frame=frame;drawable.drawableID=_nextID++;frame.leased=YES;return drawable;
   }
   if(![_condition waitUntilDate:deadline])return nil;
  }
 }@finally{[_condition unlock];}
}
@end
@implementation IOSMDrawable
- (id<MTLTexture>)texture{return self.frame.texture;}
- (CAMetalLayer *)layer{return self.state.layer;}
- (void)dealloc{[_state.condition lock];_frame.leased=NO;[_state.condition broadcast];[_state.condition unlock];}
- (CFTimeInterval)presentedTime{return 0;}
- (void)addPresentedHandler:(MTLDrawablePresentedHandler)handler{(void)handler;invalid(@"Actual display timing callbacks are not yet implemented; image publication is not a display fence");}
- (BOOL)reserveForCommand:(id)command{
 [self.state.condition lock];BOOL available=!_presentStarted&&!_reservedCommand&&!self.state.invalidated;if(available)_reservedCommand=command;[self.state.condition unlock];return available;
}
- (void)cancelReservationForCommand:(id)command{[self.state.condition lock];if(_reservedCommand==command)_reservedCommand=nil;[self.state.condition unlock];}
- (void)present{[self presentForCommand:nil];}
- (void)presentForCommand:(id)command{
 IOSMLayerState *state=self.state;CAMetalLayer *layer=state.layer;[state.condition lock];
 if(_presentStarted||state.invalidated||_reservedCommand!=command||!layer||layerState(layer)!=state){[state.condition unlock];invalid(@"Drawable is already presented or its layer no longer uses this device");}
 _presentStarted=YES;[state.condition unlock];
 IOSMTexture *texture=self.frame.texture;NSUInteger row=texture.width*4;
 IOSurfaceRef snapshot=[self.frame publishSnapshot];id imageOwner=nil;
 if(snapshot){imageOwner=(__bridge id)snapshot;static uint64_t presentations;presentations++;if(presentations<=3||presentations%300==0)fprintf(stderr,"IOSMETAL_SHARED_PRESENT count=%llu display_pixels_reads=0\n",(unsigned long long)presentations);}
 else{
 fprintf(stderr,"IOSMETAL_PRESENT_CPU_FALLBACK width=%lu height=%lu\n",(unsigned long)texture.width,(unsigned long)texture.height);
 NSData *pixels=[texture displayPixels];
 CGDataProviderRef provider=CGDataProviderCreateWithCFData((__bridge CFDataRef)pixels);CGColorSpaceRef color=CGColorSpaceCreateDeviceRGB();
 CGImageRef image=CGImageCreate(texture.width,texture.height,8,32,row,color,kCGImageAlphaPremultipliedFirst|kCGBitmapByteOrder32Little,provider,NULL,false,kCGRenderingIntentDefault);
 CGColorSpaceRelease(color);CGDataProviderRelease(provider);if(!image)invalid(@"Unable to create immutable drawable display image");
 // A drawable may belong to a UIView's backing layer. Keep GPU/readback on its
 // worker and retain the immutable image until main can publish it. Do not wait
 // on main: an application may itself be waiting for this command on main.
 imageOwner=(__bridge_transfer id)image;
 }
 void (^publish)(void)=^{
  @synchronized(layer){
   if(layerState(layer)!=state)return; // A later device transition discards it.
   // The normal main run loop publishes the transaction at its frame boundary.
   // A forced flush here serializes every worker frame with the compositor.
   [CATransaction begin];[CATransaction setDisableActions:YES];layer.contents=imageOwner;[CATransaction commit];
  }
 };
 if([NSThread isMainThread])publish();else dispatch_async(dispatch_get_main_queue(),publish);

}
- (void)presentAtTime:(CFTimeInterval)time{if(!isfinite(time)||time<0||time>CACurrentMediaTime())invalid(@"Future-timestamp drawable presentation is not implemented");[self present];}
- (void)presentAfterMinimumDuration:(CFTimeInterval)duration{if(!isfinite(duration)||duration!=0)invalid(@"Delayed drawable presentation is not implemented");[self present];}
@end

@interface CAMetalLayer(IOSMetalLayer)
- (id<MTLDevice>)iosm_device;
- (void)iosm_setDevice:(id<MTLDevice>)device;
- (id<CAMetalDrawable>)iosm_nextDrawable;
- (CGSize)iosm_drawableSize;
- (void)iosm_setDrawableSize:(CGSize)size;
- (MTLPixelFormat)iosm_pixelFormat;
- (void)iosm_setPixelFormat:(MTLPixelFormat)format;
- (BOOL)iosm_framebufferOnly;
- (void)iosm_setFramebufferOnly:(BOOL)value;
- (NSUInteger)iosm_maximumDrawableCount;
- (void)iosm_setMaximumDrawableCount:(NSUInteger)value;
- (BOOL)iosm_allowsNextDrawableTimeout;
- (void)iosm_setAllowsNextDrawableTimeout:(BOOL)value;
- (BOOL)iosm_presentsWithTransaction;
- (void)iosm_setPresentsWithTransaction:(BOOL)value;
- (void)iosm_setColorspace:(CGColorSpaceRef)value;
@end
@implementation CAMetalLayer(IOSMetalLayer)
- (id<MTLDevice>)iosm_device{IOSMLayerState *state=layerState(self);return state?state.device:[self iosm_device];}
- (void)iosm_setDevice:(id<MTLDevice>)device{
 IOSMLayerState *retiredState __attribute__((objc_precise_lifetime))=nil;
 @synchronized(self){
  IOSMLayerState *old=layerState(self);
  retiredState=old;
  if(old&&old.device==device)return;
  if(![device isKindOfClass:[IOSMDevice class]]){
   CGSize size=CGSizeZero;BOOL framebufferOnly=YES;NSUInteger maximum=3;
   if(old){[old.condition lock];size=old.size;framebufferOnly=old.framebufferOnly;maximum=old.maximumDrawableCount;old.invalidated=YES;[old.condition broadcast];[old.condition unlock];}
   objc_setAssociatedObject(self,&iosmetal_layer_key,nil,OBJC_ASSOCIATION_RETAIN);[self iosm_setDevice:device];
   if(old){[self iosm_setDrawableSize:size];[self iosm_setFramebufferOnly:framebufferOnly];[self iosm_setMaximumDrawableCount:maximum];}return;
  }
  if(self.pixelFormat!=MTLPixelFormatBGRA8Unorm||self.presentsWithTransaction||self.colorspace||!self.allowsNextDrawableTimeout)invalid(@"Drawable presentation requires BGRA8Unorm, default color space, bounded acquisition and no transaction synchronization");
  IOSMLayerState *state=[IOSMLayerState new];state.layer=self;state.device=(IOSMDevice *)device;state.size=self.drawableSize;state.framebufferOnly=self.framebufferOnly;state.maximumDrawableCount=self.maximumDrawableCount;
  if(old){[old.condition lock];old.invalidated=YES;[old.condition broadcast];[old.condition unlock];}
  objc_setAssociatedObject(self,&iosmetal_layer_key,state,OBJC_ASSOCIATION_RETAIN);
 }
}
- (id<CAMetalDrawable>)iosm_nextDrawable{IOSMLayerState *state=layerState(self);return state?[state acquire]:[self iosm_nextDrawable];}
- (CGSize)iosm_drawableSize{IOSMLayerState *state=layerState(self);if(!state)return [self iosm_drawableSize];[state.condition lock];CGSize size=state.size;[state.condition unlock];return size;}
- (void)iosm_setDrawableSize:(CGSize)size{@synchronized(self){IOSMLayerState *state=layerState(self);if(!state){[self iosm_setDrawableSize:size];return;}if(!isfinite(size.width)||!isfinite(size.height)||size.width<0||size.height<0)invalid(@"Invalid drawable dimensions");[state.condition lock];state.size=size;[state.condition broadcast];[state.condition unlock];}}
- (MTLPixelFormat)iosm_pixelFormat{return layerState(self)?MTLPixelFormatBGRA8Unorm:[self iosm_pixelFormat];}
- (void)iosm_setPixelFormat:(MTLPixelFormat)format{@synchronized(self){if(!layerState(self)){[self iosm_setPixelFormat:format];return;}if(format!=MTLPixelFormatBGRA8Unorm)invalid(@"Only BGRA8Unorm drawable presentation is implemented");}}
- (BOOL)iosm_framebufferOnly{IOSMLayerState *state=layerState(self);if(!state)return [self iosm_framebufferOnly];[state.condition lock];BOOL value=state.framebufferOnly;[state.condition unlock];return value;}
- (void)iosm_setFramebufferOnly:(BOOL)value{@synchronized(self){IOSMLayerState *state=layerState(self);if(!state){[self iosm_setFramebufferOnly:value];return;}[state.condition lock];state.framebufferOnly=value;[state.condition broadcast];[state.condition unlock];}}
- (NSUInteger)iosm_maximumDrawableCount{IOSMLayerState *state=layerState(self);if(!state)return [self iosm_maximumDrawableCount];[state.condition lock];NSUInteger value=state.maximumDrawableCount;[state.condition unlock];return value;}
- (void)iosm_setMaximumDrawableCount:(NSUInteger)value{@synchronized(self){IOSMLayerState *state=layerState(self);if(!state){[self iosm_setMaximumDrawableCount:value];return;}if(value<2||value>3)invalid(@"The drawable pool supports two or three textures");[state.condition lock];state.maximumDrawableCount=value;[state.condition broadcast];[state.condition unlock];}}
- (BOOL)iosm_allowsNextDrawableTimeout{return layerState(self)?YES:[self iosm_allowsNextDrawableTimeout];}
- (void)iosm_setAllowsNextDrawableTimeout:(BOOL)value{@synchronized(self){if(!layerState(self)){[self iosm_setAllowsNextDrawableTimeout:value];return;}if(!value)invalid(@"Unbounded drawable acquisition is not supported");}}
- (BOOL)iosm_presentsWithTransaction{return layerState(self)?NO:[self iosm_presentsWithTransaction];}
- (void)iosm_setColorspace:(CGColorSpaceRef)value{@synchronized(self){if(layerState(self)&&value)invalid(@"Custom drawable color spaces are not implemented");[self iosm_setColorspace:value];}}
- (void)iosm_setPresentsWithTransaction:(BOOL)value{@synchronized(self){if(!layerState(self)){[self iosm_setPresentsWithTransaction:value];return;}if(value)invalid(@"Transaction-synchronized drawable presentation is not implemented");}}
@end
static void iosmetal_install_layer(void){
 static dispatch_once_t once;dispatch_once(&once,^{
  SEL pairs[][2]={{@selector(setColorspace:),@selector(iosm_setColorspace:)},{@selector(device),@selector(iosm_device)},{@selector(setDevice:),@selector(iosm_setDevice:)},{@selector(nextDrawable),@selector(iosm_nextDrawable)},{@selector(drawableSize),@selector(iosm_drawableSize)},{@selector(setDrawableSize:),@selector(iosm_setDrawableSize:)},{@selector(pixelFormat),@selector(iosm_pixelFormat)},{@selector(setPixelFormat:),@selector(iosm_setPixelFormat:)},{@selector(framebufferOnly),@selector(iosm_framebufferOnly)},{@selector(setFramebufferOnly:),@selector(iosm_setFramebufferOnly:)},{@selector(maximumDrawableCount),@selector(iosm_maximumDrawableCount)},{@selector(setMaximumDrawableCount:),@selector(iosm_setMaximumDrawableCount:)},{@selector(allowsNextDrawableTimeout),@selector(iosm_allowsNextDrawableTimeout)},{@selector(setAllowsNextDrawableTimeout:),@selector(iosm_setAllowsNextDrawableTimeout:)},{@selector(presentsWithTransaction),@selector(iosm_presentsWithTransaction)},{@selector(setPresentsWithTransaction:),@selector(iosm_setPresentsWithTransaction:)}};
  for(unsigned i=0;i<sizeof(pairs)/sizeof(pairs[0]);i++){Method original=class_getInstanceMethod([CAMetalLayer class],pairs[i][0]),replacement=class_getInstanceMethod([CAMetalLayer class],pairs[i][1]);if(!original||!replacement)invalid(@"Required public CAMetalLayer method unavailable");method_exchangeImplementations(original,replacement);}
 });
}
