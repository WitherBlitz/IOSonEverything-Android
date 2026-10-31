// Authored registration helper for our own app only; permissions recorded by builder.
// API declarations cross-checked against Procursus uikittools-ng public source.
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>
#include <string.h>
#include <fcntl.h>
@interface LSApplicationWorkspace:NSObject
+ (instancetype)defaultWorkspace;
- (BOOL)registerApplication:(NSURL *)url;
- (BOOL)registerApplicationDictionary:(NSDictionary *)information;
- (BOOL)openApplicationWithBundleID:(NSString *)identifier;
@end
@interface IOSMetalApplicationState:NSObject
- (BOOL)isValid;
@end
@interface LSApplicationProxy:NSObject
+ (instancetype)applicationProxyForIdentifier:(NSString *)identifier;
- (IOSMetalApplicationState *)appState;
- (NSURL *)bundleURL;
- (NSURL *)containerURL;
@end
@interface MCMAppDataContainer:NSObject
+ (instancetype)containerWithIdentifier:(NSString *)identifier createIfNecessary:(BOOL)create existed:(BOOL *)existed error:(NSError **)error;
- (NSURL *)url;
@end
int main(int argc,char **argv){write(1,"METAL_VISIBLE_STAGE main\n",25);alarm(180);
 NSString *observedHome=nil;
 BOOL registrationOnly=argc==4&&!strcmp(argv[1],"--log-home")&&!strcmp(argv[3],"--register-only");
 if((argc==3||registrationOnly)&&!strcmp(argv[1],"--log-home")){
  observedHome=[NSString stringWithUTF8String:argv[2]];
  if(![[observedHome stringByDeletingLastPathComponent]isEqual:@"/var/mobile/Containers/Data/Application"]||![[NSUUID alloc]initWithUUIDString:observedHome.lastPathComponent]){
   puts("METAL_VISIBLE_RESULT registered=false reason=invalid-owned-home-argument");fflush(NULL);return 22;
  }
 }
 if(argc==2&&!strcmp(argv[1],"--mobile")){
  if(setgid(501)||setuid(501)){printf("METAL_VISIBLE_RESULT registered=false reason=user-drop errno=%d\n",errno);fflush(NULL);return 21;}
 }
 printf("METAL_VISIBLE_IDENTITY uid=%u euid=%u gid=%u\n",getuid(),geteuid(),getgid());fflush(NULL);
 @autoreleasepool{
 dlopen("/System/Library/Frameworks/MobileCoreServices.framework/MobileCoreServices",RTLD_NOW|RTLD_LOCAL);
 Class workspaceClass=NSClassFromString(@"LSApplicationWorkspace"),proxyClass=NSClassFromString(@"LSApplicationProxy");
 if(!workspaceClass||!proxyClass){puts("METAL_VISIBLE_RESULT registered=false reason=launchservices-unavailable");fflush(NULL);return 16;}
 NSString *identifier=@"io.github.iosvm.metalvisible",*path=@"/Applications/IOSMetalVisible.app";NSURL *url=[NSURL fileURLWithPath:path];
 LSApplicationWorkspace *workspace=[workspaceClass defaultWorkspace];LSApplicationProxy *before=[proxyClass applicationProxyForIdentifier:identifier];
 NSError *containerError=nil;BOOL existed=NO;
 dlopen("/System/Library/PrivateFrameworks/MobileContainerManager.framework/MobileContainerManager",RTLD_NOW|RTLD_LOCAL);
 MCMAppDataContainer *container=[NSClassFromString(@"MCMAppDataContainer") containerWithIdentifier:identifier createIfNecessary:YES existed:&existed error:&containerError];
 printf("METAL_VISIBLE_CONTAINER available=%u error=%.240s\n",container.url!=nil,containerError.description.UTF8String?:"none");fflush(NULL);
 BOOL valid=[[before appState]isValid]&&[[before bundleURL].path isEqual:path];BOOL registered=valid;
 if(!valid){
  // Supply our actual owned path, identifier and container. No claimed Apple signer.
  NSMutableDictionary *information=[@{@"ApplicationType":@"System",@"CFBundleIdentifier":identifier,@"CodeInfoIdentifier":identifier,@"Path":path,@"IsContainerized":@YES,@"IsAdHocSigned":@YES,@"LSInstallType":@1,@"CompatibilityState":@0,@"IsDeletable":@NO} mutableCopy];
  if(container.url){NSString *home=container.url.path;information[@"Container"]=home;information[@"EnvironmentVariables"]=@{@"HOME":home,@"CFFIXED_USER_HOME":home,@"TMPDIR":[home stringByAppendingPathComponent:@"tmp"]};registered=[workspace registerApplicationDictionary:information];}
  else registered=[workspace registerApplication:url];
 }
 LSApplicationProxy *proxy=[proxyClass applicationProxyForIdentifier:identifier];valid=[[proxy appState]isValid]&&[[proxy bundleURL].path isEqual:path];
 printf("METAL_VISIBLE_REGISTER accepted=%u valid=%u owned_path=%u\n",registered,valid,[[proxy bundleURL].path isEqual:path]);fflush(NULL);
 if(!registered||!valid){puts("METAL_VISIBLE_RESULT registered=false reason=registration-not-accepted");fflush(NULL);return 17;}
 if(registrationOnly){puts("METAL_VISIBLE_RESULT registered=true registration_only=true auto_open=false");fflush(NULL);return 0;}
 NSString *home=[[proxy containerURL]path]?:@"/var/mobile";NSString *log=[home stringByAppendingPathComponent:@"Library/Logs/IOSMetalVisible.log"];
 if(observedHome){log=[observedHome stringByAppendingPathComponent:@"Library/Logs/IOSMetalVisible.log"];puts("METAL_VISIBLE_LOG_SOURCE observed-authored-app-home");}
 // Inspect only our two explicit log locations. The app's actual home need not
 // equal the LaunchServices proxy container for a System application.
 for(NSString *candidate in @[log,@"/var/mobile/Library/Logs/IOSMetalVisible.log"]){
  struct stat state;errno=0;int found=stat(candidate.fileSystemRepresentation,&state),code=errno;
  printf("METAL_VISIBLE_LOG_CANDIDATE path=%s stat=%d errno=%d uid=%u gid=%u bytes=%lld helper_uid=%u\n",candidate.fileSystemRepresentation,found,code,found?0:state.st_uid,found?0:state.st_gid,found?0:(long long)state.st_size,getuid());
 }
 if(![[NSFileManager defaultManager]fileExistsAtPath:log]&&[[NSFileManager defaultManager]fileExistsAtPath:@"/var/mobile/Library/Logs/IOSMetalVisible.log"])log=@"/var/mobile/Library/Logs/IOSMetalVisible.log";
 printf("METAL_VISIBLE_LOG_PATH %s\n",log.fileSystemRepresentation);fflush(NULL);
 errno=0;int diagnosticFD=open(log.fileSystemRepresentation,O_RDONLY|O_NOFOLLOW),diagnosticError=errno;
 printf("METAL_VISIBLE_LOG_OPEN fd=%d errno=%d\n",diagnosticFD,diagnosticError);if(diagnosticFD>=0)close(diagnosticFD);fflush(NULL);
 NSFileHandle *previousFile=[NSFileHandle fileHandleForReadingAtPath:log];NSData *previous=[previousFile readDataOfLength:65536];[previousFile closeFile];if(previous.length){NSString *text=[[NSString alloc]initWithData:previous encoding:NSUTF8StringEncoding];printf("METAL_VISIBLE_PREVIOUS_DIAGNOSTIC\n%s\n",text.UTF8String?:"invalid-UTF8");fflush(NULL);}
 NSDictionary *attributes=[[NSFileManager defaultManager]attributesOfItemAtPath:log error:NULL];unsigned long long baseline=[attributes fileSize];
 if(baseline>1024*1024){puts("METAL_VISIBLE_RESULT registered=true frame_logged=false reason=diagnostic-log-bound");fflush(NULL);return 20;}
 BOOL opened=[workspace openApplicationWithBundleID:identifier];printf("METAL_VISIBLE_OPEN accepted=%u\n",opened);fflush(NULL);
 // The app's private log may be protected even from the launcher. Launch
 // acceptance is separate from observed rendering; images/touch are checked
 // externally. Do not add privileges or spend the deadline retrying EPERM.
 if(diagnosticFD<0&&diagnosticError==EPERM){
  printf("METAL_VISIBLE_RESULT registered=true opened=%s frame_logged=false reason=private-log-unavailable\n",opened?"true":"false");fflush(NULL);return opened?0:18;
 }
 for(unsigned i=0;i<240;i++){usleep(500000);errno=0;NSFileHandle *file=[NSFileHandle fileHandleForReadingAtPath:log];int fileError=errno;[file seekToFileOffset:baseline];NSData *fresh=[file readDataOfLength:65536];[file closeFile];NSString *text=[[NSString alloc]initWithData:fresh?:[NSData data] encoding:NSUTF8StringEncoding];if(i==0||i%20==0){struct stat state;int s=stat(log.fileSystemRepresentation,&state);printf("METAL_VISIBLE_LOG_POLL index=%u baseline=%llu open=%u errno=%d size=%lld fresh=%lu utf8=%u\n",i,baseline,file!=nil,fileError,s?-1:(long long)state.st_size,(unsigned long)fresh.length,text!=nil);fflush(NULL);}if([text containsString:@"METAL_VISIBLE_FRAME number="]&&[text containsString:@"METAL_VISIBLE_LIFECYCLE active"]){printf("METAL_VISIBLE_APP_LOG\n%s\n",text.UTF8String);printf("METAL_VISIBLE_RESULT registered=true opened=%s frame_logged=true\n",opened?"true":"false");fflush(NULL);return opened?0:18;}}
 printf("METAL_VISIBLE_RESULT registered=true opened=%s frame_logged=false\n",opened?"true":"false");fflush(NULL);return 19;
}}
