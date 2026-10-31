// Authored interactive Metal workload. SPDX-License-Identifier: AGPL-3.0-or-later
#import <UIKit/UIKit.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#include <stdio.h>
#include <stdarg.h>
#include <math.h>
#include <errno.h>
#include <stdlib.h>
#include <unistd.h>
#include <dispatch/dispatch.h>
#include "frame-timing.h"
static FILE *eventLog;
static int logWriteError;
static NSString *sessionID;
static NSString *initializationReason;
static void event(const char *format,...){
 va_list args;va_start(args,format);va_list secondary;va_copy(secondary,args);
 if(eventLog&&(vfprintf(eventLog,format,args)<0||fputc('\n',eventLog)==EOF||fflush(eventLog)))logWriteError=errno?:EIO;
 vfprintf(stderr,format,secondary);fputc('\n',stderr);fflush(stderr);va_end(secondary);va_end(args);
}
#include "metal-visible-scene.inc"
@interface MetalView:UIView
@property(nonatomic,strong) id<MTLDevice> device;
@property(nonatomic,strong) id<MTLCommandQueue> queue;
@property(nonatomic,strong) id<MTLRenderPipelineState> pipeline;
@property(nonatomic,strong) id<MTLBuffer> positions;
@property(nonatomic,strong) id<MTLBuffer> colors;
@property(nonatomic,strong) id<MTLRenderPipelineState> texturedPipeline;
@property(nonatomic,strong) id<MTLBuffer> textureVertices;
@property(nonatomic,strong) id<MTLTexture> texture0;
@property(nonatomic,strong) id<MTLTexture> texture1;
@property(nonatomic,strong) id<MTLSamplerState> nearestSampler;
@property(nonatomic,strong) id<MTLSamplerState> linearSampler;
@property(nonatomic,strong) CADisplayLink *clock;
@property(nonatomic,weak) UILabel *status;
@property(nonatomic) NSUInteger frameNumber;
@property(nonatomic) NSUInteger taps;
@property(nonatomic) BOOL active;
@property(nonatomic,strong) dispatch_queue_t renderQueue;
@property(nonatomic) BOOL frameInFlight;
@property(nonatomic) NSUInteger lifecycleGeneration;
@property(nonatomic) CFTimeInterval statsStart;
@property(nonatomic) NSUInteger statsFrames;
@property(nonatomic) BOOL lifecycleRegressionPassed;
@property(nonatomic) CFTimeInterval submissionSeconds;
@property(nonatomic) NSUInteger clockCallbacks;
@property(nonatomic) NSUInteger busySkips;
@property(nonatomic) CFTimeInterval lastClockAt;
@property(nonatomic) CFTimeInterval clockGap;
@property(nonatomic) CFTimeInterval lastFinishedAt;
@property(nonatomic) CFTimeInterval idleSeconds;
@property(nonatomic) CFTimeInterval mainFinishSeconds;
- (void)startDrawing;
- (void)stopDrawing;
- (void)finishFrame:(NSString *)failure generation:(NSUInteger)generation elapsed:(CFTimeInterval)elapsed timing:(IOSMetalFrameTiming)timing taps:(NSUInteger)taps width:(NSUInteger)width height:(NSUInteger)height;
@end
@implementation MetalView
+ (Class)layerClass{return [CAMetalLayer class];}
- (instancetype)initWithFrame:(CGRect)frame{
 if(!(self=[super initWithFrame:frame]))return nil;
 @try{
 self.device=MTLCreateSystemDefaultDevice();self.queue=[self.device newCommandQueue];
 CAMetalLayer *layer=(CAMetalLayer *)self.layer;layer.device=self.device;layer.pixelFormat=MTLPixelFormatBGRA8Unorm;layer.framebufferOnly=YES;layer.maximumDrawableCount=2;
 NSError *error=nil;id<MTLLibrary> library=[self.device newDefaultLibrary];
 if(!self.device||!self.queue||!library){initializationReason=!self.device?@"MTLCreateSystemDefaultDevice returned nil":(!self.queue?@"Command queue unavailable":@"default.metallib unavailable");event("METAL_VISIBLE_APP unavailable reason=device-queue-library");return nil;}
 self.pipeline=scenePipeline(self.device,library,NO,&error);self.texturedPipeline=scenePipeline(self.device,library,YES,&error);
 self.textureVertices=[self.device newBufferWithLength:6*24 options:0];self.texture0=sceneTexture(self.device,0);self.texture1=sceneTexture(self.device,1);self.nearestSampler=sceneSampler(self.device,NO,NO);self.linearSampler=sceneSampler(self.device,YES,YES);
 float xy[]={-0.8f,0.8f,0.8f,0.8f,-0.8f,-0.8f,0.8f,0.8f,0.8f,-0.8f,-0.8f,-0.8f};
 self.positions=[self.device newBufferWithBytes:xy length:sizeof(xy) options:0];self.colors=[self.device newBufferWithLength:6*4*sizeof(float) options:0];
 if(!self.device||!self.queue||!self.pipeline||!self.texturedPipeline||!self.textureVertices||!self.texture0||!self.texture1||!self.nearestSampler||!self.linearSampler||!self.positions||!self.colors){initializationReason=error.localizedDescription?:@"A pipeline or resource allocation was refused";event("METAL_VISIBLE_APP unavailable error=%s",error.localizedDescription.UTF8String);return nil;}
 }@catch(NSException *e){initializationReason=e.reason;event("METAL_VISIBLE_APP initialization_failed name=%s reason=%s",e.name.UTF8String,e.reason.UTF8String);return nil;}
 [self addGestureRecognizer:[[UITapGestureRecognizer alloc]initWithTarget:self action:@selector(tapped:)]];

 self.renderQueue=dispatch_queue_create("io.github.iosvm.metal-visible.render",DISPATCH_QUEUE_SERIAL);
 event("METAL_VISIBLE_DISPLAY bounds=%.0fx%.0f scale=%.1f native=%.0fx%.0f",UIScreen.mainScreen.bounds.size.width,UIScreen.mainScreen.bounds.size.height,UIScreen.mainScreen.scale,UIScreen.mainScreen.nativeBounds.size.width,UIScreen.mainScreen.nativeBounds.size.height);
 event("METAL_VISIBLE_APP gpu=%s renderer=Metal-Vulkan-Adreno",self.device.name.UTF8String);return self;
}
- (void)startDrawing{self.active=YES;if(self.window&&self.pipeline&&!self.clock){self.statsStart=CACurrentMediaTime();self.statsFrames=0;self.clockCallbacks=0;self.busySkips=0;self.lastClockAt=0;self.clockGap=0;self.lastFinishedAt=0;self.clock=[CADisplayLink displayLinkWithTarget:self selector:@selector(drawFrame:)];self.clock.preferredFramesPerSecond=30;[self.clock addToRunLoop:[NSRunLoop mainRunLoop] forMode:NSRunLoopCommonModes];}}
- (void)stopDrawing{self.active=NO;self.lifecycleGeneration++;[self.clock invalidate];self.clock=nil;}
- (void)didMoveToWindow{[super didMoveToWindow];if(self.window&&self.active)[self startDrawing];else if(!self.window){[self.clock invalidate];self.clock=nil;}}
- (void)layoutSubviews{[super layoutSubviews];CGSize size=self.bounds.size;CGFloat scale=[UIScreen mainScreen].scale;((CAMetalLayer *)self.layer).drawableSize=CGSizeMake(round(size.width*scale),round(size.height*scale));}
- (void)tapped:(UITapGestureRecognizer *)gesture{(void)gesture;self.taps++;event("METAL_VISIBLE_TOUCH count=%lu",(unsigned long)self.taps);[self drawFrame:nil];}
- (void)drawFrame:(CADisplayLink *)clock{
 CFTimeInterval started=CACurrentMediaTime();
 if(clock){self.clockCallbacks++;if(self.lastClockAt)self.clockGap=started-self.lastClockAt;self.lastClockAt=started;}
 if(!self.active||!self.window||!self.pipeline)return;
 if(self.frameInFlight){if(clock)self.busySkips++;return;}
 self.idleSeconds=self.lastFinishedAt?started-self.lastFinishedAt:0;
 self.frameInFlight=YES;NSUInteger generation=self.lifecycleGeneration,taps=self.taps,frame=self.frameNumber;CAMetalLayer *layer=(CAMetalLayer *)self.layer;
 dispatch_async(self.renderQueue,^{@autoreleasepool{
  CFTimeInterval workerBegan=CACurrentMediaTime(),submissionStart=workerBegan;
  NSString *failure=nil;NSUInteger width=0,height=0;CFTimeInterval submissionSeconds=0;
  @try{
  id<CAMetalDrawable> drawable=[layer nextDrawable];
  if(!drawable)@throw [NSException exceptionWithName:@"IOSMetalDrawableUnavailable" reason:@"No drawable became available" userInfo:nil];
  width=drawable.texture.width;height=drawable.texture.height;
  static const float palette[][3]={{1,0.2f,0},{0.1f,0.8f,0.3f},{0.25f,0.4f,1}};const float *color=palette[taps%3];float *rgba=self.colors.contents;
  for(unsigned i=0;i<6;i++){rgba[i*4]=color[0];rgba[i*4+1]=color[1];rgba[i*4+2]=color[2];rgba[i*4+3]=1;}
  MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=drawable.texture;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=MTLClearColorMake(0.025,0.04,0.08,1);
  id<MTLCommandBuffer> command=[self.queue commandBuffer];id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];
  float shift=.1f*sinf((float)frame*.07f);sceneVertices(self.textureVertices.contents,-.6f+shift,-.55f,.6f+shift,.55f,0,0,1,1,taps%3==0?.5f:.75f);
  sceneEncode(encoder,self.pipeline,self.texturedPipeline,self.positions,self.colors,self.textureVertices,taps%2?self.texture1:self.texture0,taps%3==1?self.linearSampler:self.nearestSampler);[encoder endEncoding];[command presentDrawable:drawable];
  submissionStart=CACurrentMediaTime();[command commit];[command waitUntilCompleted];submissionSeconds=CACurrentMediaTime()-submissionStart;
  if(command.status!=MTLCommandBufferStatusCompleted)failure=command.error.localizedDescription?:@"GPU submission failed";
  }@catch(NSException *e){failure=e.reason?:e.name;}
  CFTimeInterval ready=CACurrentMediaTime(),elapsed=ready-started;
  dispatch_async(dispatch_get_main_queue(),^{
   if(self.active&&generation==self.lifecycleGeneration)self.submissionSeconds=submissionSeconds;
   IOSMetalFrameTiming timing=iosmetal_frame_timing(started,workerBegan,submissionStart,ready,CACurrentMediaTime());
   [self finishFrame:failure generation:generation elapsed:elapsed timing:timing taps:taps width:width height:height];
  });
 }});
}
- (void)finishFrame:(NSString *)failure generation:(NSUInteger)generation elapsed:(CFTimeInterval)elapsed timing:(IOSMetalFrameTiming)timing taps:(NSUInteger)taps width:(NSUInteger)width height:(NSUInteger)height{
 CFTimeInterval entered=CACurrentMediaTime();
 self.frameInFlight=NO;
 if(!self.active||generation!=self.lifecycleGeneration)return;
 if(failure){self.status.text=failure;event("METAL_VISIBLE_FRAME error=%s",failure.UTF8String);[self stopDrawing];return;}
 self.frameNumber++;self.statsFrames++;CFTimeInterval duration=entered-self.statsStart;
 self.status.text=[NSString stringWithFormat:@"Adreno | frame %lu | taps %lu | %.1f FPS\nTotal %.0f | submit %.0f | main %.0f ms\nQ %.0f E %.0f UIprev %.0f | tick %.0f idle %.0f | skip %lu/%lu",(unsigned long)self.frameNumber,(unsigned long)self.taps,self.statsFrames/fmax(duration,0.001),timing.total_ms,self.submissionSeconds*1000,timing.main_ms,timing.queue_ms,timing.encode_ms,self.mainFinishSeconds*1000,self.clockGap*1000,self.idleSeconds*1000,(unsigned long)self.busySkips,(unsigned long)self.clockCallbacks];
 if(self.frameNumber<=3||self.frameNumber%30==0)event("METAL_VISIBLE_TIMING frame=%lu timing_valid=%u queue_ms=%.3f encode_ms=%.3f submit_ms=%.3f main_ms=%.3f total_ms=%.3f clock_gap_ms=%.3f idle_ms=%.3f busy_skips=%lu clock_callbacks=%lu",(unsigned long)self.frameNumber,timing.valid,timing.queue_ms,timing.encode_ms,timing.submit_ms,timing.main_ms,timing.total_ms,self.clockGap*1000,self.idleSeconds*1000,(unsigned long)self.busySkips,(unsigned long)self.clockCallbacks);
 if(self.frameNumber<=3||self.frameNumber%30==0)event("METAL_VISIBLE_FRAME number=%lu taps=%lu width=%lu height=%lu frame_ms=%.3f ui_thread_blocked=false scene=textured_alpha",(unsigned long)self.frameNumber,(unsigned long)taps,(unsigned long)width,(unsigned long)height,elapsed*1000);
 self.lastFinishedAt=CACurrentMediaTime();self.mainFinishSeconds=self.lastFinishedAt-entered;
}
- (void)dealloc{[self.clock invalidate];}
@end
@interface AppDelegate:UIResponder<UIApplicationDelegate>
@property(nonatomic,strong) UIWindow *window;
@property(nonatomic,strong) MetalView *metalView;
@end
@implementation AppDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options{
 (void)application;(void)options;
 sessionID=[[NSUUID UUID]UUIDString];NSString *home=NSHomeDirectory(),*folder=[home stringByAppendingPathComponent:@"Library/Logs"],*logPath=[folder stringByAppendingPathComponent:@"IOSMetalVisible.log"];NSError *folderError=nil;
 BOOL madeFolder=[[NSFileManager defaultManager]createDirectoryAtPath:folder withIntermediateDirectories:YES attributes:nil error:&folderError];errno=0;eventLog=fopen(logPath.fileSystemRepresentation,"a");int openError=eventLog?0:errno;
 event("METAL_VISIBLE_SESSION id=%s pid=%u uid=%u euid=%u gid=%u home=%.300s HOME=%.300s CFFIXED_USER_HOME=%.300s TMPDIR=%.300s mkdir=%u mkdir_error=%.240s fopen_errno=%d",sessionID.UTF8String,getpid(),getuid(),geteuid(),getgid(),home.UTF8String,getenv("HOME")?:"absent",getenv("CFFIXED_USER_HOME")?:"absent",getenv("TMPDIR")?:"absent",madeFolder,folderError.description.UTF8String?:"none",openError);
 NSString *diagnostic=(eventLog&&!logWriteError)?[NSString stringWithFormat:@"Session %@ | log ready | uid %u\n%@",[sessionID substringToIndex:8],getuid(),home]:[NSString stringWithFormat:@"Log mkdir=%u error=%ld open=%d write=%d uid=%u\n%@",madeFolder,(long)folderError.code,openError,logWriteError,getuid(),home];
 event("METAL_VISIBLE_LIFECYCLE launched session=%s",sessionID.UTF8String);self.window=[[UIWindow alloc]initWithFrame:[UIScreen mainScreen].bounds];UIViewController *controller=[UIViewController new];controller.view.backgroundColor=[UIColor colorWithWhite:0.04 alpha:1];
 CGRect bounds=self.window.bounds;UILabel *title=[[UILabel alloc]initWithFrame:CGRectMake(24,58,bounds.size.width-48,42)];title.text=@"Metal on Adreno";title.font=[UIFont boldSystemFontOfSize:26];title.textColor=[UIColor whiteColor];
 UILabel *status=[[UILabel alloc]initWithFrame:CGRectMake(24,102,bounds.size.width-48,48)];status.text=@"Preparing the GPU";status.numberOfLines=3;status.font=[UIFont monospacedDigitSystemFontOfSize:11 weight:UIFontWeightRegular];status.textColor=[UIColor lightGrayColor];
 MetalView *metal=[[MetalView alloc]initWithFrame:CGRectMake(24,158,bounds.size.width-48,bounds.size.height-335)];self.metalView=metal;metal.status=status;if(!metal){status.text=initializationReason?:@"Metal initialization reported an error";status.numberOfLines=0;status.frame=CGRectMake(24,106,bounds.size.width-48,180);}metal.autoresizingMask=UIViewAutoresizingFlexibleWidth|UIViewAutoresizingFlexibleHeight;
 UILabel *details=[[UILabel alloc]initWithFrame:CGRectMake(24,bounds.size.height-173,bounds.size.width-48,78)];details.text=diagnostic;details.numberOfLines=0;details.font=[UIFont monospacedSystemFontOfSize:10 weight:UIFontWeightRegular];details.textColor=[UIColor lightGrayColor];
 UILabel *hint=[[UILabel alloc]initWithFrame:CGRectMake(24,bounds.size.height-90,bounds.size.width-48,40)];hint.text=@"Tap the texture to change its image and softness";hint.numberOfLines=2;hint.font=[UIFont systemFontOfSize:15];hint.textColor=[UIColor whiteColor];
 if(metal)[controller.view addSubview:metal];[controller.view addSubview:title];[controller.view addSubview:status];[controller.view addSubview:details];[controller.view addSubview:hint];self.window.rootViewController=controller;[self.window makeKeyAndVisible];
 if(metal){
  // Exercise a delayed failed completion from before a resign/reactivate cycle.
  // This runs synchronously before the run loop can submit the first real frame.
  [metal startDrawing];NSUInteger oldGeneration=metal.lifecycleGeneration;[metal stopDrawing];[metal startDrawing];
  CADisplayLink *resumedClock=metal.clock;metal.frameInFlight=YES;
  [metal finishFrame:@"Injected stale lifecycle failure" generation:oldGeneration elapsed:0 timing:(IOSMetalFrameTiming){0} taps:0 width:0 height:0];
  metal.lifecycleRegressionPassed=metal.active&&resumedClock&&metal.clock==resumedClock;
  event("METAL_VISIBLE_LIFECYCLE_CONTROL stale_failed_completion_ignored=%u",metal.lifecycleRegressionPassed);
  details.text=[diagnostic stringByAppendingFormat:@"\nLifecycle regression: %@",metal.lifecycleRegressionPassed?@"PASS":@"FAIL"];
  [metal stopDrawing];status.text=@"Preparing the GPU";
 }
 return YES;
}
- (void)applicationDidBecomeActive:(UIApplication *)application{application.idleTimerDisabled=YES;[self.metalView startDrawing];event("METAL_VISIBLE_LIFECYCLE active");}
- (void)applicationWillResignActive:(UIApplication *)application{application.idleTimerDisabled=NO;[self.metalView stopDrawing];event("METAL_VISIBLE_LIFECYCLE inactive");}
@end
int main(int argc,char **argv){@autoreleasepool{
 if(argc>=2&&!strcmp(argv[1],"--self-test")){
  if(argc<3||argc>4||(argc==4&&strcmp(argv[3],"--negative")))return 2;
  return sceneSelfTest([NSString stringWithUTF8String:argv[2]],argc==4);
 }
 return UIApplicationMain(argc,argv,nil,NSStringFromClass([AppDelegate class]));
}}
