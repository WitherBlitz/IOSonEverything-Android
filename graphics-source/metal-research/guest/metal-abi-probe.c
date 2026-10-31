/* Read-only Metal runtime contract probe in our disposable guest process. */
typedef void *Obj;
typedef unsigned long usize;
typedef unsigned char Bool;
struct method_description { Obj name; const char *types; };
extern void *dlopen(const char *,int), *dlsym(void *,const char *);
extern char *dlerror(void);
extern int printf(const char *,...), puts(const char *), fflush(void *);
extern void free(void *);
extern unsigned int alarm(unsigned int);

int main(int argc, char **argv) {
    (void)argv;
    alarm(20);
    void *objc=dlopen("/usr/lib/libobjc.A.dylib",2);
    void *metal=dlopen("/System/Library/Frameworks/Metal.framework/Metal",2);
    void *iogpu=dlopen("/System/Library/PrivateFrameworks/IOGPU.framework/IOGPU",2);
    printf("METALABI v1 objc=%p metal=%p iogpu=%p\n",objc,metal,iogpu);
    if(!objc||!metal){printf("METALABI load_error=%.200s\n",dlerror());return 2;}
    Obj (*get_class)(const char *)=dlsym(objc,"objc_getClass");
    Obj (*get_sel)(const char *)=dlsym(objc,"sel_registerName");
    Obj (*instance_method)(Obj,Obj)=dlsym(objc,"class_getInstanceMethod");
    const char *(*method_types)(Obj)=dlsym(objc,"method_getTypeEncoding");
    usize (*instance_size)(Obj)=dlsym(objc,"class_getInstanceSize");
    Obj (*superclass)(Obj)=dlsym(objc,"class_getSuperclass");
    const char *(*class_name)(Obj)=dlsym(objc,"class_getName");
    Obj (*get_protocol)(const char *)=dlsym(objc,"objc_getProtocol");
    struct method_description *(*copy_descriptions)(Obj,Bool,Bool,unsigned int *)=
        dlsym(objc,"protocol_copyMethodDescriptionList");
    struct method_description (*description)(Obj,Obj,Bool,Bool)=dlsym(objc,"protocol_getMethodDescription");
    const char *(*sel_name)(Obj)=dlsym(objc,"sel_getName");
    if(!get_class||!get_sel||!instance_method||!method_types||!instance_size||!superclass||
       !class_name||!get_protocol||!copy_descriptions||!description||!sel_name){
        puts("METALABI missing_runtime_api");return 3;
    }
    const char *classes[]={"_MTLDevice","MTLIOAccelDevice","IOGPUMetalDevice",
        "_MTLCommandQueue","_MTLCommandBuffer","_MTLResource","_MTLBuffer",
        "_MTLTexture","_MTLFunction","_MTLLibrary","_MTLComputePipelineState",
        "_MTLRenderPipelineState","AGXA13Device","AGXG12PDevice"};
    const char *selectors[]={"initWithAcceleratorPort:","initWithDevice:","initWithDevice:options:",
        "featureProfile","maxBufferLength","supportsVertexAmplificationCount:","name",
        "newBufferWithLength:options:","newTextureWithDescriptor:","newLibraryWithData:error:",
        "newLibraryWithSource:options:error:","newCommandQueue","bitcodeData","functionName",
        "initWithDevice:reflection:options:","initWithDevice:options:reflection:","dealloc"};
    /* Full metadata was already recorded in recovery. Keep normal-boot output
     * small: the shared emulated console can block behind compositor logging. */
    if(argc>1) for(unsigned int i=0;i<sizeof(classes)/sizeof(classes[0]);i++){
        Obj cls=get_class(classes[i]);
        printf("METALABI class=%.80s present=%u size=%lu parent=%.80s\n",classes[i],cls!=0,
            cls?instance_size(cls):0,cls&&superclass(cls)?class_name(superclass(cls)):"none");
        if(!cls)continue;
        for(unsigned int j=0;j<sizeof(selectors)/sizeof(selectors[0]);j++){
            Obj m=instance_method(cls,get_sel(selectors[j]));
            if(m)printf("METALABI method class=%.80s selector=%.120s types=%.180s\n",
                classes[i],selectors[j],method_types(m));
        }
    }
    const char *protocols[]={"MTLDevice","MTLDeviceSPI","MTLBuffer","MTLTexture","MTLFunction",
        "MTLLibrary","MTLCommandQueue","MTLCommandBuffer","MTLComputeCommandEncoder",
        "MTLRenderCommandEncoder","MTLComputePipelineState","MTLRenderPipelineState"};
    if(argc>1) for(unsigned int i=0;i<sizeof(protocols)/sizeof(protocols[0]);i++){
        Obj protocol=get_protocol(protocols[i]);unsigned int count=0;
        struct method_description *list=protocol?copy_descriptions(protocol,1,1,&count):0;
        printf("METALABI protocol=%.80s present=%u required_count=%u print_cap=64\n",protocols[i],protocol!=0,count);
        if(list)for(unsigned int j=0;j<count&&j<64;j++)printf(
            "METALABI requirement protocol=%.80s selector=%.120s types=%.180s\n",
            protocols[i],sel_name(list[j].name),list[j].types?list[j].types:"none");
        free(list);
        if(protocol)for(unsigned int j=0;j<sizeof(selectors)/sizeof(selectors[0]);j++){
            struct method_description m=description(protocol,get_sel(selectors[j]),1,1);
            if(!m.name)m=description(protocol,get_sel(selectors[j]),0,1);
            if(m.name)printf("METALABI selected_requirement protocol=%.80s selector=%.120s types=%.180s\n",
                protocols[i],selectors[j],m.types?m.types:"none");
        }
    }
    Obj (*create)(void)=dlsym(metal,"MTLCreateSystemDefaultDevice");
    printf("METALABI public_create_available=%u copy_all_available=%u\n",create!=0,
        dlsym(metal,"MTLCopyAllDevices")!=0);fflush((void *)0);
    if(!create)return 4;
    Obj device=create();
    printf("METALABI DEFAULT_DEVICE present=%u\n",device!=0);
    if(device){
        void *send=dlsym(objc,"objc_msgSend");
        Obj (*msg0)(Obj,Obj)=(void *)send;
        const char *(*string0)(Obj,Obj)=(void *)send;
        Obj name=msg0(device,get_sel("name"));
        printf("METALABI device_name=%.160s\n",name?string0(name,get_sel("UTF8String")):"none");
        msg0(device,get_sel("release"));
    }
    printf("METALABI DONE real_public_device=%u runtime_methods_replaced=0\n",device!=0);
    fflush((void *)0);
    return device?0:42; /* Missing a real device is the baseline failure to implement. */
}
