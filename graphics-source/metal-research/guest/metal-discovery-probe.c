/* Authored, read-only Metal discovery prerequisites. No Apple implementation code.
 * SDK-free declarations keep this diagnostic separate from any private headers.
 * This process reads at most 16 IOAcceleratorES services; it changes no properties,
 * invokes no device factory or private registration function, and prints no blobs.
 */
typedef void *CFRef;
typedef unsigned long CFTypeID;
typedef unsigned int IOPort;
typedef unsigned long long RegistryID;
typedef unsigned char CFBoolean;

extern void *dlopen(const char *, int);
extern void *dlsym(void *, const char *);
extern int printf(const char *, ...);
extern int fflush(void *);
extern unsigned int alarm(unsigned int);

struct cf_api {
    CFRef (*string_create)(CFRef, const char *, unsigned int);
    CFTypeID (*type_id)(CFRef);
    CFTypeID (*string_type_id)(void);
    CFBoolean (*string_cstring)(CFRef, char *, long, unsigned int);
    void (*release)(CFRef);
};

/* Fixed one-byte replacements keep each log value on one bounded ASCII line. */
static void sanitize(char *text, unsigned int capacity) {
    unsigned int i;
    for (i = 0; i + 1 < capacity && text[i]; ++i) {
        unsigned char byte = (unsigned char)text[i];
        if (byte < 32 || byte > 126) text[i] = '?';
    }
    text[capacity - 1] = 0;
}

static void show_property(const struct cf_api *cf,
                         CFRef (*property)(IOPort, CFRef, CFRef, unsigned int),
                         IOPort service, unsigned int ordinal, const char *name) {
    CFRef key = cf->string_create((CFRef)0, name, 0x08000100u);
    if (!key) {
        printf("METALDISC service=%u key=%s state=key-allocation-failed\n", ordinal, name);
        return;
    }
    CFRef value = property(service, key, (CFRef)0, 0);
    cf->release(key);
    if (!value) {
        printf("METALDISC service=%u key=%s state=absent\n", ordinal, name);
        return;
    }
    if (cf->type_id(value) != cf->string_type_id()) {
        printf("METALDISC service=%u key=%s state=not-string\n", ordinal, name);
    } else {
        char text[257] = {0};
        if (cf->string_cstring(value, text, (long)sizeof(text), 0x08000100u)) {
            sanitize(text, (unsigned int)sizeof(text));
            printf("METALDISC service=%u key=%s state=string value=%.256s\n",
                   ordinal, name, text);
        } else {
            printf("METALDISC service=%u key=%s state=utf8-unrepresentable-or-over-256-bytes\n",
                   ordinal, name);
        }
    }
    cf->release(value);
}

int main(void) {
    /* External runner should still supervise the process. stdout can contend with
     * other guest clients, so the entire diagnostic has a finite process alarm. */
    alarm(15);
    void *cf_library = dlopen("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation", 2);
    void *io_library = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", 2);
    void *metal_library = dlopen("/System/Library/Frameworks/Metal.framework/Metal", 2);
    printf("METALDISC v1 cf_available=%u iokit_available=%u metal_available=%u max_services=16 max_string_bytes=256\n",
           cf_library != 0, io_library != 0, metal_library != 0);

    /* Symbol availability was recorded in recovery. The normal-boot run stalled
     * while resolving the first absent optional symbol, before registry reads.
     * Keep this independent diagnostic focused on the public registry APIs. */
    if (!cf_library || !io_library) {
        printf("METALDISC DONE status=missing-framework services=0 runtime_methods_replaced=0 registry_properties_written=0\n");
        fflush((void *)0);
        return 2;
    }

    struct cf_api cf;
    cf.string_create = (CFRef (*)(CFRef, const char *, unsigned int))dlsym(cf_library, "CFStringCreateWithCString");
    cf.type_id = (CFTypeID (*)(CFRef))dlsym(cf_library, "CFGetTypeID");
    cf.string_type_id = (CFTypeID (*)(void))dlsym(cf_library, "CFStringGetTypeID");
    cf.string_cstring = (CFBoolean (*)(CFRef, char *, long, unsigned int))dlsym(cf_library, "CFStringGetCString");
    cf.release = (void (*)(CFRef))dlsym(cf_library, "CFRelease");
    CFRef (*matching)(const char *) = (CFRef (*)(const char *))dlsym(io_library, "IOServiceMatching");
    int (*matching_services)(IOPort, CFRef, IOPort *) =
        (int (*)(IOPort, CFRef, IOPort *))dlsym(io_library, "IOServiceGetMatchingServices");
    IOPort (*next_service)(IOPort) = (IOPort (*)(IOPort))dlsym(io_library, "IOIteratorNext");
    int (*object_release)(IOPort) = (int (*)(IOPort))dlsym(io_library, "IOObjectRelease");
    CFRef (*property)(IOPort, CFRef, CFRef, unsigned int) =
        (CFRef (*)(IOPort, CFRef, CFRef, unsigned int))dlsym(io_library, "IORegistryEntryCreateCFProperty");
    int (*entry_id)(IOPort, RegistryID *) =
        (int (*)(IOPort, RegistryID *))dlsym(io_library, "IORegistryEntryGetRegistryEntryID");
    if (!cf.string_create || !cf.type_id || !cf.string_type_id || !cf.string_cstring ||
        !cf.release || !matching || !matching_services || !next_service || !object_release || !property) {
        printf("METALDISC DONE status=missing-read-api services=0 runtime_methods_replaced=0 registry_properties_written=0\n");
        fflush((void *)0);
        return 3;
    }
    CFRef dictionary = matching("IOAcceleratorES");
    if (!dictionary) {
        printf("METALDISC DONE status=matching-allocation-failed services=0 runtime_methods_replaced=0 registry_properties_written=0\n");
        fflush((void *)0);
        return 4;
    }
    IOPort iterator = 0;
    /* IOServiceGetMatchingServices consumes the matching dictionary, even on error. */
    int result = matching_services(0, dictionary, &iterator);
    if (result || !iterator) {
        if (iterator) object_release(iterator);
        printf("METALDISC DONE status=matching-failed code=0x%x services=0 runtime_methods_replaced=0 registry_properties_written=0\n",
               (unsigned int)result);
        fflush((void *)0);
        return 5;
    }
    unsigned int count = 0, capped = 0;
    while (count < 16) {
        IOPort service = next_service(iterator);
        if (!service) break;
        ++count;
        RegistryID identity = 0;
        int identity_result = entry_id ? entry_id(service, &identity) : -1;
        printf("METALDISC service=%u registry_id_available=%u registry_id=0x%llx\n",
               count, identity_result == 0, identity_result == 0 ? identity : 0);
        show_property(&cf, property, service, count, "MetalPluginName");
        show_property(&cf, property, service, count, "MetalPluginClassName");
        object_release(service);
    }
    if (count == 16) {
        IOPort extra = next_service(iterator);
        if (extra) { capped = 1; object_release(extra); }
    }
    object_release(iterator);
    printf("METALDISC DONE status=ok services=%u additional_services=%u runtime_methods_replaced=0 registry_properties_written=0 private_registration_invocations=0\n",
           count, capped);
    fflush((void *)0);
    return 0;
}
