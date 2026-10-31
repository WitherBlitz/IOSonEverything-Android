/*
 * The OpenGL ES library behind src/eagl.c when that library is gfx (src/gfx): the host's GPU,
 * through gfxstream and /dev/vgpu3d (src/redwood_gl.h; src/gl_osmesa.c is the Mesa one).
 *
 * redwood_gl_surface_texture: the texture bound to GL_TEXTURE_2D becomes the IOSurface. On the
 * host it is a colour buffer that the texture is bound to, filled from the surface's memory now
 * (and every time eagl.c asks again, which it does when the surface has changed). What is drawn
 * into it is copied back into the surface's memory when the frame ends (glFlush, glFinish, the
 * fence wait of eagl.c's frame_end), so the display finds the frame where it looks.
 *
 * Environment GFX_SHARE=0: no shared surfaces (every surface goes through glTexImage2D and
 * glReadPixels instead).
 */
#include <IOSurface/IOSurfaceRef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <pthread.h>
#include "surface_protocol.h"

#include "redwood_gl.h"
#include "gfx.h"
int gfx_test_transport(struct gfx_transport *);

struct redwood_gl {
	struct gfx *gfx;
};
static pthread_once_t snapshot_key_once=PTHREAD_ONCE_INIT;
static CFStringRef snapshot_key;
static void make_snapshot_key(void){snapshot_key=CFSTR(IOSGPU_SURFACE_KEY);}
int redwood_gl_surface_marked(void *reference){
 IOSurfaceRef surface=reference;if(!surface)return 0;pthread_once(&snapshot_key_once,make_snapshot_key);
 if(!snapshot_key||IOSurfaceLock(surface,kIOSurfaceLockReadOnly,NULL))return 1;
 CFTypeRef marker=IOSurfaceCopyValue(surface,snapshot_key);int marked=marker!=NULL;if(marker)CFRelease(marker);
 if(IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,NULL))return 1;return marked;
}
void redwood_gl_snapshot_refuse(struct redwood_gl *gl){if(gl){gl->gfx->err=1;fprintf(stderr,"IOSGPU_GUEST_SNAPSHOT_ERROR unsupported_marked_view=1\n");}}
static uint64_t snapshot_binds;
/* Consumes the lookup/retained surface reference only on success. */
static int attach_surface(struct gfx *c,IOSurfaceRef surface){
 pthread_once(&snapshot_key_once,make_snapshot_key);if(!snapshot_key)return -1;
 for(unsigned attempt=0;attempt<3;attempt++){
  if(IOSurfaceLock(surface,kIOSurfaceLockReadOnly,NULL))return -1;
  uint32_t seed=IOSurfaceGetSeed(surface);CFTypeRef value=IOSurfaceCopyValue(surface,snapshot_key);
  if(value){
   struct iosgpu_surface_meta meta={0};int valid=CFGetTypeID(value)==CFDataGetTypeID()&&CFDataGetLength(value)==sizeof(meta);
   if(valid)memcpy(&meta,CFDataGetBytePtr(value),sizeof(meta));CFRelease(value);
   valid=valid&&iosgpu_surface_meta_valid(&meta)&&meta.surface==IOSurfaceGetID(surface)&&meta.width==IOSurfaceGetWidth(surface)&&meta.height==IOSurfaceGetHeight(surface)&&IOSurfaceGetPlaneCount(surface)==0&&IOSurfaceGetBytesPerElement(surface)==4&&IOSurfaceGetPixelFormat(surface)==0x42475241u;
   IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,NULL);
   if(!valid||!c->t.snapshot_resolve)return -1;
   uint32_t resource=0;int result=c->t.snapshot_resolve(c->t.arg,&meta,&resource);
   if(result)continue; /* A concurrent replacement/removal may have retired it. */
   if(!gfx_snapshot_texture(c,resource,(void *)surface,seed,meta.width,meta.height)){
    /* No new GL binding was established on a clean failure. A failed stream
     * keeps this resolve reference until actual host context destruction. */
    if(!c->err)c->t.res_unref(c->t.arg,resource);return -1;
   }
   snapshot_binds++;if(snapshot_binds<=3||snapshot_binds%300==0)fprintf(stderr,"IOSGPU_GUEST_SNAPSHOT_BIND count=%llu cpu_pixel_uploads=0\n",(unsigned long long)snapshot_binds);
   return 1;
  }
  /* Normal surface discard materializes its final BGRA image before removing
   * the metadata and advancing this seed. Only absent metadata permits CPU. */
  if(IOSurfaceGetPlaneCount(surface)>0||IOSurfaceGetBytesPerElement(surface)!=4){IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,NULL);return 0;}
  int ok=gfx_share_texture(c,IOSurfaceGetID(surface),IOSurfaceGetBaseAddress(surface),(uint32_t)IOSurfaceGetWidth(surface),(uint32_t)IOSurfaceGetHeight(surface),(uint32_t)IOSurfaceGetBytesPerRow(surface),1,(void *)surface);
  IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,NULL);
  if(ok)gfx_snapshot_forget_bound(c);return ok;
 }return -1;
}
static int refresh_surface(struct gfx *c,void *user){
 IOSurfaceRef surface=(IOSurfaceRef)CFRetain(user);int ok=attach_surface(c,surface);if(ok<=0)CFRelease(surface);return ok>0;
}

