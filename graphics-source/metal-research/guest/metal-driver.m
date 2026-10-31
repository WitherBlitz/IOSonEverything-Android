// Authored Metal adapter for the measured iOS14 public ABI. AGPL-3.0-or-later.
// No private Apple instance layouts or implementation instructions are used.
// Current subset refuses unsupported descriptors and capabilities explicitly.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#include <dispatch/dispatch.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <float.h>
#include "iosgpu_metal.h"
#include "surface_protocol.h"
#include "metal-api-owned.h"
#define TRANSFER_CHUNK (1024u*1024u)
#include "guest-transport.h"
#include "reply-cache.h"
#include "command-batch.h"
@interface IOSMReplyCache:NSObject{NSLock *_cacheLock;struct iosm_reply_cache _cache;}
- (uint8_t *)allocate:(NSUInteger)length reused:(BOOL *)reused;
- (void)recycle:(void *)memory length:(NSUInteger)length;
@end
@implementation IOSMReplyCache
- (instancetype)init{if((self=[super init]))_cacheLock=[NSLock new];return self;}
- (uint8_t *)allocate:(NSUInteger)length reused:(BOOL *)reused{
 if(length<IOSM_REPLY_CACHE_MIN||length>IOSM_REPLY_CACHE_LIMIT){*reused=NO;return malloc(length);}
 [_cacheLock lock];void *p=iosm_reply_cache_take(&_cache,length);[_cacheLock unlock];*reused=p!=NULL;return p?:malloc(length);
}
- (void)recycle:(void *)memory length:(NSUInteger)length{if(!memory)return;if(length<IOSM_REPLY_CACHE_MIN||length>IOSM_REPLY_CACHE_LIMIT){free(memory);return;}[_cacheLock lock];iosm_reply_cache_put(&_cache,memory,length,free);[_cacheLock unlock];}
- (void)dealloc{iosm_reply_cache_clear(&_cache,free);}
@end
@class IOSMDevice,IOSMBuffer,IOSMTexture,IOSMCommand,IOSMQueue;
@protocol IOSMetalDrawableLease
- (BOOL)reserveForCommand:(id)command;
- (void)cancelReservationForCommand:(id)command;
- (void)presentForCommand:(id)command;
@end
static void put32(NSMutableData *d,uint32_t v){[d appendBytes:&v length:4];}
static void put64(NSMutableData *d,uint64_t v){[d appendBytes:&v length:8];}
static uint64_t get64(NSData *d,NSUInteger at){uint64_t v=0;if(at<=d.length&&8<=d.length-at)memcpy(&v,(const uint8_t *)d.bytes+at,8);return v;}
static uint32_t get32(NSData *d,NSUInteger at){uint32_t v=0;if(at<=d.length&&4<=d.length-at)memcpy(&v,(const uint8_t *)d.bytes+at,4);return v;}
static NSError *problem(NSString *message){return [NSError errorWithDomain:@"IOSonEverything.Metal" code:1 userInfo:@{NSLocalizedDescriptionKey:message?:@"Unknown Metal error"}];}
static void invalid(NSString *message){@throw [NSException exceptionWithName:NSInvalidArgumentException reason:message userInfo:nil];}
@interface IOSMDevice:NSObject<MTLDevice>{uint32_t _context;uint64_t _sequence;BOOL _failed;BOOL _profileTransfers;BOOL _sharedFrames;NSRecursiveLock *_lock;NSString *_name;NSUInteger _maximum;NSRecursiveLock *_submissionLock;IOSMReplyCache *_replyCache;struct iosm_command_batch *_encodingBatch;uint64_t _batchedOperations,_batchCrossings;}
- (NSData *)call:(uint32_t)op body:(NSData *)body capacity:(uint32_t)capacity error:(NSError **)error;
- (NSData *)perform:(uint32_t)op body:(NSData *)body capacity:(uint32_t)capacity;
- (void)releaseHandle:(uint64_t)handle;
- (void)beginSubmission;
- (void)endSubmission;
- (BOOL)flushEncoding:(NSError **)error;
- (BOOL)sharedFrames;
- (int64_t)surfaceControl:(const struct iosgpu_surface_request *)request meta:(struct iosgpu_surface_meta *)meta;
@end
@interface IOSMObject:NSObject
@property(nonatomic,strong) IOSMDevice *backendDevice;
@property(nonatomic) uint64_t handle;
@property(nonatomic,copy) NSString *label;
@end
@implementation IOSMObject
- (id<MTLDevice>)device{return self.backendDevice;}
- (void)dealloc{if(_handle)[_backendDevice releaseHandle:_handle];}
@end
@interface IOSMBuffer:IOSMObject<MTLBuffer>{void *_memory;}
@property(nonatomic) NSUInteger length;
- (BOOL)makeShadow;
- (void)upload;
- (void)download;
@end
@interface IOSMTexture:IOSMObject<MTLTexture>
@property(nonatomic,strong) MTLTextureDescriptor *shape;
@property(nonatomic) BOOL framebufferOnlyValue;
- (void)readbackBytes:(void *)bytes bytesPerRow:(NSUInteger)stride fromRegion:(MTLRegion)region mipmapLevel:(NSUInteger)level;
@end
@interface IOSMFunction:IOSMObject<MTLFunction>
@property(nonatomic,copy) NSString *functionName;
@property(nonatomic) MTLFunctionType functionType;
@end
@interface IOSMLibrary:IOSMObject<MTLLibrary>
@property(nonatomic,strong) NSArray<NSString *> *names;
@end
@interface IOSMComputeState:IOSMObject<MTLComputePipelineState>
@property(nonatomic) NSUInteger threadExecutionWidth;
@property(nonatomic) NSUInteger maxTotalThreadsPerThreadgroup;
@property(nonatomic) NSUInteger staticThreadgroupMemoryLength;
@end
@interface IOSMRenderState:IOSMObject<MTLRenderPipelineState>
@end
@interface IOSMSampler:IOSMObject<MTLSamplerState>
@end
@interface IOSMQueue:IOSMObject<MTLCommandQueue>
@end
@interface IOSMCommand:IOSMObject<MTLCommandBuffer>{MTLCommandBufferStatus _status;NSError *_error;BOOL _scheduledDrained;BOOL _completedDrained;NSThread *_callbackThread;}
@property(nonatomic,strong) NSCondition *stateChanged;
@property(nonatomic,strong) IOSMQueue *commandQueue;
@property(nonatomic,strong) NSMutableArray<IOSMBuffer *> *buffers;
@property(nonatomic,strong) NSMutableArray *resources;
@property(nonatomic,strong) NSMutableArray<id<MTLDrawable>> *drawables;
@property(nonatomic,strong) NSMutableArray *scheduledHandlers;
@property(nonatomic,strong) NSMutableArray *completedHandlers;
@property(nonatomic) MTLCommandBufferStatus status;
@property(nonatomic,strong) NSError *error;
@property(nonatomic) BOOL activeEncoder;
- (void)keep:(IOSMBuffer *)buffer;
@end
@interface IOSMComputeEncoder:IOSMObject<MTLComputeCommandEncoder>
@property(nonatomic,strong) IOSMCommand *command;
@end
@interface IOSMRenderEncoder:IOSMObject<MTLRenderCommandEncoder>
@property(nonatomic,strong) IOSMCommand *command;
@end
static IOSMObject *owned(id object,Class kind,IOSMDevice *device){
 if(![object isKindOfClass:kind]||[(IOSMObject *)object backendDevice]!=device)invalid(@"Metal object belongs to another device or has the wrong kind");
 return object;
}
@implementation IOSMDevice
- (instancetype)init{
 if(!(self=[super init]))return nil;_lock=[NSRecursiveLock new];_submissionLock=[NSRecursiveLock new];_sequence=1;
 _replyCache=[IOSMReplyCache new];
 const char *profile=getenv("IOSMETAL_PROFILE_TRANSFERS");_profileTransfers=profile&&!strcmp(profile,"1");
 uint32_t tag[]={IOSGPU_METAL_OPEN_MAGIC,1,1,0},written=0;
 const char *sharedMode=getenv("IOSMETAL_SHARED_FRAMES");if(sharedMode&&!strcmp(sharedMode,"0"))tag[2]=0;
 int64_t opened=guest_rpc(IOSGPU_OPEN,0,tag,sizeof(tag),NULL,0,&written);
 if(opened>0)_sharedFrames=tag[2]!=0;
 else{tag[2]=0;opened=guest_rpc(IOSGPU_OPEN,0,tag,sizeof(tag),NULL,0,&written);}
 if(opened<=0||opened>UINT32_MAX){printf("IOSMETAL_GUEST open_failed=%lld\n",(long long)opened);return nil;}
 _context=(uint32_t)opened;NSError *error=nil;NSData *info=[self call:IOSMETAL_INFO body:nil capacity:1024 error:&error];
 if(info.length<12)return nil;_maximum=(NSUInteger)get64(info,4);_name=[[NSString alloc]initWithBytes:(const uint8_t *)info.bytes+12 length:info.length-12 encoding:NSUTF8StringEncoding];
 if(!_name)return nil;
 NSData *features=[self call:IOSMETAL_FEATURES body:nil capacity:16 error:NULL];const char *batchMode=getenv("IOSMETAL_COMMAND_BATCH");
 if(features.length==16&&get32(features,0)==1&&(get32(features,4)&1)&&get32(features,8)==IOSM_BATCH_MAX_OPERATIONS&&get32(features,12)==IOSM_BATCH_MAX_BYTES&&(!batchMode||strcmp(batchMode,"0"))){_encodingBatch=calloc(1,sizeof(*_encodingBatch));if(_encodingBatch)iosm_batch_clear(_encodingBatch);}
 printf("IOSMETAL_GUEST device=%s context=%u public_subset=1 command_batch=%u shared_frames=%u\n",_name.UTF8String,_context,_encodingBatch!=NULL,_sharedFrames);return self;
}
- (BOOL)sharedFrames{return _sharedFrames&&!_failed;}
- (int64_t)surfaceControl:(const struct iosgpu_surface_request *)request meta:(struct iosgpu_surface_meta *)meta{
 [_lock lock];@try{
  if(!_sharedFrames||_failed||!_context)return -ENOTSUP;
  if(![self flushEncoding:NULL])return -EIO;
  uint32_t written=0;int64_t result=guest_rpc(IOSGPU_METAL_CALL,_context,request,sizeof(*request),meta,meta?sizeof(*meta):0,&written);
  if(result<0)return result;
  if(written!=(meta?sizeof(*meta):0)||(meta&&!iosgpu_surface_meta_valid(meta))){_failed=YES;return -EIO;}return result;
 }@finally{[_lock unlock];}
}
- (void)dealloc{if(_context&&!_failed){uint32_t written=0;(void)guest_rpc(IOSGPU_CLOSE,_context,NULL,0,NULL,0,&written);}free(_encodingBatch);}
- (BOOL)flushEncoding:(NSError **)error{
 if(!_encodingBatch||!_encodingBatch->count)return YES;
 uint32_t count=_encodingBatch->count;NSData *body=[NSData dataWithBytes:_encodingBatch->bytes length:_encodingBatch->used];iosm_batch_clear(_encodingBatch);
 NSData *reply=[self call:IOSMETAL_ENCODER_BATCH body:body capacity:4 error:error];
 if(reply.length!=4||get32(reply,0)!=count){_failed=YES;if(error&&!*error)*error=problem(@"Metal encoder batch acknowledgment mismatch");return NO;}
 uint64_t previous=_batchedOperations;_batchedOperations+=count;_batchCrossings++;
 if(_profileTransfers&&previous/256!=_batchedOperations/256)fprintf(stderr,"IOSMETAL_BATCH_PROFILE operations=%llu crossings=%llu saved_round_trips=%llu\n",(unsigned long long)_batchedOperations,(unsigned long long)_batchCrossings,(unsigned long long)(_batchedOperations-_batchCrossings));
 return YES;
}
- (NSData *)call:(uint32_t)op body:(NSData *)body capacity:(uint32_t)capacity error:(NSError **)error{
 if(error)*error=nil;[_lock lock];NSData *result=nil;uint8_t *allocation=NULL;
 IOSMReplyCache *cache=_replyCache;NSUInteger replyLength=0;BOOL reused=NO;
 BOOL profile=_profileTransfers&&capacity>=512*1024;CFTimeInterval began=profile?CACurrentMediaTime():0,allocated=began,prefaulted=began,returned=began;
 @try{
  if(_failed||!_context){if(error)*error=problem(@"Metal transport is unavailable");return nil;}
  if(body.length>32u*1024*1024-24||capacity>32u*1024*1024-24||_sequence==UINT64_MAX){if(error)*error=problem(@"Metal message exceeds its bound");return nil;}
  if(_encodingBatch&&op!=IOSMETAL_ENCODER_BATCH){
   if(capacity==0&&iosm_batch_body_size(op)&&body.length==iosm_batch_body_size(op)){
    int queued=iosm_batch_push(_encodingBatch,op,body.bytes,body.length);
    if(!queued){if(![self flushEncoding:error])return nil;queued=iosm_batch_push(_encodingBatch,op,body.bytes,body.length);}
    if(queued!=1){_failed=YES;if(error)*error=problem(@"Invalid bounded encoder batch state");return nil;}
    result=[NSData data];return result;
   }
   if(![self flushEncoding:error])return nil;
  }
  NSMutableData *request=[NSMutableData dataWithCapacity:24+body.length];put32(request,IOSMETAL_WIRE_MAGIC);put32(request,1);put32(request,op);put32(request,(uint32_t)body.length);uint64_t sequence=_sequence++;put64(request,sequence);if(body.length)[request appendData:body];
  replyLength=MAX(capacity,1024u)+24;allocation=[cache allocate:replyLength reused:&reused];
  if(!allocation){if(error)*error=problem(@"Unable to allocate bounded Metal reply");return nil;}
  if(profile)allocated=CACurrentMediaTime();
  // Only prefault private reply pages; the host supplies every accepted byte.
  // Avoid zeroing an entire native-resolution frame on the emulated CPU.
  for(NSUInteger at=0;at<replyLength;at+=4096)allocation[at]=0;allocation[replyLength-1]=0;
  if(profile)prefaulted=CACurrentMediaTime();
  NSData *reply=[NSData dataWithBytesNoCopy:allocation length:replyLength freeWhenDone:NO];uint32_t written=0;
  int64_t code=guest_rpc(IOSGPU_METAL_CALL,_context,request.bytes,(uint32_t)request.length,allocation,(uint32_t)replyLength,&written);
  if(profile)returned=CACurrentMediaTime();
  if(code<0||written<24||written>reply.length){_failed=YES;if(error)*error=problem([NSString stringWithFormat:@"Metal transport failure %lld",(long long)code]);return nil;}
  uint32_t size=get32(reply,12);
  if(get32(reply,0)!=IOSMETAL_WIRE_MAGIC||get32(reply,4)!=1||get64(reply,16)!=sequence||size!=written-24){_failed=YES;if(error)*error=problem(@"Metal reply framing mismatch");return nil;}
  int32_t status=(int32_t)get32(reply,8);
  if(status<0){NSString *why=[[NSString alloc]initWithBytes:(const uint8_t *)reply.bytes+24 length:size encoding:NSUTF8StringEncoding];if(error)*error=problem(why?:@"Metal backend refused the operation");return nil;}
  // Only the last immutable reader returns this allocation to the bounded
  // cache. Its independent owner can outlive this device and any CGImage.
  uint8_t *storage=allocation;
  result=[[NSData alloc]initWithBytesNoCopy:allocation+24 length:size deallocator:^(void *bytes,NSUInteger length){
   (void)bytes;(void)length;[cache recycle:storage length:replyLength];
  }];
  if(result)allocation=NULL;
 }@finally{if(profile){CFTimeInterval ended=CACurrentMediaTime();fprintf(stderr,"IOSMETAL_TRANSFER_PROFILE op=%u capacity=%u bytes=%lu allocation_ms=%.3f prefault_ms=%.3f rpc_ms=%.3f wrapping_ms=%.3f success=%u reused=%u\n",op,capacity,(unsigned long)result.length,(allocated-began)*1000,(prefaulted-allocated)*1000,(returned-prefaulted)*1000,(ended-returned)*1000,result!=nil,reused);fflush(stderr);}[cache recycle:allocation length:replyLength];[_lock unlock];}return result;
}
- (NSData *)perform:(uint32_t)op body:(NSData *)body capacity:(uint32_t)capacity{NSError *error=nil;NSData *data=[self call:op body:body capacity:capacity error:&error];if(!data)invalid(error.localizedDescription);return data;}
- (void)releaseHandle:(uint64_t)handle{if(!handle||_failed)return;NSMutableData *body=[NSMutableData data];put64(body,handle);NSError *error=nil;(void)[self call:IOSMETAL_OBJECT_RELEASE body:body capacity:0 error:&error];if(error)printf("IOSMETAL_GUEST release_error=%s\n",error.localizedDescription.UTF8String);}
- (void)beginSubmission{[_submissionLock lock];}
- (void)endSubmission{[_submissionLock unlock];}
- (NSString *)name{return _name;}
- (NSUInteger)maxBufferLength{return _maximum;}
- (MTLSize)maxThreadsPerThreadgroup{return MTLSizeMake(64,1,1);}
- (BOOL)hasUnifiedMemory{return YES;}
- (BOOL)isLowPower{return YES;}
- (BOOL)isHeadless{return NO;}
- (BOOL)isRemovable{return NO;}
- (uint64_t)registryID{return UINT64_C(0x494f534d00000001);}
- (BOOL)supportsFeatureSet:(MTLFeatureSet)set{(void)set;return NO;}
- (BOOL)supportsFamily:(MTLGPUFamily)family{(void)family;return NO;}
- (BOOL)supportsTextureSampleCount:(NSUInteger)n{return n==1;}
- (BOOL)areRasterOrderGroupsSupported{return NO;}
- (BOOL)supportsRasterOrderGroups{return NO;}
- (BOOL)areProgrammableSamplePositionsSupported{return NO;}
- (BOOL)supportsBCTextureCompression{return NO;}
- (BOOL)supportsPullModelInterpolation{return NO;}
- (BOOL)supports32BitFloatFiltering{return NO;}
- (BOOL)supports32BitMSAA{return NO;}
- (BOOL)supportsFunctionPointers{return NO;}
- (BOOL)supportsRaytracing{return NO;}
- (id<MTLBuffer>)newBufferWithLength:(NSUInteger)length options:(MTLResourceOptions)options{
 if(!length||length>_maximum||options!=MTLResourceStorageModeShared)return nil;
 NSMutableData *body=[NSMutableData data];put64(body,length);put64(body,0);NSError *error=nil;NSData *data=[self call:IOSMETAL_BUFFER_NEW body:body capacity:8 error:&error];if(!data)return nil;
 IOSMBuffer *buffer=[IOSMBuffer new];buffer.backendDevice=self;buffer.handle=get64(data,0);buffer.length=length;if(![buffer makeShadow])return nil;return buffer;
}
- (id<MTLBuffer>)newBufferWithBytes:(const void *)bytes length:(NSUInteger)length options:(MTLResourceOptions)options{
 if(!bytes&&length)return nil;id<MTLBuffer> buffer=[self newBufferWithLength:length options:options];if(buffer)memcpy(buffer.contents,bytes,length);return buffer;
}
- (id<MTLTexture>)newTextureWithDescriptor:(MTLTextureDescriptor *)descriptor{
 if(descriptor.textureType!=MTLTextureType2D||descriptor.depth!=1||descriptor.arrayLength!=1||descriptor.mipmapLevelCount!=1||descriptor.sampleCount!=1||descriptor.width>8192||descriptor.height>8192||descriptor.usage&~7u)return nil;
 if(descriptor.storageMode!=MTLStorageModeShared&&descriptor.storageMode!=MTLStorageModePrivate)return nil;
 NSMutableData *body=[NSMutableData data];put32(body,(uint32_t)descriptor.pixelFormat);put32(body,(uint32_t)descriptor.width);put32(body,(uint32_t)descriptor.height);put32(body,(uint32_t)descriptor.usage);
 NSError *error=nil;NSData *data=[self call:IOSMETAL_TEXTURE_NEW body:body capacity:8 error:&error];if(!data)return nil;
 IOSMTexture *texture=[IOSMTexture new];texture.backendDevice=self;texture.handle=get64(data,0);texture.shape=[descriptor copy];return texture;
}
- (id<MTLSamplerState>)newSamplerStateWithDescriptor:(MTLSamplerDescriptor *)d{
 if(!d||d.minFilter>MTLSamplerMinMagFilterLinear||d.magFilter>MTLSamplerMinMagFilterLinear||d.mipFilter!=MTLSamplerMipFilterNotMipmapped||!d.normalizedCoordinates||d.maxAnisotropy!=1||d.compareFunction!=MTLCompareFunctionNever||d.lodAverage||d.lodMinClamp!=0||d.lodMaxClamp!=FLT_MAX)return nil;
 // Native iOS14 descriptors do not expose every getter in the build SDK.
 // Border colors cannot affect either admitted address mode; absent fields
 // must not turn a default descriptor into an unrecognized-selector exception.
 if(([d respondsToSelector:@selector(borderColor)]&&d.borderColor!=MTLSamplerBorderColorTransparentBlack)||([d respondsToSelector:@selector(supportArgumentBuffers)]&&d.supportArgumentBuffers))return nil;
 if((d.sAddressMode!=MTLSamplerAddressModeClampToEdge&&d.sAddressMode!=MTLSamplerAddressModeRepeat)||(d.tAddressMode!=MTLSamplerAddressModeClampToEdge&&d.tAddressMode!=MTLSamplerAddressModeRepeat)||(d.rAddressMode!=MTLSamplerAddressModeClampToEdge&&d.rAddressMode!=MTLSamplerAddressModeRepeat))return nil;
 NSMutableData *body=[NSMutableData data];put32(body,(uint32_t)d.minFilter);put32(body,(uint32_t)d.magFilter);put32(body,(uint32_t)d.sAddressMode);put32(body,(uint32_t)d.tAddressMode);put32(body,(uint32_t)d.rAddressMode);put32(body,1);
 NSError *error=nil;NSData *data=[self call:IOSMETAL_SAMPLER_NEW body:body capacity:8 error:&error];if(!data)return nil;
 IOSMSampler *sampler=[IOSMSampler new];sampler.backendDevice=self;sampler.handle=get64(data,0);sampler.label=d.label;return sampler;
}
- (id<MTLLibrary>)newLibraryWithData:(dispatch_data_t)data error:(NSError **)error{
 if(!data||!dispatch_data_get_size(data)||dispatch_data_get_size(data)>8u*1024*1024){if(error)*error=problem(@"A nonempty metallib of at most8MiB is required");return nil;}
 const void *bytes=NULL;size_t size=0;dispatch_data_t mapped __attribute__((objc_precise_lifetime))=dispatch_data_create_map(data,&bytes,&size);
 if(!mapped||size>8u*1024*1024){if(error)*error=problem(@"Metallib exceeds the shader input bound");return nil;}
 NSMutableData *body=[NSMutableData data];put32(body,1);[body appendBytes:bytes length:size];NSData *reply=[self call:IOSMETAL_LIBRARY_NEW body:body capacity:8 error:error];if(!reply)return nil;
 IOSMLibrary *library=[IOSMLibrary new];library.backendDevice=self;library.handle=get64(reply,0);return library;
}
- (id<MTLLibrary>)newLibraryWithFile:(NSString *)file error:(NSError **)error{
 NSData *bytes=[NSData dataWithContentsOfFile:file options:NSDataReadingMappedIfSafe error:error];if(!bytes)return nil;
 if(!bytes.length||bytes.length>8u*1024*1024){if(error)*error=problem(@"Metallib file exceeds its bound");return nil;}
 dispatch_data_t data=dispatch_data_create(bytes.bytes,bytes.length,NULL,DISPATCH_DATA_DESTRUCTOR_DEFAULT);return [self newLibraryWithData:data error:error];
}
- (id<MTLLibrary>)newLibraryWithURL:(NSURL *)url error:(NSError **)error{if(!url.isFileURL){if(error)*error=problem(@"Only local metallib files are supported");return nil;}return [self newLibraryWithFile:url.path error:error];}
- (id<MTLLibrary>)newDefaultLibrary{return [self newDefaultLibraryWithBundle:[NSBundle mainBundle] error:NULL];}
- (id<MTLLibrary>)newDefaultLibraryWithBundle:(NSBundle *)bundle error:(NSError **)error{NSString *path=[bundle pathForResource:@"default" ofType:@"metallib"];if(!path){if(error)*error=problem(@"Bundle has no default.metallib");return nil;}return [self newLibraryWithFile:path error:error];}
- (id<MTLLibrary>)newLibraryWithSource:(NSString *)source options:(MTLCompileOptions *)options error:(NSError **)error{(void)source;(void)options;if(error)*error=problem(@"MSL source compilation is not implemented; supply a compiled metallib");return nil;}
- (id<MTLComputePipelineState>)newComputePipelineStateWithFunction:(id<MTLFunction>)function error:(NSError **)error{
 IOSMFunction *fn=(IOSMFunction *)owned(function,[IOSMFunction class],self);NSMutableData *body=[NSMutableData data];put64(body,fn.handle);
 NSData *data=[self call:IOSMETAL_COMPUTE_PIPELINE_NEW body:body capacity:20 error:error];if(data.length!=20)return nil;
 IOSMComputeState *state=[IOSMComputeState new];state.backendDevice=self;state.handle=get64(data,0);state.threadExecutionWidth=get32(data,8);state.maxTotalThreadsPerThreadgroup=get32(data,12);state.staticThreadgroupMemoryLength=get32(data,16);return state;
}
- (id<MTLRenderPipelineState>)newRenderPipelineStateWithDescriptor:(MTLRenderPipelineDescriptor *)descriptor error:(NSError **)error{
 if(descriptor.sampleCount!=1||descriptor.depthAttachmentPixelFormat!=MTLPixelFormatInvalid||descriptor.stencilAttachmentPixelFormat!=MTLPixelFormatInvalid||!descriptor.rasterizationEnabled||descriptor.alphaToCoverageEnabled||descriptor.alphaToOneEnabled||descriptor.inputPrimitiveTopology!=MTLPrimitiveTopologyClassUnspecified||descriptor.tessellationFactorFormat!=MTLTessellationFactorFormatHalf||descriptor.tessellationPartitionMode!=MTLTessellationPartitionModePow2||descriptor.maxTessellationFactor!=16){if(error)*error=problem(@"Render descriptor needs a single color attachment, no depth/stencil in this subset");return nil;}
 MTLRenderPipelineColorAttachmentDescriptor *color=descriptor.colorAttachments[0];
 if((NSUInteger)color.sourceRGBBlendFactor>UINT32_MAX||(NSUInteger)color.destinationRGBBlendFactor>UINT32_MAX||(NSUInteger)color.rgbBlendOperation>UINT32_MAX||(NSUInteger)color.sourceAlphaBlendFactor>UINT32_MAX||(NSUInteger)color.destinationAlphaBlendFactor>UINT32_MAX||(NSUInteger)color.alphaBlendOperation>UINT32_MAX||((NSUInteger)color.writeMask&~(NSUInteger)MTLColorWriteMaskAll)){if(error)*error=problem(@"Color attachment fields exceed supported bounds");return nil;}
 BOOL colorState=color.blendingEnabled||color.writeMask!=MTLColorWriteMaskAll||color.sourceRGBBlendFactor!=MTLBlendFactorOne||color.destinationRGBBlendFactor!=MTLBlendFactorZero||color.rgbBlendOperation!=MTLBlendOperationAdd||color.sourceAlphaBlendFactor!=MTLBlendFactorOne||color.destinationAlphaBlendFactor!=MTLBlendFactorZero||color.alphaBlendOperation!=MTLBlendOperationAdd;
 NSMutableData *attributes=[NSMutableData data],*layouts=[NSMutableData data];uint32_t attributeCount=0,layoutCount=0;BOOL usedBuffers[31]={NO};
 if(descriptor.vertexDescriptor){
  for(unsigned i=0;i<31;i++){
   MTLVertexAttributeDescriptor *attribute=descriptor.vertexDescriptor.attributes[i];if(attribute.format==MTLVertexFormatInvalid)continue;
   if(attribute.bufferIndex>=31||attribute.offset>UINT32_MAX||(NSUInteger)attribute.format>UINT32_MAX){if(error)*error=problem(@"Vertex attribute fields exceed supported bounds");return nil;}
   attributeCount++;usedBuffers[attribute.bufferIndex]=YES;put32(attributes,i);put32(attributes,(uint32_t)attribute.format);put64(attributes,attribute.offset);put32(attributes,(uint32_t)attribute.bufferIndex);
  }
  for(unsigned i=0;i<31;i++){
   MTLVertexBufferLayoutDescriptor *layout=descriptor.vertexDescriptor.layouts[i];
   if(!usedBuffers[i]&&!layout.stride&&layout.stepFunction==MTLVertexStepFunctionPerVertex&&layout.stepRate==1)continue;
   if(layout.stride>UINT32_MAX||layout.stepRate>UINT32_MAX||(NSUInteger)layout.stepFunction>UINT32_MAX){if(error)*error=problem(@"Dynamic or wide vertex layout fields are not implemented");return nil;}
   layoutCount++;put32(layouts,i);put64(layouts,layout.stride);put32(layouts,(uint32_t)layout.stepFunction);put64(layouts,layout.stepRate);
  }
 }
 for(unsigned i=1;i<8;i++)if(descriptor.colorAttachments[i].pixelFormat!=MTLPixelFormatInvalid){if(error)*error=problem(@"Multiple color attachments are not implemented");return nil;}
 IOSMFunction *vertex=(IOSMFunction *)owned(descriptor.vertexFunction,[IOSMFunction class],self),*fragment=(IOSMFunction *)owned(descriptor.fragmentFunction,[IOSMFunction class],self);
 NSMutableData *body=[NSMutableData data];put64(body,vertex.handle);put64(body,fragment.handle);put32(body,(uint32_t)descriptor.colorAttachments[0].pixelFormat);
 uint32_t operation=IOSMETAL_RENDER_PIPELINE_NEW;
 if(descriptor.vertexDescriptor||colorState){operation=colorState?IOSMETAL_RENDER_PIPELINE_COLOR_STATE_NEW:IOSMETAL_RENDER_PIPELINE_VERTEX_LAYOUT_NEW;put32(body,attributeCount);[body appendData:attributes];put32(body,layoutCount);[body appendData:layouts];}
 if(colorState){put32(body,color.blendingEnabled?1:0);put32(body,(uint32_t)color.sourceRGBBlendFactor);put32(body,(uint32_t)color.destinationRGBBlendFactor);put32(body,(uint32_t)color.rgbBlendOperation);put32(body,(uint32_t)color.sourceAlphaBlendFactor);put32(body,(uint32_t)color.destinationAlphaBlendFactor);put32(body,(uint32_t)color.alphaBlendOperation);put32(body,(uint32_t)color.writeMask);}
 NSData *data=[self call:operation body:body capacity:8 error:error];if(!data)return nil;
 IOSMRenderState *state=[IOSMRenderState new];state.backendDevice=self;state.handle=get64(data,0);return state;
}
- (id<MTLCommandQueue>)newCommandQueue{
 NSError *error=nil;NSData *data=[self call:IOSMETAL_QUEUE_NEW body:nil capacity:8 error:&error];if(!data)return nil;
 IOSMQueue *queue=[IOSMQueue new];queue.backendDevice=self;queue.handle=get64(data,0);return queue;
}
@end
@implementation IOSMBuffer
- (BOOL)makeShadow{_memory=calloc(1,self.length);return _memory!=NULL;}
- (void)dealloc{free(_memory);}
- (void *)contents{return _memory;}
- (void)upload{
 for(NSUInteger at=0;at<self.length;){NSUInteger size=MIN(TRANSFER_CHUNK,self.length-at);NSMutableData *body=[NSMutableData data];put64(body,self.handle);put64(body,at);[body appendBytes:(uint8_t *)_memory+at length:size];[self.backendDevice perform:IOSMETAL_BUFFER_UPLOAD body:body capacity:0];at+=size;}
}
- (void)download{
 for(NSUInteger at=0;at<self.length;){NSUInteger size=MIN(TRANSFER_CHUNK,self.length-at);NSMutableData *body=[NSMutableData data];put64(body,self.handle);put64(body,at);put32(body,(uint32_t)size);NSData *data=[self.backendDevice perform:IOSMETAL_BUFFER_READ body:body capacity:(uint32_t)size];if(data.length!=size)invalid(@"Buffer readback length mismatch");memcpy((uint8_t *)_memory+at,data.bytes,size);at+=size;}
}
- (MTLStorageMode)storageMode{return MTLStorageModeShared;}
- (MTLCPUCacheMode)cpuCacheMode{return MTLCPUCacheModeDefaultCache;}
- (MTLHazardTrackingMode)hazardTrackingMode{return MTLHazardTrackingModeTracked;}
- (MTLResourceOptions)resourceOptions{return MTLResourceStorageModeShared;}
- (void)didModifyRange:(NSRange)range{if(range.location>self.length||range.length>self.length-range.location)invalid(@"Buffer modification range exceeds its length");}
@end
@implementation IOSMFunction
- (NSString *)name{return self.functionName;}
- (NSArray *)vertexAttributes{return nil;}
- (NSDictionary *)functionConstantsDictionary{invalid(@"Function-constant reflection is not implemented");return nil;}
- (MTLPatchType)patchType{return MTLPatchTypeNone;}
- (NSInteger)patchControlPointCount{return -1;}
@end
@implementation IOSMLibrary
- (NSArray<NSString *> *)functionNames{
 if(_names)return _names;NSMutableData *body=[NSMutableData data];put64(body,self.handle);NSData *data=[self.backendDevice perform:IOSMETAL_LIBRARY_NAMES body:body capacity:512*1024];
 uint32_t count=get32(data,0);if(data.length<4||count>4096)invalid(@"Malformed function table");NSUInteger at=4;NSMutableArray *names=[NSMutableArray arrayWithCapacity:count];
 for(uint32_t i=0;i<count;i++){if(at>data.length||4>data.length-at)invalid(@"Truncated function table");uint32_t size=get32(data,at);at+=4;if(size>data.length-at)invalid(@"Truncated function name");NSString *name=[[NSString alloc]initWithBytes:(const uint8_t *)data.bytes+at length:size encoding:NSUTF8StringEncoding];if(!name)invalid(@"Invalid UTF8 function name");[names addObject:name];at+=size;}
 if(at!=data.length)invalid(@"Trailing function table bytes");_names=[names copy];return _names;
}
- (id<MTLFunction>)newFunctionWithName:(NSString *)name{
 NSData *utf8=[name dataUsingEncoding:NSUTF8StringEncoding];if(!utf8.length||utf8.length>256)return nil;
 NSMutableData *body=[NSMutableData data];put64(body,self.handle);put32(body,(uint32_t)utf8.length);[body appendData:utf8];NSError *error=nil;NSData *data=[self.backendDevice call:IOSMETAL_FUNCTION_NEW body:body capacity:12 error:&error];if(data.length!=12)return nil;
 IOSMFunction *function=[IOSMFunction new];function.backendDevice=self.backendDevice;function.handle=get64(data,0);function.functionName=name;function.functionType=(MTLFunctionType)get32(data,8);return function;
}
- (MTLLibraryType)type{return MTLLibraryTypeExecutable;}
@end
@implementation IOSMComputeState
@end
@implementation IOSMRenderState
@end
@implementation IOSMSampler
@end
@implementation IOSMQueue
- (id<MTLCommandBuffer>)commandBuffer{
 NSMutableData *body=[NSMutableData data];put64(body,self.handle);NSError *error=nil;NSData *data=[self.backendDevice call:IOSMETAL_COMMAND_NEW body:body capacity:8 error:&error];if(!data)return nil;
 IOSMCommand *command=[IOSMCommand new];command.backendDevice=self.backendDevice;command.commandQueue=self;command.handle=get64(data,0);command.buffers=[NSMutableArray array];command.resources=[NSMutableArray array];command.drawables=[NSMutableArray array];command.scheduledHandlers=[NSMutableArray array];command.completedHandlers=[NSMutableArray array];command.stateChanged=[NSCondition new];command.status=MTLCommandBufferStatusNotEnqueued;return command;
}
@end
@implementation IOSMCommand
@synthesize status=_status,error=_error;
- (MTLCommandBufferStatus)status{[self.stateChanged lock];MTLCommandBufferStatus value=_status;[self.stateChanged unlock];return value;}
- (void)setStatus:(MTLCommandBufferStatus)value{[self.stateChanged lock];_status=value;[self.stateChanged broadcast];[self.stateChanged unlock];}
- (NSError *)error{[self.stateChanged lock];NSError *value=_error;[self.stateChanged unlock];return value;}
- (void)setError:(NSError *)value{[self.stateChanged lock];_error=value;[self.stateChanged unlock];}
- (void)keep:(IOSMBuffer *)buffer{if(![self.buffers containsObject:buffer])[self.buffers addObject:buffer];}
- (BOOL)retainedReferences{return YES;}
- (id<MTLComputeCommandEncoder>)computeCommandEncoder{
 if(self.activeEncoder||self.status!=MTLCommandBufferStatusNotEnqueued)invalid(@"Command buffer is already committed or has an open encoder");
 NSMutableData *body=[NSMutableData data];put64(body,self.handle);NSData *data=[self.backendDevice perform:IOSMETAL_COMPUTE_ENCODER_NEW body:body capacity:8];
 IOSMComputeEncoder *encoder=[IOSMComputeEncoder new];encoder.backendDevice=self.backendDevice;encoder.command=self;encoder.handle=get64(data,0);self.activeEncoder=YES;return encoder;
}
- (id<MTLRenderCommandEncoder>)renderCommandEncoderWithDescriptor:(MTLRenderPassDescriptor *)descriptor{
 if(self.activeEncoder||self.status!=MTLCommandBufferStatusNotEnqueued)invalid(@"Command buffer is already committed or has an open encoder");
 if(descriptor.depthAttachment.texture||descriptor.stencilAttachment.texture)invalid(@"Depth/stencil render attachments are not implemented");
 for(unsigned i=1;i<8;i++)if(descriptor.colorAttachments[i].texture)invalid(@"Multiple render attachments are not implemented");
 MTLRenderPassColorAttachmentDescriptor *color=descriptor.colorAttachments[0];IOSMTexture *target=(IOSMTexture *)owned(color.texture,[IOSMTexture class],self.backendDevice);
 if(color.level||color.slice||color.depthPlane||color.resolveTexture)invalid(@"Render attachment subresources/resolve are not implemented");
 NSMutableData *body=[NSMutableData data];put64(body,self.handle);put64(body,target.handle);put32(body,(uint32_t)color.loadAction);put32(body,(uint32_t)color.storeAction);MTLClearColor clear=color.clearColor;[body appendBytes:&clear length:sizeof(clear)];
 NSData *data=[self.backendDevice perform:IOSMETAL_RENDER_ENCODER_NEW body:body capacity:8];IOSMRenderEncoder *encoder=[IOSMRenderEncoder new];encoder.backendDevice=self.backendDevice;encoder.command=self;encoder.handle=get64(data,0);[self.resources addObject:target];self.activeEncoder=YES;return encoder;
}
- (void)addScheduledHandler:(MTLCommandBufferHandler)handler{
 if(!handler)invalid(@"Missing scheduled handler");[self.stateChanged lock];if(_status>=MTLCommandBufferStatusCommitted){[self.stateChanged unlock];invalid(@"Register scheduled handlers before commit");}[self.scheduledHandlers addObject:[handler copy]];[self.stateChanged unlock];
}
- (void)addCompletedHandler:(MTLCommandBufferHandler)handler{
 if(!handler)invalid(@"Missing completion handler");[self.stateChanged lock];if(_status>=MTLCommandBufferStatusCommitted){[self.stateChanged unlock];invalid(@"Register completion handlers before commit");}[self.completedHandlers addObject:[handler copy]];[self.stateChanged unlock];
}
- (void)presentDrawable:(id<MTLDrawable>)drawable{
 if(![(id)drawable isKindOfClass:NSClassFromString(@"IOSMDrawable")]||[(id<CAMetalDrawable>)drawable texture].device!=self.backendDevice)invalid(@"Drawable belongs to a different Metal implementation");
 [self.stateChanged lock];if(_status!=MTLCommandBufferStatusNotEnqueued||[self.drawables containsObject:drawable]){[self.stateChanged unlock];invalid(@"Queue each drawable once before committing");}if(![(id<IOSMetalDrawableLease>)drawable reserveForCommand:self]){[self.stateChanged unlock];invalid(@"Drawable is already reserved or presented");}[self.drawables addObject:drawable];[self.stateChanged unlock];
}
- (void)commit{
 [self.stateChanged lock];if(self.activeEncoder||_status!=MTLCommandBufferStatusNotEnqueued){[self.stateChanged unlock];invalid(@"Commit requires an uncommitted command with no open encoder");}_status=MTLCommandBufferStatusCommitted;[self.stateChanged broadcast];[self.stateChanged unlock];
 NSError *failure=nil;[self.backendDevice beginSubmission];
 @try{
  for(IOSMBuffer *buffer in self.buffers)[buffer upload];
  NSMutableData *body=[NSMutableData data];put64(body,self.handle);[self.backendDevice perform:IOSMETAL_COMMAND_COMMIT body:body capacity:8];
  for(IOSMBuffer *buffer in self.buffers)[buffer download];
  for(id<IOSMetalDrawableLease> drawable in self.drawables)[drawable presentForCommand:self];
 }@catch(NSException *exception){failure=problem(exception.reason);}@finally{[self.backendDevice endSubmission];}
 for(id<IOSMetalDrawableLease> drawable in self.drawables)[drawable cancelReservationForCommand:self];
 // Host commit waits the GPU; publish completion only after guest copyback.
 // Callbacks run outside locks and see coherent shared shadows, including reentrant work.
 [self.stateChanged lock];_error=failure;_status=failure?MTLCommandBufferStatusError:MTLCommandBufferStatusCompleted;
 [self.drawables removeAllObjects];NSArray *scheduled=[self.scheduledHandlers copy],*completed=[self.completedHandlers copy];[self.scheduledHandlers removeAllObjects];[self.completedHandlers removeAllObjects];_callbackThread=[NSThread currentThread];[self.stateChanged broadcast];[self.stateChanged unlock];
 NSException *callbackError=nil;
 for(MTLCommandBufferHandler handler in scheduled){@try{handler(self);}@catch(NSException *e){if(!callbackError)callbackError=e;}}
 [self.stateChanged lock];_scheduledDrained=YES;[self.stateChanged broadcast];[self.stateChanged unlock];
 for(MTLCommandBufferHandler handler in completed){@try{handler(self);}@catch(NSException *e){if(!callbackError)callbackError=e;}}
 [self.stateChanged lock];_completedDrained=YES;_callbackThread=nil;[self.stateChanged broadcast];[self.stateChanged unlock];
 if(callbackError)@throw callbackError;
}
- (void)waitForStatus:(MTLCommandBufferStatus)target{
 [self.stateChanged lock];if(_status<MTLCommandBufferStatusCommitted){[self.stateChanged unlock];invalid(@"Waiting before commit is not supported by this serialized adapter");}
 BOOL completed=target==MTLCommandBufferStatusCompleted;
 if(_callbackThread==[NSThread currentThread]&&!(completed?_completedDrained:_scheduledDrained)){[self.stateChanged unlock];invalid(@"A Metal callback cannot wait for its own callback group");}
 while(_status<target||!(completed?_completedDrained:_scheduledDrained))[self.stateChanged wait];[self.stateChanged unlock];
}
- (void)waitUntilCompleted{[self waitForStatus:MTLCommandBufferStatusCompleted];}
- (void)waitUntilScheduled{[self waitForStatus:MTLCommandBufferStatusScheduled];}

