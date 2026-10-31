/* Authored inputs and independent UNORM blending oracle. SPDX-License-Identifier: AGPL-3.0-or-later */
#define BLENDING_CASES 10
/* enabled, srcRGB, dstRGB, RGBop, srcA, dstA, Aop, MTLColorWriteMask */
static const uint32_t blending_cases[BLENDING_CASES][8]={
 {1,4,5,0,1,5,0,15}, {1,4,1,0,1,1,0,15},
 {1,1,1,1,1,1,2,15}, {1,1,1,3,1,1,4,15},
 {1,11,12,0,13,14,0,15}, {0,8,9,0,8,9,0,9},
 {1,1,1,0,1,1,0,0}, {1,2,7,0,10,0,0,6},
 {1,6,3,0,8,9,0,15}, {1,10,5,4,0,1,3,15}
};
static const uint8_t blending_clear[4]={64,128,191,64};
static void blending_source(float *rgba,unsigned variant){
 const float values[][4]={{.75f,.25f,.5f,.5f},{.125f,.875f,.375f,.75f}};
 memcpy(rgba,values[variant%2],16);
}
static void blending_constant(float *rgba,unsigned variant){
 const float values[][4]={{.2f,.6f,.4f,.8f},{.7f,.3f,.9f,.25f}};
 memcpy(rgba,values[variant%2],16);
}
static void blending_vertices(uint8_t *bytes,unsigned variant){
 layout_pixels(bytes,variant);float rgba[4];blending_source(rgba,variant);
 for(unsigned i=0;i<6;i++)memcpy(bytes+128+i*40+16,rgba,16);
}
static void blending_plain(float *xy,float *colors,unsigned variant){
 uint8_t interleaved[LAYOUT_BYTES];blending_vertices(interleaved,variant);
 for(unsigned i=0;i<6;i++){memcpy(xy+i*2,interleaved+128+i*40+4,8);memcpy(colors+i*4,interleaved+128+i*40+16,16);}
}
static float blending_factor(unsigned factor,unsigned channel,const float *src,const float *dst,const float *constant){
 switch(factor){
  case 0:return 0;case 1:return 1;case 2:return src[channel];case 3:return 1-src[channel];
  case 4:return src[3];case 5:return 1-src[3];case 6:return dst[channel];case 7:return 1-dst[channel];
  case 8:return dst[3];case 9:return 1-dst[3];case 10:return channel==3?1:(src[3]<1-dst[3]?src[3]:1-dst[3]);
  case 11:return constant[channel];case 12:return 1-constant[channel];case 13:return constant[3];case 14:return 1-constant[3];
  default:abort();
 }
}
static void blending_expected(uint8_t *rgba,unsigned x,unsigned y,unsigned which,unsigned variant){
 memcpy(rgba,blending_clear,4);if(x>=4||y>=4)return;
 float src[4],dst[4],constant[4];blending_source(src,variant);blending_constant(constant,variant);
 for(unsigned c=0;c<4;c++)dst[c]=blending_clear[c]/255.f;
 const uint32_t *state=blending_cases[which];
 for(unsigned c=0;c<4;c++){
  if(!(state[7]&(8u>>c)))continue;
  float value=src[c];
  if(state[0]){
   unsigned base=c==3?4:1,op=state[base+2];
   float s=src[c]*blending_factor(state[base],c,src,dst,constant);
   float d=dst[c]*blending_factor(state[base+1],c,src,dst,constant);
   switch(op){case 0:value=s+d;break;case 1:value=s-d;break;case 2:value=d-s;break;
    case 3:value=src[c]<dst[c]?src[c]:dst[c];break;case 4:value=src[c]>dst[c]?src[c]:dst[c];break;default:abort();}
  }
  if(value<0)value=0;if(value>1)value=1;rgba[c]=(uint8_t)(value*255.f+.5f);
 }
}
static int blending_differs(const uint8_t *actual,const uint8_t *expected,unsigned x,unsigned y,unsigned which){
 for(unsigned c=0;c<4;c++){
  int delta=(int)actual[c]-expected[c];if(delta<0)delta=-delta;
  unsigned tolerance=(x<4&&y<4&&(blending_cases[which][7]&(8u>>c)))?1:0;
  if((unsigned)delta>tolerance)return 1;
 }
 return 0;
}
