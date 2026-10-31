// Authored public Metal client. SPDX-License-Identifier: AGPL-3.0-or-later
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#import <objc/runtime.h>
#include <dispatch/dispatch.h>
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <stdlib.h>
#include "authored-metallib.inc"
#include "metal-api-owned.h"
#include "sampling-fixture.h"
#include "vertex-layout-fixture.h"
#include "blending-fixture.h"
#include <pthread.h>
static unsigned checks,failures;
static void check(BOOL ok,const char *name){checks++;if(!ok){failures++;printf("METAL_API_FAIL %s\n",name);}}
@interface IOSMetalPublicationProbe:CAMetalLayer
@property(atomic) BOOL publishedOnMain;
@property(atomic) unsigned publicationCount;
@end
@implementation IOSMetalPublicationProbe
- (void)setContents:(id)value{if(value){self.publishedOnMain=[NSThread isMainThread];self.publicationCount++;printf("METAL_API_PUBLICATION_SET object=%p main=%u pthread_main=%u count=%u\n",self,[NSThread isMainThread],pthread_main_np()!=0,self.publicationCount);fflush(NULL);}[super setContents:value];}
@end
static BOOL compute(id<MTLDevice> device,id<MTLLibrary> library,BOOL negative){
 enum{COUNT=257,SIZE=(COUNT+128)*4};uint8_t source[SIZE],guard[SIZE];memset(source,0xa5,sizeof(source));memset(guard,0x7b,sizeof(guard));
 for(unsigned i=0;i<COUNT;i++){float v=(int)(i%13)-6;memcpy(source+256+i*4,&v,4);}
 id<MTLBuffer> a=[device newBufferWithBytes:source length:sizeof(source) options:MTLResourceStorageModeShared];
 id<MTLBuffer> b=[device newBufferWithBytes:guard length:sizeof(guard) options:MTLResourceStorageModeShared];
 float factor=2;id<MTLBuffer> scale=[device newBufferWithBytes:&factor length:4 options:MTLResourceStorageModeShared];
 id<MTLFunction> fn=[library newFunctionWithName:@"scale_and_offset"];
 check(fn.functionType==MTLFunctionTypeKernel,"function-type-is-kernel");NSError *error=nil;
 id<MTLComputePipelineState> state=[device newComputePipelineStateWithFunction:fn error:&error];
 check(state!=nil&&error==nil,"compute-pipeline");check(a&&b&&scale,"compute-buffers");if(!a||!b||!scale||!state)return NO;
 id<MTLCommandQueue> queue=[device newCommandQueue];id<MTLCommandBuffer> command=[queue commandBuffer];
 __block unsigned scheduled=0,completed=0;
 [command addScheduledHandler:^(id<MTLCommandBuffer> c){scheduled++;check(c.status>=MTLCommandBufferStatusScheduled,"scheduled-state");}];
 [command addCompletedHandler:^(id<MTLCommandBuffer> c){usleep(100000);completed++;check(c.status==MTLCommandBufferStatusCompleted&&c.error==nil,"completed-handler-state");}];
 id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];[encoder setComputePipelineState:state];
 [encoder setBuffer:a offset:256 atIndex:0];[encoder setBuffer:b offset:256 atIndex:1];[encoder setBuffer:scale offset:0 atIndex:2];
 [encoder dispatchThreads:MTLSizeMake(COUNT,1,1) threadsPerThreadgroup:MTLSizeMake(64,1,1)];[encoder endEncoding];
 // Shared contents modified AFTER encoding must be visible at commit.
 *(float *)scale.contents=5;
 dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{[command commit];});
 while(command.status<MTLCommandBufferStatusCommitted)usleep(1000);
 [command waitUntilCompleted];
 check(command.status==MTLCommandBufferStatusCompleted&&command.error==nil,"compute-completed");
 check(scheduled==1&&completed==1,"completion-handlers-once");
 uint8_t *result=b.contents;unsigned mismatches=0;
 for(unsigned i=0;i<COUNT;i++){float got;memcpy(&got,result+256+i*4,4);float expected=5*((int)(i%13)-6)+(float)i;if(negative&&i==0)expected+=1;if(got!=expected)mismatches++;}
 check(mismatches==0,"compute-every-output");check(!memcmp(result,guard,256)&&!memcmp(result+256+COUNT*4,guard+256+COUNT*4,256),"compute-guards");
 printf("METAL_API_COMPUTE elements=%u offset=256 factor_changed_after_encoding=5 mismatches=%u\n",COUNT,mismatches);return mismatches==0;
}
static BOOL render(id<MTLDevice> device,id<MTLLibrary> library){
 MTLRenderPipelineDescriptor *pipeline=[MTLRenderPipelineDescriptor new];pipeline.vertexFunction=[library newFunctionWithName:@"colored_vertex"];pipeline.fragmentFunction=[library newFunctionWithName:@"colored_fragment"];pipeline.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA8Unorm;
 NSError *error=nil;pipeline.colorAttachments[0].writeMask=(MTLColorWriteMask)16;
 printf("METAL_API_MASK_NORMALIZATION requested=16 observed=%lu\n",(unsigned long)pipeline.colorAttachments[0].writeMask);
 pipeline.colorAttachments[0].writeMask=MTLColorWriteMaskNone;
 check([device newRenderPipelineStateWithDescriptor:pipeline error:&error]!=nil&&error==nil,"zero-write-mask-pipeline");
 pipeline.colorAttachments[0].writeMask=MTLColorWriteMaskAll;error=nil;
 id<MTLRenderPipelineState> state=[device newRenderPipelineStateWithDescriptor:pipeline error:&error];check(state!=nil&&error==nil,"render-pipeline");if(!state){printf("METAL_API_RENDER_ERROR %s sample=%lu raster=%u vertexDescriptor=%u alphaCoverage=%u alphaOne=%u topology=%lu tessFormat=%lu partition=%lu maxTess=%lu mask=%lu\n",error.localizedDescription.UTF8String,(unsigned long)pipeline.sampleCount,pipeline.rasterizationEnabled,pipeline.vertexDescriptor!=nil,pipeline.alphaToCoverageEnabled,pipeline.alphaToOneEnabled,(unsigned long)pipeline.inputPrimitiveTopology,(unsigned long)pipeline.tessellationFactorFormat,(unsigned long)pipeline.tessellationPartitionMode,(unsigned long)pipeline.maxTessellationFactor,(unsigned long)pipeline.colorAttachments[0].writeMask);return NO;}
 MTLTextureDescriptor *descriptor=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:8 height:8 mipmapped:NO];descriptor.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;descriptor.storageMode=MTLStorageModeShared;
 id<MTLTexture> target=[device newTextureWithDescriptor:descriptor];check(target.width==8&&target.height==8&&target.pixelFormat==MTLPixelFormatRGBA8Unorm,"texture-shape");if(!target)return NO;
 float positions[]={-1,1,0,1,-1,0,0,1,0,0,-1,0},colors[24];for(unsigned i=0;i<6;i++){colors[i*4]=1;colors[i*4+1]=0.2f;colors[i*4+2]=0;colors[i*4+3]=1;}
 id<MTLBuffer> xy=[device newBufferWithBytes:positions length:sizeof(positions) options:0];id<MTLBuffer> rgba=[device newBufferWithBytes:colors length:sizeof(colors) options:0];
 id<MTLCommandQueue> queue=[device newCommandQueue];id<MTLCommandBuffer> command=[queue commandBuffer];
 MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=target;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,1,1);
 id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];[encoder setRenderPipelineState:state];[encoder setVertexBuffer:xy offset:0 atIndex:0];[encoder setVertexBuffer:rgba offset:0 atIndex:1];[encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];[encoder endEncoding];[command commit];[command waitUntilCompleted];
 check(command.status==MTLCommandBufferStatusCompleted&&command.error==nil,"render-completed");
 uint8_t pixels[8*48];memset(pixels,0x7b,sizeof(pixels));[target getBytes:pixels bytesPerRow:48 fromRegion:MTLRegionMake2D(0,0,8,8) mipmapLevel:0];
 unsigned mismatches=0,padding=0;for(unsigned y=0;y<8;y++){for(unsigned x=0;x<8;x++){uint8_t expected[4]={0,0,255,255};if(x<4&&y<4){expected[0]=255;expected[1]=51;expected[2]=0;}if(memcmp(pixels+y*48+x*4,expected,4))mismatches++;}for(unsigned x=32;x<48;x++)if(pixels[y*48+x]!=0x7b)padding++;}
 check(mismatches==0,"render-every-pixel");check(padding==0,"texture-row-padding-preserved");printf("METAL_API_RENDER pixels=64 stride=48 mismatches=%u padding_errors=%u\n",mismatches,padding);return !mismatches&&!padding;
}
static BOOL sampling(id<MTLDevice> device,id<MTLLibrary> library,BOOL negative){
 BOOL available=[device respondsToSelector:@selector(newSamplerStateWithDescriptor:)];
 check(available,"sampler-creation-selector");if(!available)return NO;
 MTLSamplerDescriptor *sd=[MTLSamplerDescriptor new];id<MTLSamplerState> samplers[4];
 for(unsigned i=0;i<4;i++){sd.minFilter=sd.magFilter=i/2?MTLSamplerMinMagFilterLinear:MTLSamplerMinMagFilterNearest;sd.sAddressMode=sd.tAddressMode=i%2?MTLSamplerAddressModeRepeat:MTLSamplerAddressModeClampToEdge;samplers[i]=[device newSamplerStateWithDescriptor:sd];check(samplers[i]!=nil,"sampler-object");if(!samplers[i])return NO;}
 sd.maxAnisotropy=2;check([device newSamplerStateWithDescriptor:sd]==nil,"unsupported-sampler-anisotropy-refused");
 MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:4 height:4 mipmapped:NO];shape.storageMode=MTLStorageModeShared;shape.usage=MTLTextureUsageShaderRead;
 id<MTLTexture> textures[2];for(unsigned i=0;i<2;i++){textures[i]=[device newTextureWithDescriptor:shape];uint8_t pixels[96];sampling_pixels(pixels,i);[textures[i] replaceRegion:MTLRegionMake2D(0,0,4,4) mipmapLevel:0 withBytes:pixels bytesPerRow:24];}
 shape.width=8;shape.height=8;shape.usage=MTLTextureUsageShaderRead|MTLTextureUsageRenderTarget;id<MTLTexture> target=[device newTextureWithDescriptor:shape];
 MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new];pd.vertexFunction=[library newFunctionWithName:@"colored_vertex"];pd.fragmentFunction=[library newFunctionWithName:@"sampled_fragment"];pd.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA8Unorm;
 NSError *error=nil;id<MTLRenderPipelineState> pipeline=[device newRenderPipelineStateWithDescriptor:pd error:&error];check(pipeline&&!error,"sampled-render-pipeline");if(!pipeline){printf("METAL_API_SAMPLING_ERROR %s\n",error.description.UTF8String);return NO;}
 const float xy[]={-1,1,1,1,-1,-1,1,1,1,-1,-1,-1};float color[24];for(unsigned i=0;i<24;i++)color[i]=1;
 id<MTLBuffer> positions=[device newBufferWithBytes:xy length:sizeof(xy) options:0],colors=[device newBufferWithBytes:color length:sizeof(color) options:0];
 id<MTLCommandQueue> queue=[device newCommandQueue];unsigned mismatches=0,padding=0;
 for(unsigned frame=0;frame<5;frame++){
  unsigned selected=frame<4?frame:0,variant=selected%2,linear=selected/2;id<MTLCommandBuffer> command=[queue commandBuffer];MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=target;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,1,1);
  id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];[encoder setRenderPipelineState:pipeline];[encoder setVertexBuffer:positions offset:0 atIndex:0];[encoder setVertexBuffer:colors offset:0 atIndex:1];
  [encoder setFragmentTexture:textures[1-variant] atIndex:3];[encoder setFragmentSamplerState:samplers[(selected+1)%4] atIndex:5];
  [encoder setFragmentTexture:nil atIndex:3];[encoder setFragmentSamplerState:nil atIndex:5];[encoder setFragmentTexture:textures[variant] atIndex:3];[encoder setFragmentSamplerState:samplers[selected] atIndex:5];
  BOOL refused=NO;@try{[encoder setFragmentSamplerState:samplers[0] atIndex:16];}@catch(NSException *e){refused=[e.name isEqual:NSInvalidArgumentException];}check(refused,"sampler-index-bound-refused");
  [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];[encoder endEncoding];
  if(frame==4){textures[variant]=nil;samplers[selected]=nil;}
  [command commit];[command waitUntilCompleted];check(command.status==MTLCommandBufferStatusCompleted&&!command.error,"sampled-render-completed");
  uint8_t result[8*48];memset(result,0x7b,sizeof(result));[target getBytes:result bytesPerRow:48 fromRegion:MTLRegionMake2D(0,0,8,8) mipmapLevel:0];unsigned bad=0;
  for(unsigned y=0;y<8;y++){for(unsigned x=0;x<8;x++){uint8_t expected[4];sampling_expected(expected,x,y,variant,(int)variant,(int)linear);if(negative&&frame==0&&x==0&&y==0)expected[0]^=1;if(sampling_differs(result+y*48+x*4,expected,(int)linear))bad++;}for(unsigned x=32;x<48;x++)if(result[y*48+x]!=0x7b)padding++;}
  check(!bad,"sampled-texture-and-sampler-every-pixel");mismatches+=bad;
 }
 check(!padding,"sampled-readback-padding-preserved");printf("METAL_API_SAMPLING pixels=320 texture_index=3 sampler_index=5 nearest_linear_clamp_repeat=true linear_rgb_tolerance=1 mismatches=%u padding_errors=%u\n",mismatches,padding);return !mismatches&&!padding;
}
static BOOL vertexLayouts(id<MTLDevice> device,id<MTLLibrary> library,BOOL negative){
 MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new];pd.vertexFunction=[library newFunctionWithName:@"layout_vertex"];pd.fragmentFunction=[library newFunctionWithName:@"colored_fragment"];pd.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA8Unorm;
 MTLVertexDescriptor *layout=[MTLVertexDescriptor vertexDescriptor];layout.attributes[3].format=MTLVertexFormatFloat2;layout.attributes[3].offset=4;layout.attributes[3].bufferIndex=6;layout.attributes[7].format=MTLVertexFormatFloat4;layout.attributes[7].offset=16;layout.attributes[7].bufferIndex=6;layout.layouts[6].stride=40;pd.vertexDescriptor=layout;
 NSError *error=nil;id<MTLRenderPipelineState> state=[device newRenderPipelineStateWithDescriptor:pd error:&error];check(state!=nil&&!error,"vertex-layout-pipeline");if(!state){printf("METAL_API_VERTEX_LAYOUT_ERROR %s\n",error.description.UTF8String);return NO;}
 MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:8 height:8 mipmapped:NO];shape.storageMode=MTLStorageModeShared;shape.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;id<MTLTexture> target=[device newTextureWithDescriptor:shape];
 id<MTLBuffer> vertices=[device newBufferWithLength:LAYOUT_BYTES options:0];id<MTLCommandQueue> queue=[device newCommandQueue];unsigned mismatches=0,padding=0;
 for(unsigned frame=0;frame<2;frame++){
  layout_pixels(vertices.contents,frame);id<MTLCommandBuffer> command=[queue commandBuffer];MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=target;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,1,1);
  id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];[encoder setRenderPipelineState:state];[encoder setVertexBuffer:vertices offset:128 atIndex:6];[encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];[encoder endEncoding];[command commit];[command waitUntilCompleted];check(command.status==MTLCommandBufferStatusCompleted&&!command.error,"vertex-layout-completed");
  uint8_t result[8*48];memset(result,0x7b,sizeof(result));[target getBytes:result bytesPerRow:48 fromRegion:MTLRegionMake2D(0,0,8,8) mipmapLevel:0];unsigned bad=0;
  for(unsigned y=0;y<8;y++){for(unsigned x=0;x<8;x++){uint8_t expected[4];layout_expected(expected,x,y,frame);if(negative&&frame==1&&x==0&&y==0)expected[1]^=1;if(memcmp(result+y*48+x*4,expected,4))bad++;}for(unsigned x=32;x<48;x++)if(result[y*48+x]!=0x7b)padding++;}
  check(!bad,"vertex-layout-every-pixel");mismatches+=bad;
 }
 check(!padding,"vertex-layout-padding");printf("METAL_API_VERTEX_LAYOUT pixels=128 attributes=3,7 buffer=6 binding_offset=128 stride=40 mismatches=%u padding_errors=%u\n",mismatches,padding);return !mismatches&&!padding;
}
#include "metal-api-blending.inc"
static BOOL transfers(id<MTLDevice> device,id<MTLLibrary> library){
 NSUInteger size=1024u*1024+256,offset=1024u*1024-256;NSMutableData *input=[NSMutableData dataWithLength:size];memset(input.mutableBytes,0x63,size);
 id<MTLBuffer> buffer=[device newBufferWithBytes:input.bytes length:size options:0];check(buffer!=nil,"chunk-buffer-allocation");if(!buffer)return NO;
 float source[128],factor=7;for(unsigned i=0;i<128;i++)source[i]=(int)(i%9)-4;
 id<MTLBuffer> a=[device newBufferWithBytes:source length:sizeof(source) options:0],scale=[device newBufferWithBytes:&factor length:sizeof(factor) options:0];
 NSError *error=nil;id<MTLComputePipelineState> state=[device newComputePipelineStateWithFunction:[library newFunctionWithName:@"scale_and_offset"] error:&error];check(a&&scale&&state&&!error,"chunk-compute-prerequisites");if(!a||!scale||!state)return NO;
 id<MTLCommandQueue> queue=[device newCommandQueue];id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
 [encoder setComputePipelineState:state];[encoder setBuffer:a offset:0 atIndex:0];[encoder setBuffer:buffer offset:offset atIndex:1];[encoder setBuffer:scale offset:0 atIndex:2];[encoder dispatchThreads:MTLSizeMake(128,1,1) threadsPerThreadgroup:MTLSizeMake(64,1,1)];[encoder endEncoding];[command commit];[command waitUntilCompleted];
 unsigned bufferBad=0;for(unsigned i=0;i<128;i++){float got;memcpy(&got,(uint8_t *)buffer.contents+offset+4*i,4);if(got!=7*source[i]+i)bufferBad++;}
 BOOL good=command.status==MTLCommandBufferStatusCompleted&&!command.error&&!bufferBad&&!memcmp(buffer.contents,input.bytes,offset);check(good,"chunk-buffer-gpu-write-crosses-boundary");
 MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:512 height:513 mipmapped:NO];shape.storageMode=MTLStorageModeShared;
 id<MTLTexture> texture=[device newTextureWithDescriptor:shape];check(texture!=nil,"chunk-texture-allocation");if(!texture)return NO;
 NSUInteger stride=2064,total=stride*513;NSMutableData *pixels=[NSMutableData dataWithLength:total],*result=[NSMutableData dataWithLength:total];for(NSUInteger y=0;y<513;y++)for(NSUInteger x=0;x<2048;x++)((uint8_t *)pixels.mutableBytes)[y*stride+x]=(uint8_t)((y*17+x*11)%251);memset(result.mutableBytes,0x7b,total);
 [texture replaceRegion:MTLRegionMake2D(0,0,512,513) mipmapLevel:0 withBytes:pixels.bytes bytesPerRow:stride];
 [texture getBytes:result.mutableBytes bytesPerRow:stride fromRegion:MTLRegionMake2D(0,0,512,513) mipmapLevel:0];
 unsigned bad=0;uint8_t *bytes=result.mutableBytes;for(NSUInteger y=0;y<513;y++){for(NSUInteger x=0;x<stride;x++)if(bytes[y*stride+x]!=(x<2048?(uint8_t)((y*17+x*11)%251):0x7b))bad++;}
 check(bad==0,"chunk-texture-entire-roundtrip-and-padding");good=good&&!bad;
 BOOL refused=NO;@try{[texture getBytes:result.mutableBytes bytesPerRow:NSUIntegerMax fromRegion:MTLRegionMake2D(0,0,2,2) mipmapLevel:0];}@catch(NSException *e){refused=[e.name isEqual:NSInvalidArgumentException];}check(refused,"overflowing-texture-stride-refused");
 printf("METAL_API_TRANSFERS buffer_bytes=%lu texture_bytes=%u mismatches=%u overflow_refused=%u\n",(unsigned long)size,512*513*4,bad+bufferBad,refused);return good&&refused;
}
static id<MTLCommandBuffer> clearCommand(id<MTLCommandQueue> queue,id<MTLTexture> texture,MTLClearColor color,unsigned setters){
 id<MTLCommandBuffer> command=[queue commandBuffer];MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=texture;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=color;
 id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];for(unsigned i=0;i<setters;i++)[encoder setBlendColorRed:(float)(i%7)/7 green:0 blue:0 alpha:1];[encoder endEncoding];return command;
}
static BOOL commandStreamTest(id<MTLDevice> device){
 MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:2 height:2 mipmapped:NO];shape.storageMode=MTLStorageModeShared;shape.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
 id<MTLTexture> target=[device newTextureWithDescriptor:shape],callbackTarget=[device newTextureWithDescriptor:shape];id<MTLCommandQueue> queue=[device newCommandQueue];check(target&&callbackTarget&&queue,"command-stream-prerequisites");if(!target||!callbackTarget||!queue)return NO;
 id<MTLCommandBuffer> first=clearCommand(queue,target,MTLClearColorMake(1,0,0,1),257),second=clearCommand(queue,target,MTLClearColorMake(0,1,0,1),0);__block unsigned callbacks=0;
 [first addCompletedHandler:^(id<MTLCommandBuffer> done){check(done.status==MTLCommandBufferStatusCompleted,"command-stream-callback-state");id<MTLCommandBuffer> nested=clearCommand(queue,callbackTarget,MTLClearColorMake(0,0,1,1),1);[nested commit];[nested waitUntilCompleted];if(nested.status==MTLCommandBufferStatusCompleted&&!nested.error)callbacks++;}];
 [second commit];[second waitUntilCompleted];[first commit];[first waitUntilCompleted];check(first.status==MTLCommandBufferStatusCompleted&&!first.error&&second.status==MTLCommandBufferStatusCompleted&&!second.error,"command-stream-reverse-commit");check(callbacks==1,"command-stream-callback-reentrancy");
 uint8_t actual[16],expected[16];unsigned bad=0;for(unsigned i=0;i<4;i++){expected[i*4]=255;expected[i*4+1]=0;expected[i*4+2]=0;expected[i*4+3]=255;}[target getBytes:actual bytesPerRow:8 fromRegion:MTLRegionMake2D(0,0,2,2) mipmapLevel:0];if(memcmp(actual,expected,16))bad++;
 for(unsigned i=0;i<4;i++){expected[i*4]=0;expected[i*4+2]=255;}[callbackTarget getBytes:actual bytesPerRow:8 fromRegion:MTLRegionMake2D(0,0,2,2) mipmapLevel:0];if(memcmp(actual,expected,16))bad++;check(!bad,"command-stream-reverse-and-nested-pixels");printf("METAL_API_COMMAND_STREAM setters=257 reverse_commit=true callback_reentrant=true mismatches=%u\n",bad);return !bad&&callbacks==1;
}
static BOOL layerTest(id<MTLDevice> device){
 CAMetalLayer *layer=[CAMetalLayer layer];layer.device=device;layer.pixelFormat=MTLPixelFormatBGRA8Unorm;layer.drawableSize=CGSizeMake(8,8);layer.framebufferOnly=NO;
 id<CAMetalDrawable> drawable=[layer nextDrawable];check(drawable!=nil,"layer-next-drawable");if(!drawable)return NO;
 check(drawable.layer==layer&&drawable.texture.width==8&&drawable.texture.height==8&&drawable.texture.device==device,"drawable-public-properties");
 BOOL timingRefused=NO;@try{[drawable addPresentedHandler:^(id<MTLDrawable> d){(void)d;}];}@catch(NSException *e){timingRefused=[e.name isEqual:NSInvalidArgumentException];}check(timingRefused,"display-timing-explicitly-unsupported");
 id<MTLCommandQueue> queue=[device newCommandQueue];id<MTLCommandBuffer> command=[queue commandBuffer];
 MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=drawable.texture;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=MTLClearColorMake(0.25,0.5,1,1);
 id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];[encoder endEncoding];[command presentDrawable:drawable];[command commit];[command waitUntilCompleted];
 check(command.status==MTLCommandBufferStatusCompleted&&!command.error&&drawable.presentedTime==0,"drawable-command-presented");
 CGImageRef image=(__bridge CGImageRef)layer.contents;BOOL imageValid=image&&CFGetTypeID(image)==CGImageGetTypeID();check(imageValid,"layer-image-publication");if(!imageValid)return NO;
 check(CGImageGetWidth(image)==8&&CGImageGetHeight(image)==8,"layer-image-dimensions");CFDataRef data=CGDataProviderCopyData(CGImageGetDataProvider(image));unsigned mismatches=0;
 if(!data)return NO;const UInt8 *bytes=CFDataGetBytePtr(data);size_t stride=CGImageGetBytesPerRow(image);const uint8_t expected[]={255,128,64,255};
 for(unsigned y=0;y<8;y++)for(unsigned x=0;x<8;x++)if(memcmp(bytes+y*stride+x*4,expected,4))mismatches++;CFRelease(data);check(!mismatches,"layer-every-presented-pixel");
 // Hold the first published image while a later, larger drawable replaces it.
 // This detects no-copy reply buffers freed/reused before their CGImage provider.
 CGImageRetain(image);
 @autoreleasepool{
  CAMetalLayer *large=[CAMetalLayer layer];large.device=device;large.drawableSize=CGSizeMake(576,512);
  id<CAMetalDrawable> big=[large nextDrawable];id<MTLCommandBuffer> draw=[queue commandBuffer];
  MTLRenderPassDescriptor *shape=[MTLRenderPassDescriptor renderPassDescriptor];shape.colorAttachments[0].texture=big.texture;shape.colorAttachments[0].loadAction=MTLLoadActionClear;shape.colorAttachments[0].storeAction=MTLStoreActionStore;shape.colorAttachments[0].clearColor=MTLClearColorMake(1,0.2,0,1);
  id<MTLRenderCommandEncoder> paint=[draw renderCommandEncoderWithDescriptor:shape];[paint endEncoding];[draw presentDrawable:big];[draw commit];[draw waitUntilCompleted];
  CGImageRef actual=(__bridge CGImageRef)large.contents;
  BOOL dimensions=actual&&CGImageGetWidth(actual)==576&&CGImageGetHeight(actual)==512;check(dimensions,"large-drawable-native-transfer-dimensions");
  if(dimensions){CFDataRef result=CGDataProviderCopyData(CGImageGetDataProvider(actual));const uint8_t *values=CFDataGetBytePtr(result);size_t pitch=CGImageGetBytesPerRow(actual);unsigned bad=0;const uint8_t color[]={0,51,255,255};for(unsigned y=0;y<512;y++)for(unsigned x=0;x<576;x++)if(memcmp(values+y*pitch+x*4,color,4))bad++;check(!bad,"large-drawable-every-pixel");CFRelease(result);}
 }
 data=CGDataProviderCopyData(CGImageGetDataProvider(image));bytes=CFDataGetBytePtr(data);
 unsigned retainedBad=0;for(unsigned y=0;y<8;y++)for(unsigned x=0;x<8;x++)if(memcmp(bytes+y*stride+x*4,expected,4))retainedBad++;
 check(!retainedBad,"published-image-remains-immutable-after-next-frame");CFRelease(data);CGImageRelease(image);
 IOSMetalPublicationProbe *threaded=[IOSMetalPublicationProbe layer];threaded.device=device;threaded.drawableSize=CGSizeMake(8,8);
 id<CAMetalDrawable> threadFrame=[threaded nextDrawable];id<MTLCommandBuffer> threadCommand=[queue commandBuffer];
 MTLRenderPassDescriptor *threadPass=[MTLRenderPassDescriptor renderPassDescriptor];threadPass.colorAttachments[0].texture=threadFrame.texture;threadPass.colorAttachments[0].loadAction=MTLLoadActionClear;threadPass.colorAttachments[0].storeAction=MTLStoreActionStore;threadPass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,1,1);
 id<MTLRenderCommandEncoder> threadEncoder=[threadCommand renderCommandEncoderWithDescriptor:threadPass];[threadEncoder endEncoding];[threadCommand presentDrawable:threadFrame];
 dispatch_group_t group=dispatch_group_create();dispatch_group_enter(group);
 unsigned publicationBaseline=threaded.publicationCount;
 printf("METAL_API_PUBLICATION_BEFORE object=%p contents=%u count=%u\n",threaded,threaded.contents!=nil,publicationBaseline);fflush(NULL);
 dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{[threadCommand commit];dispatch_group_leave(group);});
 NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:5];
 // Full-system CAMetalLayer can already expose native contents before our
 // queued main-thread publication. Wait for the observed setter, not non-nil.
 while((dispatch_group_wait(group,DISPATCH_TIME_NOW)!=0||threaded.publicationCount==publicationBaseline)&&deadline.timeIntervalSinceNow>0)
  [[NSRunLoop currentRunLoop]runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
 printf("METAL_API_PUBLICATION status=%lu group_completed=%u contents=%u published_on_main=%u error=%s object=%p count=%u current_main=%u pthread_main=%u\n",(unsigned long)threadCommand.status,dispatch_group_wait(group,DISPATCH_TIME_NOW)==0,threaded.contents!=nil,threaded.publishedOnMain,threadCommand.error.description.UTF8String?:"none",threaded,threaded.publicationCount,[NSThread isMainThread],pthread_main_np()!=0);
 check(threadCommand.status==MTLCommandBufferStatusCompleted&&threaded.contents&&threaded.publicationCount==publicationBaseline+1&&threaded.publishedOnMain,"worker-render-publishes-layer-on-main-thread");
 CGImageRef published=(__bridge CGImageRef)threaded.contents;BOOL publicationPixels=published&&threaded.publicationCount>publicationBaseline&&CFGetTypeID(published)==CGImageGetTypeID()&&CGImageGetWidth(published)==8&&CGImageGetHeight(published)==8;
 if(publicationPixels){CFDataRef result=CGDataProviderCopyData(CGImageGetDataProvider(published));publicationPixels=result!=NULL;if(result){const uint8_t *values=CFDataGetBytePtr(result);size_t pitch=CGImageGetBytesPerRow(published);publicationPixels=pitch==32&&CFDataGetLength(result)>=256;const uint8_t blue[]={255,0,0,255};if(publicationPixels)for(unsigned y=0;y<8;y++)for(unsigned x=0;x<8;x++)if(memcmp(values+y*pitch+x*4,blue,4))publicationPixels=NO;CFRelease(result);}}
 check(publicationPixels,"worker-published-image-every-blue-pixel");
 // Public contract regressions: pool, reservation, color policy and device transitions.
 drawable=nil;command=nil;
 @autoreleasepool{
  NSMutableArray *keepers __attribute__((objc_precise_lifetime))=[NSMutableArray array];
  for(unsigned i=0;i<3;i++){id<CAMetalDrawable> value=[layer nextDrawable];if(value)[keepers addObject:value];}
  check(keepers.count==3,"drawable-pool-three-leases");CFTimeInterval start=CACurrentMediaTime();check([layer nextDrawable]==nil,"drawable-pool-exhaustion");check(CACurrentMediaTime()-start<3,"drawable-pool-timeout-bounded");
 }
 @autoreleasepool{
  id<CAMetalDrawable> reserved=[layer nextDrawable];id<MTLCommandBuffer> first __attribute__((objc_precise_lifetime))=[queue commandBuffer],second=[queue commandBuffer];[first presentDrawable:reserved];BOOL refused=NO;
  @try{[second presentDrawable:reserved];}@catch(NSException *e){refused=[e.name isEqual:NSInvalidArgumentException];}check(refused,"drawable-reserved-once-across-commands");
 }
 CGColorSpaceRef custom=CGColorSpaceCreateWithName(kCGColorSpaceSRGB);BOOL colorRefused=NO;@try{layer.colorspace=custom;}@catch(NSException *e){colorRefused=[e.name isEqual:NSInvalidArgumentException];}check(colorRefused,"unsupported-display-color-space-refused");layer.colorspace=NULL;CGColorSpaceRelease(custom);
 layer.maximumDrawableCount=2;layer.device=nil;check(CGSizeEqualToSize(layer.drawableSize,CGSizeMake(8,8))&&!layer.framebufferOnly&&layer.maximumDrawableCount==2,"layer-properties-survive-device-clear");layer.device=device;check(CGSizeEqualToSize(layer.drawableSize,CGSizeMake(8,8))&&!layer.framebufferOnly&&layer.maximumDrawableCount==2,"layer-properties-survive-device-restore");
 printf("METAL_API_LAYER pixels=64 mismatches=%u display_timing_supported=false\n",mismatches);return !mismatches;
}
#include "metal-transfer-profile.inc"
#include "metal-snapshot-retirement.inc"
int main(int argc,char **argv){
 for(int i=1;i<argc;i++)if(!strcmp(argv[i],"--snapshot-retirement")){int result=retirementTest();printf("METAL_API_RESULT pass=%s snapshot_retirement=true\n",result?"false":"true");fflush(NULL);return result;}
 BOOL negative=NO,publicFactory=NO,layerCheck=NO,profileReadback=NO;for(int i=1;i<argc;i++){if(!strcmp(argv[i],"--negative"))negative=YES;if(!strcmp(argv[i],"--public-factory"))publicFactory=YES;if(!strcmp(argv[i],"--layer"))layerCheck=YES;if(!strcmp(argv[i],"--profile-readback"))profileReadback=YES;if(!strcmp(argv[i],"--profile-command-batch"))setenv("IOSMETAL_PROFILE_TRANSFERS","1",1);if(!strcmp(argv[i],"--no-batch"))setenv("IOSMETAL_COMMAND_BATCH","0",1);}if(profileReadback)setenv("IOSMETAL_PROFILE_TRANSFERS","1",1);write(1,"METAL_API_STAGE main\n",21);alarm(120);@autoreleasepool{
  write(1,"METAL_API_STAGE pool\n",21);
  printf("METAL_API_ENV insert=%s\n",getenv("DYLD_INSERT_LIBRARIES")?:"absent");fflush(NULL);
  printf("METAL_VISIBLE_PREREQ uicache=%u uiopen=%u launchctl=%u\n",access("/usr/bin/uicache",X_OK)==0,access("/usr/bin/uiopen",X_OK)==0,access("/bin/launchctl",X_OK)==0||access("/usr/bin/launchctl",X_OK)==0);fflush(NULL);
  void *driver=dlopen("/usr/lib/iosmetal-driver.dylib",RTLD_NOW|RTLD_LOCAL);
  if(!driver){printf("METAL_API_RESULT pass=false baseline=driver-missing error=%.180s\n",dlerror());fflush(NULL);return 42;}
  IOSMetalCreateDeviceFn create=(IOSMetalCreateDeviceFn)dlsym(driver,"IOSMetalCreateDevice");id<MTLDevice> device=publicFactory?MTLCreateSystemDefaultDevice():(create?create():nil);
  check(device!=nil,"real-device");if(!device){puts("METAL_API_RESULT pass=false reason=device-unavailable");fflush(NULL);return 2;}
  printf("METAL_API_DEVICE name=%s class=%s\n",device.name.UTF8String,object_getClassName(device));
  if(profileReadback)return transferProfile(device,negative);
  size_t half=sizeof(authored_metallib)/2;
  dispatch_data_t first=dispatch_data_create(authored_metallib,half,NULL,DISPATCH_DATA_DESTRUCTOR_DEFAULT);
  dispatch_data_t last=dispatch_data_create(authored_metallib+half,sizeof(authored_metallib)-half,NULL,DISPATCH_DATA_DESTRUCTOR_DEFAULT);
  dispatch_data_t data=dispatch_data_create_concat(first,last);NSError *error=nil;
  id<MTLLibrary> library=[device newLibraryWithData:data error:&error];check(library!=nil&&error==nil,"public-metallib-load");if(!library){printf("METAL_API_LIBRARY_ERROR %s\n",error.description.UTF8String);return 3;}
  check(library.functionNames.count==5,"library-function-names");check(compute(device,library,negative),"compute-subtest");check(render(device,library),"render-subtest");check(sampling(device,library,negative),"sampling-subtest");check(vertexLayouts(device,library,negative),"vertex-layout-subtest");check(blending(device,library,negative),"blending-subtest");check(transfers(device,library),"transfer-subtest");
  check(commandStreamTest(device),"command-stream-subtest");
  if(layerCheck){@try{check(layerTest(device),"layer-subtest");}@catch(NSException *e){check(NO,"layer-exception");printf("METAL_API_LAYER_ERROR %s %s\n",e.name.UTF8String,e.reason.UTF8String);}}
  dispatch_data_t bad=dispatch_data_create("bad",3,NULL,DISPATCH_DATA_DESTRUCTOR_DEFAULT);error=nil;check([device newLibraryWithData:bad error:&error]==nil&&error!=nil,"bad-library-error");
  printf("METAL_API_RESULT pass=%s checks=%u failures=%u public_metal_messages=true factory=%s\n",failures?"false":"true",checks,failures,publicFactory?"MTLCreateSystemDefaultDevice":"owned-explicit");fflush(NULL);return failures?1:0;
 }
}
