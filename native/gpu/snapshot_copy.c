/* Worker-owned GPU snapshot copy. SPDX-License-Identifier: AGPL-3.0-or-later */
#define GL_GLEXT_PROTOTYPES
#include "snapshot_copy.h"
#include "iosgpu_metal.h"
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <GLES2/gl2ext.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct imported {uint64_t id;AHardwareBuffer *buffer;EGLImageKHR image;GLuint texture;uint32_t width,height;};
struct iosgpu_snapshot_copy {
 EGLDisplay display;EGLContext context;EGLSurface surface;
 PFNEGLGETNATIVECLIENTBUFFERANDROIDPROC client;
 PFNEGLCREATEIMAGEKHRPROC image_create;PFNEGLDESTROYIMAGEKHRPROC image_destroy;
 PFNEGLCREATESYNCKHRPROC sync_create;PFNEGLDESTROYSYNCKHRPROC sync_destroy;
 PFNEGLWAITSYNCKHRPROC sync_wait;PFNGLEGLIMAGETARGETTEXTURE2DOESPROC image_bind;
 GLuint program,vao,fbo;struct imported imports[3];unsigned next;
 struct iosgpu_snapshot_target targets[32];uint64_t target_bytes;
 int poisoned;uint64_t copies,created,reused;
};
struct previous {EGLDisplay display;EGLContext context;EGLSurface draw,read;};
static struct previous previous(void){return (struct previous){eglGetCurrentDisplay(),eglGetCurrentContext(),eglGetCurrentSurface(EGL_DRAW),eglGetCurrentSurface(EGL_READ)};}
static int restore(struct iosgpu_snapshot_copy *c,struct previous p){return eglMakeCurrent(p.display==EGL_NO_DISPLAY?c->display:p.display,p.draw,p.read,p.context)?0:-EIO;}
static int leave(struct iosgpu_snapshot_copy *c,struct previous p,int result){if(restore(c,p)){c->poisoned=1;return -EIO;}return result;}
static int current(struct iosgpu_snapshot_copy *c){return eglMakeCurrent(c->display,c->surface,c->surface,c->context)?0:-EIO;}
static void drop_import(struct iosgpu_snapshot_copy *c,struct imported *i){
 if(!i->id)return;glDeleteTextures(1,&i->texture);c->image_destroy(c->display,i->image);AHardwareBuffer_release(i->buffer);memset(i,0,sizeof(*i));
}
static GLuint shader(GLenum type,const char *source){
 GLuint s=glCreateShader(type);if(!s)return 0;glShaderSource(s,1,&source,NULL);glCompileShader(s);GLint ok=0;glGetShaderiv(s,GL_COMPILE_STATUS,&ok);if(!ok){glDeleteShader(s);return 0;}return s;
}
static int setup(struct iosgpu_snapshot_copy *c){
 const char *vertex="#version 300 es\nvoid main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(p*2.0-1.0,0,1);}";
 const char *fragment="#version 300 es\nprecision highp float;uniform highp sampler2D image;out vec4 color;void main(){color=texelFetch(image,ivec2(gl_FragCoord.xy),0);}";
 GLuint vs=shader(GL_VERTEX_SHADER,vertex),fs=shader(GL_FRAGMENT_SHADER,fragment);
 if(!vs||!fs){glDeleteShader(vs);glDeleteShader(fs);return -EIO;}
 c->program=glCreateProgram();glAttachShader(c->program,vs);glAttachShader(c->program,fs);glLinkProgram(c->program);glDeleteShader(vs);glDeleteShader(fs);
 GLint ok=0;glGetProgramiv(c->program,GL_LINK_STATUS,&ok);if(!ok)return -EIO;
 glUseProgram(c->program);glUniform1i(glGetUniformLocation(c->program,"image"),0);
 glGenVertexArrays(1,&c->vao);glGenFramebuffers(1,&c->fbo);
 glDisable(GL_DITHER);glDisable(GL_BLEND);glDisable(GL_SCISSOR_TEST);glDisable(GL_DEPTH_TEST);
 return glGetError()==GL_NO_ERROR?0:-EIO;
}
struct iosgpu_snapshot_copy *iosgpu_snapshot_copy_create(void *shared_parent){
 if(!shared_parent)return NULL;
 struct iosgpu_snapshot_copy *c=calloc(1,sizeof(*c));if(!c)return NULL;
 struct previous p=previous();EGLConfig config;EGLint count=0,id=0,type=0,version=0;
 c->display=eglGetDisplay(EGL_DEFAULT_DISPLAY);if(c->display==EGL_NO_DISPLAY||!eglInitialize(c->display,NULL,NULL)||!eglBindAPI(EGL_OPENGL_ES_API))goto fail;
 if(!eglQueryContext(c->display,shared_parent,EGL_CONFIG_ID,&id)||!eglQueryContext(c->display,shared_parent,EGL_CONTEXT_CLIENT_TYPE,&type)||!eglQueryContext(c->display,shared_parent,EGL_CONTEXT_CLIENT_VERSION,&version)||type!=EGL_OPENGL_ES_API||version<3)goto fail;
 EGLint ca[]={EGL_CONFIG_ID,id,EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT,EGL_NONE};
 if(!eglChooseConfig(c->display,ca,&config,1,&count)||count!=1)goto fail;
 EGLint sa[]={EGL_WIDTH,1,EGL_HEIGHT,1,EGL_NONE};c->surface=eglCreatePbufferSurface(c->display,config,sa);if(c->surface==EGL_NO_SURFACE)goto fail;
 if(!eglMakeCurrent(c->display,c->surface,c->surface,shared_parent))goto fail;
 GLint reset=0;glGetIntegerv(GL_RESET_NOTIFICATION_STRATEGY_KHR,&reset);if(glGetError()!=GL_NO_ERROR||(reset!=GL_LOSE_CONTEXT_ON_RESET_KHR&&reset!=GL_NO_RESET_NOTIFICATION_KHR))goto fail;
 if(!eglMakeCurrent(c->display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT))goto fail;
 EGLint attrs[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_CONTEXT_OPENGL_RESET_NOTIFICATION_STRATEGY_EXT,reset==GL_LOSE_CONTEXT_ON_RESET_KHR?EGL_LOSE_CONTEXT_ON_RESET_EXT:EGL_NO_RESET_NOTIFICATION_EXT,EGL_NONE};
 c->context=eglCreateContext(c->display,config,shared_parent,attrs);if(c->context==EGL_NO_CONTEXT||current(c))goto fail;
#define LOAD(member,name) c->member=(void *)eglGetProcAddress(name);if(!c->member)goto fail
 LOAD(client,"eglGetNativeClientBufferANDROID");LOAD(image_create,"eglCreateImageKHR");LOAD(image_destroy,"eglDestroyImageKHR");LOAD(image_bind,"glEGLImageTargetTexture2DOES");LOAD(sync_create,"eglCreateSyncKHR");LOAD(sync_destroy,"eglDestroySyncKHR");LOAD(sync_wait,"eglWaitSyncKHR");
#undef LOAD
 if(setup(c)||restore(c,p))goto fail;return c;
fail:
 if(c->context!=EGL_NO_CONTEXT&&current(c)==0){glDeleteProgram(c->program);glDeleteVertexArrays(1,&c->vao);glDeleteFramebuffers(1,&c->fbo);}
 if(c->display!=EGL_NO_DISPLAY){restore(c,p);if(c->context!=EGL_NO_CONTEXT)eglDestroyContext(c->display,c->context);if(c->surface!=EGL_NO_SURFACE)eglDestroySurface(c->display,c->surface);}
 free(c);return NULL;
}
static struct imported *import_frame(struct iosgpu_snapshot_copy *c,struct iosmetal_frame frame){
 uint64_t id=0;if(AHardwareBuffer_getId(frame.buffer,&id)||!id)return NULL;
 for(unsigned n=0;n<3;n++)if(c->imports[n].id==id){struct imported *i=&c->imports[n];if(i->width!=frame.width||i->height!=frame.height)return NULL;c->reused++;return i;}
 struct imported *i=&c->imports[c->next++%3];drop_import(c,i);
 EGLint attrs[]={EGL_IMAGE_PRESERVED_KHR,EGL_TRUE,EGL_NONE};
 EGLImageKHR image=c->image_create(c->display,EGL_NO_CONTEXT,EGL_NATIVE_BUFFER_ANDROID,c->client(frame.buffer),attrs);if(image==EGL_NO_IMAGE_KHR)return NULL;
 GLuint texture=0;glGenTextures(1,&texture);glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,texture);c->image_bind(GL_TEXTURE_2D,image);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
 // Finish creation before Vulkan can write this newly imported allocation.
 glFinish();if(glGetError()!=GL_NO_ERROR){glDeleteTextures(1,&texture);c->image_destroy(c->display,image);return NULL;}
 AHardwareBuffer_acquire(frame.buffer);*i=(struct imported){id,frame.buffer,image,texture,frame.width,frame.height};c->created++;return i;
}
int iosgpu_snapshot_copy(struct iosgpu_snapshot_copy *c,void *metal,uint64_t source,uint32_t destination,uint32_t width,uint32_t height,const struct iosgpu_frame_api *api){
 if(!c||!metal||!api||!api->prepare||!api->submit||!api->cancel||!api->returned||!api->collect||!source||!destination||!width||!height||width>8192||height>8192||(uint64_t)width*height>8u*1024u*1024u)return -EINVAL;
 if(c->poisoned)return -EIO;
 // Only targets allocated and tracked by this copy owner are writable. Besides
 // rejecting foreign textures, this pins their actual storage dimensions.
 int owned=0;for(unsigned n=0;n<32;n++)if(c->targets[n].buffer&&c->targets[n].texture==destination&&c->targets[n].width==width&&c->targets[n].height==height){owned=1;break;}if(!owned)return -EINVAL;
 struct previous p=previous();int result=current(c);if(result)return result;
 if(!glIsTexture(destination)||glGetError()!=GL_NO_ERROR)return leave(c,p,-EINVAL);
 struct iosmetal_frame frame={0};result=api->prepare(metal,source,&frame);
 /* The qualified runtime reports nonfatal preparation refusals as EINVAL,
  * including its export-memory quota. No descriptor was submitted or exposed.
  * Distinguish that safe refusal from any later GPU/restore failure. */
 if(result)return leave(c,p,result==-EINVAL||result==-ENOMEM||result==-ENOSPC||result==-EAGAIN?-ENOBUFS:result);
 if(frame.version!=1||frame.format!=70||frame.reserved||!frame.buffer||frame.width!=width||frame.height!=height||frame.ready_fd!=-1){result=-EINVAL;goto cancel;}
 struct imported *i=import_frame(c,frame);if(!i){result=-EIO;goto cancel;}
 glBindFramebuffer(GL_FRAMEBUFFER,c->fbo);glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,destination,0);
 if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE||glGetError()!=GL_NO_ERROR){result=-EIO;goto cancel;}
 result=api->submit(metal,frame.token,&frame.ready_fd);if(result)goto poisoned;
 if(frame.ready_fd>=0){
  EGLint attrs[]={EGL_SYNC_NATIVE_FENCE_FD_ANDROID,frame.ready_fd,EGL_NONE};EGLSyncKHR sync=c->sync_create(c->display,EGL_SYNC_NATIVE_FENCE_ANDROID,attrs);
  if(sync==EGL_NO_SYNC_KHR){close(frame.ready_fd);result=-EIO;goto poisoned;}
  int waited=c->sync_wait(c->display,sync,0),dropped=c->sync_destroy(c->display,sync);if(!waited||!dropped){result=-EIO;goto poisoned;}
 }
 glViewport(0,0,width,height);glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,i->texture);glUseProgram(c->program);glBindVertexArray(c->vao);glDrawArrays(GL_TRIANGLES,0,3);
 // This is our own GPU read, independent of any guest acknowledgment.
 glFinish();if(glGetError()!=GL_NO_ERROR){result=-EIO;goto poisoned;}
 glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,0,0);
 result=api->returned(metal,frame.token,-1);if(result)goto poisoned;
 for(unsigned n=0;n<8000;n++){result=api->collect(metal);if(result!=-EAGAIN)break;usleep(1000);}
 if(result)goto poisoned;c->copies++;return leave(c,p,0);
