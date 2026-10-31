/* Authored pixel oracle, independent of the GPU/AIR implementation. */
#include <stdint.h>
static void sampling_texel(uint8_t out[4],unsigned x,unsigned y,unsigned variant){
 out[0]=(uint8_t)(17*x+13*y+31*variant);
 out[1]=(uint8_t)(11*x+7*y+67*variant+9);
 out[2]=(uint8_t)(7*x+19*y+23*variant+5);out[3]=255;
}
static void sampling_pixels(uint8_t out[96],unsigned variant){
 for(unsigned i=0;i<96;i++)out[i]=0x7b;
 for(unsigned y=0;y<4;y++)for(unsigned x=0;x<4;x++)sampling_texel(out+y*24+x*4,x,y,variant);
}
static int sampling_index(int index,int repeat){return repeat?(index%4+4)%4:index<0?0:index>3?3:index;}
static void sampling_expected(uint8_t out[4],unsigned x,unsigned y,unsigned variant,int repeat,int linear){
 if(linear){
  int nx=6*(int)x-9,ny=6*(int)y-9;
  int tx=nx>=0?nx/8:(nx-7)/8,ty=ny>=0?ny/8:(ny-7)/8;
  unsigned fx=(unsigned)(nx-tx*8),fy=(unsigned)(ny-ty*8),sum[4]={0};
  for(int iy=0;iy<2;iy++)for(int ix=0;ix<2;ix++){
   uint8_t pixel[4];sampling_texel(pixel,(unsigned)sampling_index(tx+ix,repeat),(unsigned)sampling_index(ty+iy,repeat),variant);
   unsigned weight=(ix?fx:8-fx)*(iy?fy:8-fy);for(unsigned c=0;c<4;c++)sum[c]+=pixel[c]*weight;
  }
  for(unsigned c=0;c<4;c++)out[c]=(uint8_t)((sum[c]+32)/64);
  return;
 }
 /* Sample centers map to (6*x-5)/8 in texel coordinates. */
 int nx=6*(int)x-5,ny=6*(int)y-5;
 int tx=nx>=0?nx/8:(nx-7)/8,ty=ny>=0?ny/8:(ny-7)/8;
 if(repeat){tx=(tx%4+4)%4;ty=(ty%4+4)%4;}
 else{tx=tx<0?0:tx>3?3:tx;ty=ty<0?0:ty>3?3:ty;}
 sampling_texel(out,(unsigned)tx,(unsigned)ty,variant);
}
static int sampling_differs(const uint8_t actual[4],const uint8_t expected[4],int linear){
 for(unsigned c=0;c<4;c++){int difference=(int)actual[c]-expected[c];if(difference<0)difference=-difference;if(difference>(c==3?0:linear))return 1;}
 return 0;
}