static uint32_t
surface_seed(void *user)
{
	return IOSurfaceGetSeed((IOSurfaceRef)user);
}

static void
surface_release(void *user)
{
	CFRelease((IOSurfaceRef)user);
}

struct redwood_gl *
redwood_gl_create(int version)
{
	struct gfx_transport t = { 0 };
	struct redwood_gl *gl;

	if (gfx_test_transport(&t) != 0) {
		return NULL;
	}
	gl = calloc(1, sizeof(*gl));
	if (gl == NULL || (gl->gfx = gfx_create(&t, version)) == NULL) {
		free(gl);
		return NULL;
	}
	gl->gfx->seed_of = surface_seed;
	gl->gfx->release = surface_release;
	gl->gfx->snapshot_refresh = refresh_surface;
	return gl;
}

int
redwood_gl_make_current(struct redwood_gl *gl)
{
	return gfx_make_current(gl ? gl->gfx : NULL);
}

void
redwood_gl_destroy(struct redwood_gl *gl)
{
	gfx_destroy(gl->gfx);
	free(gl);
}

const char *
redwood_gl_library(void)
{
	return "gfx: Adreno via bounded Android TCG transport";
}

int
redwood_gl_surface_texture_ref(struct redwood_gl *gl, void *reference)
{
	static int share = -1;
	IOSurfaceRef surface;
	int ok;

	if (share < 0) {
		const char *e = getenv("GFX_SHARE");
		share = e == NULL || strcmp(e, "0") != 0;
	}
	if (!reference) {
		return 0;
	}
	surface=(IOSurfaceRef)CFRetain(reference);
	if(!share){
		pthread_once(&snapshot_key_once,make_snapshot_key);
		if(!snapshot_key||IOSurfaceLock(surface,kIOSurfaceLockReadOnly,NULL)){CFRelease(surface);gl->gfx->err=1;return 1;}
		CFTypeRef marker=snapshot_key?IOSurfaceCopyValue(surface,snapshot_key):NULL;
		IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,NULL);
		if(marker){CFRelease(marker);CFRelease(surface);gl->gfx->err=1;return 1;}
		CFRelease(surface);return 0;
	}
	/*
	 * The base address stays valid while the surface lives: eagl.c holds it for as long as the
	 * texture is the surface. The lock is for reading it now.
	 */
	ok = attach_surface(gl->gfx,surface);
	if (ok<=0) {
		CFRelease(surface);
	}
	/* A marked failure must never select eagl.c's ordinary CPU upload path. */
	if(ok<0){gl->gfx->err=1;fprintf(stderr,"IOSGPU_GUEST_SNAPSHOT_ERROR marked_surface_unavailable=1\n");return 1;}
	return ok>0;
}
int redwood_gl_surface_texture(struct redwood_gl *gl,uint32_t id){IOSurfaceRef surface=IOSurfaceLookup(id);if(!surface)return 0;int ok=redwood_gl_surface_texture_ref(gl,surface);CFRelease(surface);return ok;}
void redwood_gl_refresh_surfaces(struct redwood_gl *gl){if(gl)gfx_snapshot_refresh_all(gl->gfx);}

