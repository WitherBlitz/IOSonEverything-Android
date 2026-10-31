/* Authored sparse/interleaved input and independent raster oracle. */
#define LAYOUT_BYTES (128+6*40+64)
static void layout_pixels(uint8_t *bytes,unsigned variant){
 const float xy[]={-1,1,0,1,-1,0,0,1,0,0,-1,0};
 const float colors[][4]={{1,.2f,0,1},{.2f,1,.4f,1}};
 memset(bytes,0x63,LAYOUT_BYTES);
 for(unsigned i=0;i<6;i++){
  memcpy(bytes+128+i*40+4,xy+i*2,8);
  memcpy(bytes+128+i*40+16,colors[variant%2],16);
 }
}
static void layout_expected(uint8_t *rgba,unsigned x,unsigned y,unsigned variant){
 rgba[0]=0;rgba[1]=0;rgba[2]=255;rgba[3]=255;
 if(x<4&&y<4){rgba[0]=variant?51:255;rgba[1]=variant?255:51;rgba[2]=variant?102:0;}
}
