/* Authored public CAMetalLayer large-reply profile and immutability control. */
static int transferProfile(id<MTLDevice> device,BOOL negative){
 enum{Width=1440,Height=3120,Frames=12};unsigned pixels=0;CGImageRef retained=NULL;
 @try{
  CAMetalLayer *layer=[CAMetalLayer layer];layer.device=device;layer.drawableSize=CGSizeMake(Width,Height);layer.maximumDrawableCount=2;
  id<MTLCommandQueue> queue=[device newCommandQueue];
  for(unsigned frame=0;frame<Frames;frame++){@autoreleasepool{
   id<CAMetalDrawable> drawable=[layer nextDrawable];id<MTLCommandBuffer> command=[queue commandBuffer];
   MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=drawable.texture;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;
   unsigned red=frame&1,green=(frame>>1)&1,blue=(frame>>2)&1;pass.colorAttachments[0].clearColor=MTLClearColorMake(red,green,blue,1);
   id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];[encoder endEncoding];[command presentDrawable:drawable];CFTimeInterval start=CACurrentMediaTime();[command commit];[command waitUntilCompleted];CFTimeInterval committed=CACurrentMediaTime();
   check(command.status==MTLCommandBufferStatusCompleted&&!command.error,"profile-native-frame-completed");
   CGImageRef image=(__bridge CGImageRef)layer.contents;BOOL shape=image&&CGImageGetWidth(image)==Width&&CGImageGetHeight(image)==Height;check(shape,"profile-native-frame-size");if(!shape)break;
   if(!retained)retained=CGImageRetain(image);
   CFDataRef data=CGDataProviderCopyData(CGImageGetDataProvider(image));const uint8_t *bytes=data?CFDataGetBytePtr(data):NULL;size_t stride=CGImageGetBytesPerRow(image);unsigned bad=0;
   if(!bytes||CFDataGetLength(data)<(CFIndex)((Height-1)*stride+Width*4)){if(data)CFRelease(data);check(NO,"profile-image-data-range");break;}
   for(unsigned y=0;y<Height;y++)for(unsigned x=0;x<Width;x++){uint8_t expected[]={blue?255:0,green?255:0,red?255:0,255};if(negative&&frame==3&&y==0&&x==731)expected[0]^=8;if(memcmp(bytes+y*stride+x*4,expected,4))bad++;}
   CFRelease(data);check(!bad,"profile-all-native-pixels");pixels+=Width*Height;
   printf("METAL_TRANSFER_FRAME frame=%u commit_present_ms=%.3f check_ms=%.3f mismatches=%u\n",frame,(committed-start)*1000,(CACurrentMediaTime()-committed)*1000,bad);fflush(NULL);
  }}
  if(retained){CFDataRef data=CGDataProviderCopyData(CGImageGetDataProvider(retained));const uint8_t *bytes=data?CFDataGetBytePtr(data):NULL;size_t stride=CGImageGetBytesPerRow(retained);unsigned bad=0;
   if(!bytes||CFDataGetLength(data)<(CFIndex)((Height-1)*stride+Width*4))bad=1;
   else for(unsigned y=0;y<Height;y++)for(unsigned x=0;x<Width;x++){const uint8_t black[]={0,0,0,255};if(memcmp(bytes+y*stride+x*4,black,4))bad++;}
   check(!bad,"profile-retained-native-image-immutable");if(data)CFRelease(data);
  }
 }@catch(NSException *e){check(NO,"profile-exception");printf("METAL_TRANSFER_EXCEPTION name=%s reason=%s\n",e.name.UTF8String,e.reason.UTF8String);}
 if(retained)CGImageRelease(retained);check(pixels==Width*Height*Frames,"profile-all-native-frames");
 printf("METAL_API_RESULT pass=%s checks=%u failures=%u scope=profile-native-layer pixels=%u frames=%u negative=%u public_metal_messages=true\n",failures?"false":"true",checks,failures,pixels,Frames,negative);fflush(NULL);return failures?1:0;
}