@end
static void bindBuffer(IOSMObject *encoder,IOSMCommand *command,id<MTLBuffer> buffer,NSUInteger offset,NSUInteger index,uint32_t stage){
 IOSMBuffer *value=(IOSMBuffer *)owned(buffer,[IOSMBuffer class],encoder.backendDevice);if(offset>value.length||index>=31)invalid(@"Buffer binding exceeds its bounds");
 NSMutableData *body=[NSMutableData data];put64(body,encoder.handle);put64(body,value.handle);put64(body,offset);put32(body,(uint32_t)index);put32(body,stage);[encoder.backendDevice perform:IOSMETAL_BUFFER_SET body:body capacity:0];[command keep:value];
}
static void bindTextureOrSampler(IOSMObject *encoder,IOSMCommand *command,id object,NSUInteger index,uint32_t stage,BOOL sampler){
 if(index>=(sampler?16:31))invalid(@"Texture or sampler binding exceeds its bounds");
 IOSMObject *value=object?owned(object,sampler?[IOSMSampler class]:[IOSMTexture class],encoder.backendDevice):nil;
 NSMutableData *body=[NSMutableData data];put64(body,encoder.handle);put64(body,value.handle);put32(body,(uint32_t)index);put32(body,stage);[encoder.backendDevice perform:sampler?IOSMETAL_SAMPLER_SET:IOSMETAL_TEXTURE_SET body:body capacity:0];
 if(value&&![command.resources containsObject:value])[command.resources addObject:value];
}
@implementation IOSMComputeEncoder
- (void)setComputePipelineState:(id<MTLComputePipelineState>)state{IOSMComputeState *value=(IOSMComputeState *)owned(state,[IOSMComputeState class],self.backendDevice);NSMutableData *body=[NSMutableData data];put64(body,self.handle);put64(body,value.handle);[self.backendDevice perform:IOSMETAL_COMPUTE_PIPELINE_SET body:body capacity:0];[self.command.resources addObject:value];}
- (void)setBuffer:(id<MTLBuffer>)buffer offset:(NSUInteger)offset atIndex:(NSUInteger)index{bindBuffer(self,self.command,buffer,offset,index,0);}
- (void)setTexture:(id<MTLTexture>)texture atIndex:(NSUInteger)index{bindTextureOrSampler(self,self.command,texture,index,0,NO);}
- (void)setSamplerState:(id<MTLSamplerState>)sampler atIndex:(NSUInteger)index{bindTextureOrSampler(self,self.command,sampler,index,0,YES);}
- (void)dispatch:(MTLSize)grid group:(MTLSize)group mode:(uint32_t)mode{NSMutableData *body=[NSMutableData data];put64(body,self.handle);for(unsigned i=0;i<3;i++)put64(body,((NSUInteger *)&grid)[i]);for(unsigned i=0;i<3;i++)put64(body,((NSUInteger *)&group)[i]);put32(body,mode);[self.backendDevice perform:IOSMETAL_DISPATCH body:body capacity:0];}
- (void)dispatchThreads:(MTLSize)grid threadsPerThreadgroup:(MTLSize)group{[self dispatch:grid group:group mode:0];}
- (void)dispatchThreadgroups:(MTLSize)grid threadsPerThreadgroup:(MTLSize)group{[self dispatch:grid group:group mode:1];}
- (void)endEncoding{if(!self.handle)invalid(@"Encoder already ended");NSMutableData *body=[NSMutableData data];put64(body,self.handle);[self.backendDevice perform:IOSMETAL_ENCODER_END body:body capacity:0];self.handle=0;self.command.activeEncoder=NO;}
@end
@implementation IOSMRenderEncoder
- (void)setBlendColorRed:(float)red green:(float)green blue:(float)blue alpha:(float)alpha{
 if(!self.handle)invalid(@"Encoder already ended");float values[]={red,green,blue,alpha};for(unsigned i=0;i<4;i++)if(!__builtin_isfinite(values[i]))invalid(@"Blend color values must be finite");
 NSMutableData *body=[NSMutableData data];put64(body,self.handle);for(unsigned i=0;i<4;i++){uint32_t bits;memcpy(&bits,values+i,4);put32(body,bits);}[self.backendDevice perform:IOSMETAL_BLEND_COLOR_SET body:body capacity:0];
}
- (void)setRenderPipelineState:(id<MTLRenderPipelineState>)state{IOSMRenderState *value=(IOSMRenderState *)owned(state,[IOSMRenderState class],self.backendDevice);NSMutableData *body=[NSMutableData data];put64(body,self.handle);put64(body,value.handle);[self.backendDevice perform:IOSMETAL_RENDER_PIPELINE_SET body:body capacity:0];[self.command.resources addObject:value];}
- (void)setVertexBuffer:(id<MTLBuffer>)buffer offset:(NSUInteger)offset atIndex:(NSUInteger)index{bindBuffer(self,self.command,buffer,offset,index,1);}
- (void)setFragmentBuffer:(id<MTLBuffer>)buffer offset:(NSUInteger)offset atIndex:(NSUInteger)index{bindBuffer(self,self.command,buffer,offset,index,2);}
- (void)setVertexTexture:(id<MTLTexture>)texture atIndex:(NSUInteger)index{bindTextureOrSampler(self,self.command,texture,index,1,NO);}
- (void)setFragmentTexture:(id<MTLTexture>)texture atIndex:(NSUInteger)index{bindTextureOrSampler(self,self.command,texture,index,2,NO);}
- (void)setVertexSamplerState:(id<MTLSamplerState>)sampler atIndex:(NSUInteger)index{bindTextureOrSampler(self,self.command,sampler,index,1,YES);}
- (void)setFragmentSamplerState:(id<MTLSamplerState>)sampler atIndex:(NSUInteger)index{bindTextureOrSampler(self,self.command,sampler,index,2,YES);}
- (void)drawPrimitives:(MTLPrimitiveType)type vertexStart:(NSUInteger)start vertexCount:(NSUInteger)count{[self drawPrimitives:type vertexStart:start vertexCount:count instanceCount:1 baseInstance:0];}
- (void)drawPrimitives:(MTLPrimitiveType)type vertexStart:(NSUInteger)start vertexCount:(NSUInteger)count instanceCount:(NSUInteger)instances{[self drawPrimitives:type vertexStart:start vertexCount:count instanceCount:instances baseInstance:0];}
- (void)drawPrimitives:(MTLPrimitiveType)type vertexStart:(NSUInteger)start vertexCount:(NSUInteger)count instanceCount:(NSUInteger)instances baseInstance:(NSUInteger)base{NSMutableData *body=[NSMutableData data];put64(body,self.handle);put32(body,(uint32_t)type);put64(body,start);put64(body,count);put64(body,instances);put64(body,base);[self.backendDevice perform:IOSMETAL_DRAW body:body capacity:0];}
- (void)endEncoding{if(!self.handle)invalid(@"Encoder already ended");NSMutableData *body=[NSMutableData data];put64(body,self.handle);[self.backendDevice perform:IOSMETAL_ENCODER_END body:body capacity:0];self.handle=0;self.command.activeEncoder=NO;}
@end
@implementation IOSMTexture
- (NSData *)displayPixels{
 NSUInteger row=self.width*4,total=row*self.height;
 if(total<=IOSGPU_MAX_BYTES-24){
  NSData *data=[self.backendDevice perform:IOSMETAL_TEXTURE_READ body:[self region:MTLRegionMake2D(0,0,self.width,self.height) level:0] capacity:(uint32_t)total];
  if(data.length!=total)invalid(@"Display pixel readback length mismatch");return data;
 }
 // Keep the bounded chunk fallback for the largest admitted textures.
 NSMutableData *pixels=[NSMutableData dataWithLength:total];
 [self readbackBytes:pixels.mutableBytes bytesPerRow:row fromRegion:MTLRegionMake2D(0,0,self.width,self.height) mipmapLevel:0];
 return [pixels copy];
}
- (NSUInteger)width{return self.shape.width;}
- (NSUInteger)height{return self.shape.height;}
- (NSUInteger)depth{return 1;}
- (NSUInteger)arrayLength{return 1;}
- (NSUInteger)mipmapLevelCount{return 1;}
- (NSUInteger)sampleCount{return 1;}
- (MTLTextureType)textureType{return MTLTextureType2D;}
- (MTLPixelFormat)pixelFormat{return self.shape.pixelFormat;}
- (MTLTextureUsage)usage{return self.shape.usage;}
- (MTLStorageMode)storageMode{return self.shape.storageMode;}
- (MTLCPUCacheMode)cpuCacheMode{return MTLCPUCacheModeDefaultCache;}
- (BOOL)isFramebufferOnly{return self.framebufferOnlyValue;}
- (BOOL)allowGPUOptimizedContents{return NO;}
- (NSMutableData *)region:(MTLRegion)region level:(NSUInteger)level{
 if(level||region.origin.z||region.size.depth!=1||!region.size.width||!region.size.height||region.origin.x>self.width||region.size.width>self.width-region.origin.x||region.origin.y>self.height||region.size.height>self.height-region.origin.y)invalid(@"Texture region is outside this2D level");
 NSMutableData *body=[NSMutableData data];put64(body,self.handle);put32(body,(uint32_t)region.origin.x);put32(body,(uint32_t)region.origin.y);put32(body,(uint32_t)region.size.width);put32(body,(uint32_t)region.size.height);put32(body,(uint32_t)region.size.width*4);return body;
}
- (NSUInteger)checkBytes:(const void *)bytes stride:(NSUInteger)stride region:(MTLRegion)region level:(NSUInteger)level{
 (void)[self region:region level:level];NSUInteger row=region.size.width*4,h=region.size.height;
 if(!bytes||stride<row||(h>1&&stride>(NSUIntegerMax-row)/(h-1)))invalid(@"Texture byte stride overflows its range");
 NSUInteger span=(h-1)*stride+row;if((uintptr_t)bytes>UINTPTR_MAX-span)invalid(@"Texture pointer range overflows");return row;
}
- (void)getBytes:(void *)bytes bytesPerRow:(NSUInteger)stride fromRegion:(MTLRegion)region mipmapLevel:(NSUInteger)level{
 if(self.isFramebufferOnly||self.storageMode==MTLStorageModePrivate)invalid(@"CPU reads require a shared texture that is not framebuffer-only");[self readbackBytes:bytes bytesPerRow:stride fromRegion:region mipmapLevel:level];
}
- (void)readbackBytes:(void *)bytes bytesPerRow:(NSUInteger)stride fromRegion:(MTLRegion)region mipmapLevel:(NSUInteger)level{
 NSUInteger row=[self checkBytes:bytes stride:stride region:region level:level],chunkRows=MAX(1u,TRANSFER_CHUNK/row);
 for(NSUInteger at=0;at<region.size.height;){NSUInteger rows=MIN(chunkRows,region.size.height-at);MTLRegion part=region;part.origin.y+=at;part.size.height=rows;
 NSData *data=[self.backendDevice perform:IOSMETAL_TEXTURE_READ body:[self region:part level:level] capacity:(uint32_t)(row*rows)];if(data.length!=row*rows)invalid(@"Texture readback length mismatch");
 for(NSUInteger y=0;y<rows;y++)memcpy((uint8_t *)bytes+(at+y)*stride,(const uint8_t *)data.bytes+y*row,row);at+=rows;}
}
- (void)replaceRegion:(MTLRegion)region mipmapLevel:(NSUInteger)level withBytes:(const void *)bytes bytesPerRow:(NSUInteger)stride{
 if(self.isFramebufferOnly||self.storageMode==MTLStorageModePrivate)invalid(@"CPU writes require a shared texture that is not framebuffer-only");
 NSUInteger row=[self checkBytes:bytes stride:stride region:region level:level],chunkRows=MAX(1u,TRANSFER_CHUNK/row);
 for(NSUInteger at=0;at<region.size.height;){NSUInteger rows=MIN(chunkRows,region.size.height-at);MTLRegion part=region;part.origin.y+=at;part.size.height=rows;NSMutableData *body=[self region:part level:level];
 for(NSUInteger y=0;y<rows;y++)[body appendBytes:(const uint8_t *)bytes+(at+y)*stride length:row];[self.backendDevice perform:IOSMETAL_TEXTURE_UPLOAD body:body capacity:0];at+=rows;}
}

@end
id<MTLDevice> IOSMetalCreateDevice(void){return [IOSMDevice new];}

// Ordinary process-local dyld interposition for the explicit experimental launch.
// The guest's system frameworks and other process launch environments are unchanged.
__attribute__((used,section("__DATA,__interpose,interposing")))
static const struct {const void *replacement;const void *original;} iosmetal_public_factory[]={
 {(const void *)IOSMetalCreateDevice,(const void *)MTLCreateSystemDefaultDevice}
};

#include "metal-layer.inc"
__attribute__((constructor)) static void iosmetal_loaded(void){iosmetal_install_layer();write(1,"IOSMETAL_GUEST image_loaded\n",28);}