cancel:
 // The descriptor has not been submitted. Discard its consumer import first.
 for(unsigned n=0;n<3;n++)if(c->imports[n].buffer==frame.buffer)drop_import(c,&c->imports[n]);
 glBindFramebuffer(GL_FRAMEBUFFER,c->fbo);glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,0,0);
 if(glGetError()!=GL_NO_ERROR)c->poisoned=1;
 if(api->cancel(metal,frame.token))c->poisoned=1;
 return leave(c,p,result);
poisoned:
 c->poisoned=1;return leave(c,p,result?result:-EIO);
}
void iosgpu_snapshot_copy_stats(const struct iosgpu_snapshot_copy *c,uint64_t stats[4]){
 if(c&&stats){stats[0]=c->copies;stats[1]=c->created;stats[2]=c->reused;stats[3]=0;}
}
int iosgpu_snapshot_copy_clear_imports(struct iosgpu_snapshot_copy *c){
 if(!c)return 1;if(c->poisoned)return 0;struct previous p=previous();if(current(c))return 0;
 glFinish();if(glGetError()!=GL_NO_ERROR){c->poisoned=1;restore(c,p);return 0;}
 for(unsigned n=0;n<3;n++)drop_import(c,&c->imports[n]);return leave(c,p,0)==0;
}
int iosgpu_snapshot_copy_destroy(struct iosgpu_snapshot_copy *c){
 if(!c)return 1;if(c->poisoned||c->target_bytes)return 0;struct previous p=previous();if(current(c))return 0;
 glFinish();if(glGetError()!=GL_NO_ERROR){c->poisoned=1;restore(c,p);return 0;}
 for(unsigned n=0;n<3;n++)drop_import(c,&c->imports[n]);glDeleteProgram(c->program);glDeleteVertexArrays(1,&c->vao);glDeleteFramebuffers(1,&c->fbo);
 if(restore(c,p)){c->poisoned=1;return 0;}
 int ok=eglDestroyContext(c->display,c->context)&&eglDestroySurface(c->display,c->surface);if(!ok){c->poisoned=1;return 0;}free(c);return 1;
}
int iosgpu_snapshot_target_create(struct iosgpu_snapshot_copy *c,uint32_t width,uint32_t height,struct iosgpu_snapshot_target *out){
 if(!c||!out||!width||!height||width>8192||height>8192||(uint64_t)width*height*4>32u*1024u*1024u)return -EINVAL;
 if(c->poisoned)return -EIO;unsigned at=32;for(unsigned n=0;n<32;n++)if(!c->targets[n].buffer){at=n;break;}
 uint64_t estimate=(uint64_t)width*height*4;if(at==32||estimate>256u*1024u*1024u-c->target_bytes)return -ENOSPC;
 struct previous p=previous();if(current(c))return -EIO;
 struct iosgpu_snapshot_target t={.width=width,.height=height};AHardwareBuffer_Desc desc={.width=width,.height=height,.layers=1,.format=AHARDWAREBUFFER_FORMAT_R8G8B8A8_UNORM,.usage=AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE|AHARDWAREBUFFER_USAGE_GPU_COLOR_OUTPUT};
 if(AHardwareBuffer_allocate(&desc,&t.buffer))return leave(c,p,-ENOMEM);
 AHardwareBuffer_describe(t.buffer,&desc);uint64_t bytes=(uint64_t)desc.stride*height*4;
 if(bytes<estimate||bytes>32u*1024u*1024u||bytes>256u*1024u*1024u-c->target_bytes){AHardwareBuffer_release(t.buffer);return leave(c,p,-ENOSPC);}
 EGLint attrs[]={EGL_IMAGE_PRESERVED_KHR,EGL_TRUE,EGL_NONE};t.image=c->image_create(c->display,EGL_NO_CONTEXT,EGL_NATIVE_BUFFER_ANDROID,c->client(t.buffer),attrs);
 if(t.image==EGL_NO_IMAGE_KHR){AHardwareBuffer_release(t.buffer);return leave(c,p,-EIO);}
 glGenTextures(1,&t.texture);glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,t.texture);c->image_bind(GL_TEXTURE_2D,t.image);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);glFinish();
 if(glGetError()!=GL_NO_ERROR){c->poisoned=1;c->targets[at]=t;c->target_bytes+=bytes;restore(c,p);return -EIO;}
 c->targets[at]=t;c->target_bytes+=bytes;
 if(restore(c,p)){c->poisoned=1;return -EIO;}*out=t;return 0;
}
int iosgpu_snapshot_target_destroy(struct iosgpu_snapshot_copy *c,struct iosgpu_snapshot_target *target){
 if(!c||!target||c->poisoned)return 0;unsigned at=32;
 for(unsigned n=0;n<32;n++)if(c->targets[n].buffer&&c->targets[n].buffer==target->buffer&&c->targets[n].texture==target->texture&&c->targets[n].image==target->image&&c->targets[n].width==target->width&&c->targets[n].height==target->height){at=n;break;}
 if(at==32)return 0;struct previous p=previous();if(current(c))return 0;
 glFinish();if(glGetError()!=GL_NO_ERROR){c->poisoned=1;restore(c,p);return 0;}
 glDeleteTextures(1,&target->texture);if(!c->image_destroy(c->display,target->image)){c->poisoned=1;restore(c,p);return 0;}
 AHardwareBuffer_Desc desc;AHardwareBuffer_describe(target->buffer,&desc);c->target_bytes-=(uint64_t)desc.stride*target->height*4;AHardwareBuffer_release(target->buffer);
 memset(&c->targets[at],0,sizeof(c->targets[at]));memset(target,0,sizeof(*target));if(restore(c,p)){c->poisoned=1;return 0;}return 1;
}
