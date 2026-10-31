/* Authored visible-workload timing; no display-fence claim. AGPL-3.0-or-later. */
#ifndef IOSMETAL_FRAME_TIMING_H
#define IOSMETAL_FRAME_TIMING_H
#include <math.h>
typedef struct {double queue_ms,encode_ms,submit_ms,main_ms,total_ms;int valid;} IOSMetalFrameTiming;
static inline IOSMetalFrameTiming iosmetal_frame_timing(double start,double worker,double submit,double ready,double main){
 double stamps[]={start,worker,submit,ready,main};
 for(unsigned i=0;i<5;i++)if(!isfinite(stamps[i])||(i&&stamps[i]<stamps[i-1]))return (IOSMetalFrameTiming){0};
 IOSMetalFrameTiming result={(worker-start)*1000,(submit-worker)*1000,(ready-submit)*1000,(main-ready)*1000,(main-start)*1000,1};
 if(!isfinite(result.total_ms))return (IOSMetalFrameTiming){0};
 return result;
}
#endif
