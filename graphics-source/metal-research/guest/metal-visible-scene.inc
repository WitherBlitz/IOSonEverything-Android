/* Authored application scene and independent pixel check. AGPL-3.0-or-later. */
#include "sampling-fixture.h"
static id<MTLRenderPipelineState> scenePipeline(id<MTLDevice> device,id<MTLLibrary> library,BOOL textured,NSError **error){
 MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new];
 pd.vertexFunction=[library newFunctionWithName:textured?@"layout_vertex":@"colored_vertex"];
 pd.fragmentFunction=[library newFunctionWithName:textured?@"textured_fragment":@"colored_fragment"];
 if(!pd.vertexFunction||!pd.fragmentFunction){if(error)*error=[NSError errorWithDomain:@"IOSMetalVisible" code:1 userInfo:@{NSLocalizedDescriptionKey:@"Required authored scene shader is unavailable"}];return nil;}
 pd.colorAttachments[0].pixelFormat=MTLPixelFormatBGRA8Unorm;
 if(textured){
  MTLVertexDescriptor *layout=[MTLVertexDescriptor vertexDescriptor];layout.attributes[3].format=MTLVertexFormatFloat2;layout.attributes[3].offset=0;layout.attributes[3].bufferIndex=6;layout.attributes[7].format=MTLVertexFormatFloat4;layout.attributes[7].offset=8;layout.attributes[7].bufferIndex=6;layout.layouts[6].stride=24;pd.vertexDescriptor=layout;
  MTLRenderPipelineColorAttachmentDescriptor *color=pd.colorAttachments[0];color.blendingEnabled=YES;color.sourceRGBBlendFactor=MTLBlendFactorSourceAlpha;color.destinationRGBBlendFactor=MTLBlendFactorOneMinusSourceAlpha;color.sourceAlphaBlendFactor=MTLBlendFactorOne;color.destinationAlphaBlendFactor=MTLBlendFactorOneMinusSourceAlpha;
 }
 return [device newRenderPipelineStateWithDescriptor:pd error:error];
}
static void sceneVertices(float *out,float x0,float y0,float x1,float y1,float u0,float v0,float u1,float v1,float opacity){
 const float xy[]={x0,y1,x1,y1,x0,y0,x1,y1,x1,y0,x0,y0};
 const float uv[]={u0,v0,u1,v0,u0,v1,u1,v0,u1,v1,u0,v1};
 for(unsigned i=0;i<6;i++){out[i*6]=xy[i*2];out[i*6+1]=xy[i*2+1];out[i*6+2]=uv[i*2];out[i*6+3]=uv[i*2+1];out[i*6+4]=opacity;out[i*6+5]=1;}
}
static id<MTLTexture> sceneTexture(id<MTLDevice> device,unsigned variant){
 MTLTextureDescriptor *descriptor=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:4 height:4 mipmapped:NO];descriptor.storageMode=MTLStorageModeShared;descriptor.usage=MTLTextureUsageShaderRead;
 id<MTLTexture> texture=[device newTextureWithDescriptor:descriptor];uint8_t data[96];sampling_pixels(data,variant);[texture replaceRegion:MTLRegionMake2D(0,0,4,4) mipmapLevel:0 withBytes:data bytesPerRow:24];return texture;
}
static id<MTLSamplerState> sceneSampler(id<MTLDevice> device,BOOL linear,BOOL repeat){
 MTLSamplerDescriptor *descriptor=[MTLSamplerDescriptor new];descriptor.minFilter=linear?MTLSamplerMinMagFilterLinear:MTLSamplerMinMagFilterNearest;descriptor.magFilter=descriptor.minFilter;descriptor.sAddressMode=repeat?MTLSamplerAddressModeRepeat:MTLSamplerAddressModeClampToEdge;descriptor.tAddressMode=descriptor.sAddressMode;return [device newSamplerStateWithDescriptor:descriptor];
}
static void sceneEncode(id<MTLRenderCommandEncoder> encoder,id<MTLRenderPipelineState> background,id<MTLRenderPipelineState> foreground,id<MTLBuffer> positions,id<MTLBuffer> colors,id<MTLBuffer> vertices,id<MTLTexture> texture,id<MTLSamplerState> sampler){
 [encoder setRenderPipelineState:background];[encoder setVertexBuffer:positions offset:0 atIndex:0];[encoder setVertexBuffer:colors offset:0 atIndex:1];[encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];
 [encoder setRenderPipelineState:foreground];[encoder setVertexBuffer:vertices offset:0 atIndex:6];[encoder setFragmentTexture:texture atIndex:3];[encoder setFragmentSamplerState:sampler atIndex:5];[encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];
}
static int sceneSelfTest(NSString *path,BOOL negative){
 @try{
  id<MTLDevice> device=MTLCreateSystemDefaultDevice();NSData *source=[NSData dataWithContentsOfFile:path];NSError *error=nil;
  if(!device||!source.length){puts("METAL_TEXTURED_RESULT pass=false reason=device-or-library-file");return 2;}
  dispatch_data_t data=dispatch_data_create(source.bytes,source.length,NULL,DISPATCH_DATA_DESTRUCTOR_DEFAULT);id<MTLLibrary> library=[device newLibraryWithData:data error:&error];
  id<MTLRenderPipelineState> background=scenePipeline(device,library,NO,&error),foreground=scenePipeline(device,library,YES,&error);
  if(!library||!background||!foreground){printf("METAL_TEXTURED_RESULT pass=false reason=pipeline functions=%lu error=%s\n",(unsigned long)library.functionNames.count,error.description.UTF8String);return 3;}
  const float xy[]={-1,1,1,1,-1,-1,1,1,1,-1,-1,-1};float rgba[24];for(unsigned i=0;i<6;i++){rgba[i*4]=32/255.f;rgba[i*4+1]=64/255.f;rgba[i*4+2]=96/255.f;rgba[i*4+3]=1;}
  id<MTLBuffer> positions=[device newBufferWithBytes:xy length:sizeof(xy) options:0],colors=[device newBufferWithBytes:rgba length:sizeof(rgba) options:0],vertices=[device newBufferWithLength:6*24 options:0];
  MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:8 height:8 mipmapped:NO];shape.storageMode=MTLStorageModeShared;shape.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;id<MTLTexture> target=[device newTextureWithDescriptor:shape];id<MTLCommandQueue> queue=[device newCommandQueue];unsigned mismatches=0,padding=0,completed=0;
  id<MTLTexture> textures[]={sceneTexture(device,0),sceneTexture(device,1)};
  for(unsigned frame=0;frame<8;frame++){
   unsigned variant=frame%2,linear=(frame/2)%2,repeat=(frame/4)%2,numerator=variant?3:2;float opacity=numerator/4.f;sceneVertices(vertices.contents,-1,-1,1,1,-.25f,-.25f,1.25f,1.25f,opacity);
   id<MTLSamplerState> sampler=sceneSampler(device,linear,repeat);id<MTLCommandBuffer> command=[queue commandBuffer];MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=target;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,1,1);
   id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];sceneEncode(encoder,background,foreground,positions,colors,vertices,textures[variant],sampler);[encoder endEncoding];[command commit];[command waitUntilCompleted];if(command.status==MTLCommandBufferStatusCompleted&&!command.error)completed++;
   uint8_t result[8*48];memset(result,0x7b,sizeof(result));[target getBytes:result bytesPerRow:48 fromRegion:MTLRegionMake2D(0,0,8,8) mipmapLevel:0];unsigned bad=0;
   for(unsigned y=0;y<8;y++){
    for(unsigned x=0;x<8;x++){
     uint8_t sampled[4],expected[4];sampling_expected(sampled,x,y,variant,repeat,linear);
     const unsigned clear[]={32,64,96};for(unsigned c=0;c<3;c++)expected[c]=(uint8_t)((sampled[c]*numerator+clear[c]*(4-numerator)+2)/4);expected[3]=255;
     if(negative&&frame==0&&x==0&&y==0)expected[0]^=8;
     uint8_t *pixel=result+y*48+x*4,actual[]={pixel[2],pixel[1],pixel[0],pixel[3]};if(sampling_differs(actual,expected,1))bad++;
    }
    for(unsigned x=32;x<48;x++)if(result[y*48+x]!=0x7b)padding++;
   }
   if(bad)printf("METAL_TEXTURED_CASE frame=%u mismatches=%u\n",frame,bad);mismatches+=bad;
  }
  BOOL pass=!mismatches&&!padding&&completed==8;printf("METAL_TEXTURED_RESULT pass=%s pixels=512 frames=8 completed=%u mismatches=%u padding_errors=%u interpolated_uv=true two_draws=true alpha_blend=true negative=%s\n",pass?"true":"false",completed,mismatches,padding,negative?"true":"false");fflush(NULL);return pass?0:1;
 }@catch(NSException *e){printf("METAL_TEXTURED_RESULT pass=false reason=exception name=%s message=%s\n",e.name.UTF8String,e.reason.UTF8String);fflush(NULL);return 4;}
}
