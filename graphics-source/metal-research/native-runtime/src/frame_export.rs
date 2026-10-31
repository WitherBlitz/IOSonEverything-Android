// SPDX-License-Identifier: AGPL-3.0-or-later
//! Android host-only frame export. Resource leases are independent of submission.
//! The three AHB images never have CPU mappings. Source pixels move by GPU blit.
use crate::{frame_lease::{Leases,SLOTS}, limits::{Budget,Ticket}, GpuTexture};
use ash::vk;
use metal2vulkan_runtime::{CommandQueue,Device};
use std::{ffi::c_void,os::fd::{AsRawFd,FromRawFd,OwnedFd},ptr,sync::Arc};

type Result<T> = std::result::Result<T,String>;
#[repr(C)] #[derive(Default)]
struct AhbDesc { width:u32,height:u32,layers:u32,format:u32,usage:u64,stride:u32,rfu0:u32,rfu1:u64 }
#[cfg_attr(target_os="android",link(name="android"))] unsafe extern "C" {
    fn AHardwareBuffer_allocate(desc:*const AhbDesc,out:*mut *mut c_void)->i32;
    fn AHardwareBuffer_release(buffer:*mut c_void);
    fn AHardwareBuffer_describe(buffer:*const c_void,desc:*mut AhbDesc);
}
#[repr(C)] #[derive(Clone,Copy)]
pub struct Frame {pub version:u32,pub width:u32,pub height:u32,pub format:u32,
    pub token:u64,pub buffer:*mut c_void,pub ready_fd:i32,pub reserved:u32}
#[repr(C)] #[derive(Default)]
struct SyncInfo {name:[u8;32],status:i32,flags:u32,num_fences:u32,pad:u32,details:u64}
const SYNC_FILE_INFO:u32=0xc0383e04;
fn sync_ready(fd:i32)->Result<bool> {
    let mut info=SyncInfo::default();
    // Public Linux sync_file UAPI, _IOWR('>',4,struct sync_file_info), size56.
    if unsafe{libc::ioctl(fd,SYNC_FILE_INFO as _,&mut info)}<0{return Err("frame:not-a-sync-file".into());}
    if info.status<0{return Err("fatal:frame-consumer-gpu-error".into());}Ok(info.status>0)
}
enum Consumer {Done,Fence(OwnedFd)}
impl Consumer {fn ready(&self)->Result<bool>{match self {Self::Done=>Ok(true),Self::Fence(fd)=>sync_ready(fd.as_raw_fd())}}}

struct Slot {
    device:ash::Device,buffer:*mut c_void,image:vk::Image,memory:vk::DeviceMemory,
    pool:vk::CommandPool,command:vk::CommandBuffer,fence:vk::Fence,signal:vk::Semaphore,
    width:u32,height:u32,initialized:bool,submitted:bool,consumer:Option<Consumer>,
    source:Option<GpuTexture>,_tickets:[Option<Arc<Ticket>>;2],
}
impl Drop for Slot {
    fn drop(&mut self){unsafe{
        // Owner only drops idle/drained slots; submitted or leased slots keep
        // their entire Context alive on close rather than freeing GPU storage.
        if self.signal!=vk::Semaphore::null(){self.device.destroy_semaphore(self.signal,None);}
        if self.fence!=vk::Fence::null(){self.device.destroy_fence(self.fence,None);}
        if self.pool!=vk::CommandPool::null(){self.device.destroy_command_pool(self.pool,None);}
        if self.image!=vk::Image::null(){self.device.destroy_image(self.image,None);}
        if self.memory!=vk::DeviceMemory::null(){self.device.free_memory(self.memory,None);}
        if !self.buffer.is_null(){AHardwareBuffer_release(self.buffer);}
    }}
}
fn vkerr(error:vk::Result)->String{format!("fatal:frame-vulkan:{error:?}")}
unsafe fn barrier(device:&ash::Device,command:vk::CommandBuffer,image:vk::Image,
    layouts:(vk::ImageLayout,vk::ImageLayout),families:(u32,u32),access:(vk::AccessFlags,vk::AccessFlags)) {
    let b=vk::ImageMemoryBarrier::default().image(image).old_layout(layouts.0).new_layout(layouts.1)
        .src_queue_family_index(families.0).dst_queue_family_index(families.1)
        .src_access_mask(access.0).dst_access_mask(access.1)
        .subresource_range(vk::ImageSubresourceRange::default().aspect_mask(vk::ImageAspectFlags::COLOR).level_count(1).layer_count(1));
    device.cmd_pipeline_barrier(command,vk::PipelineStageFlags::ALL_COMMANDS,vk::PipelineStageFlags::ALL_COMMANDS,
        vk::DependencyFlags::empty(),&[],&[],&[b]);
}
impl Slot {
    unsafe fn new(runtime:&Device,budget:&Budget,width:u32,height:u32)->Result<Self>{
        let raw=runtime.raw();
        if raw.queue_families.len()!=1{return Err("unsupported:frame-multiple-queue-families".into());}
        let usage=vk::ImageUsageFlags::SAMPLED|vk::ImageUsageFlags::COLOR_ATTACHMENT|vk::ImageUsageFlags::TRANSFER_DST;
        if !raw.instance.get_physical_device_format_properties(raw.physical_device,vk::Format::R8G8B8A8_UNORM).optimal_tiling_features.contains(vk::FormatFeatureFlags::BLIT_DST){return Err("unsupported:frame-blit-destination".into());}
        let mut external_info=vk::PhysicalDeviceExternalImageFormatInfo::default().handle_type(vk::ExternalMemoryHandleTypeFlags::ANDROID_HARDWARE_BUFFER_ANDROID);
        let info=vk::PhysicalDeviceImageFormatInfo2::default().push_next(&mut external_info).format(vk::Format::R8G8B8A8_UNORM).ty(vk::ImageType::TYPE_2D).tiling(vk::ImageTiling::OPTIMAL).usage(usage);
        let mut external_props=vk::ExternalImageFormatProperties::default();
        let importable={let mut props=vk::ImageFormatProperties2::default().push_next(&mut external_props);
            raw.instance.get_physical_device_image_format_properties2(raw.physical_device,&info,&mut props).map_err(vkerr)?;
            width<=props.image_format_properties.max_extent.width&&height<=props.image_format_properties.max_extent.height};
        if !importable||!external_props.external_memory_properties.external_memory_features.contains(vk::ExternalMemoryFeatureFlags::IMPORTABLE){return Err("unsupported:frame-ahb-image-import".into());}
        let estimated=u64::from(width)*u64::from(height)*4;
        let initial_ticket=budget.reserve(estimated)?;
        let mut s=Self {device:raw.device.clone(),buffer:ptr::null_mut(),image:vk::Image::null(),memory:vk::DeviceMemory::null(),
            pool:vk::CommandPool::null(),command:vk::CommandBuffer::null(),fence:vk::Fence::null(),signal:vk::Semaphore::null(),
            width,height,initialized:false,submitted:false,consumer:None,source:None,_tickets:[Some(initial_ticket),None]};
        let desc=AhbDesc{width,height,layers:1,format:1,usage:(1<<8)|(1<<9),..AhbDesc::default()};
        if AHardwareBuffer_allocate(&desc,&mut s.buffer)!=0||s.buffer.is_null(){return Err("frame:ahb-allocation".into());}
        let mut actual=AhbDesc::default();AHardwareBuffer_describe(s.buffer,&mut actual);
        if actual.width!=width||actual.height!=height||actual.layers!=1||actual.format!=1||actual.stride<width||actual.usage&desc.usage!=desc.usage{return Err("frame:ahb-layout".into());}
        let external=ash::android::external_memory_android_hardware_buffer::Device::new(raw.instance,raw.device);
        let mut format=vk::AndroidHardwareBufferFormatPropertiesANDROID::default();
        let (allocation_size,memory_type_bits)={let mut props=vk::AndroidHardwareBufferPropertiesANDROID::default().push_next(&mut format);
            external.get_android_hardware_buffer_properties(s.buffer.cast(),&mut props).map_err(vkerr)?;
            (props.allocation_size,props.memory_type_bits)};
        if format.format!=vk::Format::R8G8B8A8_UNORM{return Err("unsupported:frame-ahb-format".into());}
        if allocation_size>32*1024*1024{return Err("quota:single-resource".into());}
        // Gralloc's padding is known only after allocation. Reserve the texels
        // first, then charge any additional driver storage before importing it.
        if allocation_size>estimated{s._tickets[1]=Some(budget.reserve(allocation_size-estimated)?);}
        let mut ext=vk::ExternalMemoryImageCreateInfo::default().handle_types(vk::ExternalMemoryHandleTypeFlags::ANDROID_HARDWARE_BUFFER_ANDROID);
        let ci=vk::ImageCreateInfo::default().push_next(&mut ext).image_type(vk::ImageType::TYPE_2D).format(format.format)
            .extent(vk::Extent3D{width,height,depth:1}).mip_levels(1).array_layers(1).samples(vk::SampleCountFlags::TYPE_1)
            .tiling(vk::ImageTiling::OPTIMAL).usage(usage)
            .sharing_mode(vk::SharingMode::EXCLUSIVE).initial_layout(vk::ImageLayout::UNDEFINED);
        s.image=s.device.create_image(&ci,None).map_err(vkerr)?;
        let memory_type=memory_type_bits.trailing_zeros();if memory_type>=32{return Err("frame:memory-type".into());}
        let mut import=vk::ImportAndroidHardwareBufferInfoANDROID::default().buffer(s.buffer.cast());
        let mut dedicated=vk::MemoryDedicatedAllocateInfo::default().image(s.image);
        s.memory=s.device.allocate_memory(&vk::MemoryAllocateInfo::default().allocation_size(allocation_size).memory_type_index(memory_type).push_next(&mut import).push_next(&mut dedicated),None).map_err(vkerr)?;
        s.device.bind_image_memory(s.image,s.memory,0).map_err(vkerr)?;
        s.pool=s.device.create_command_pool(&vk::CommandPoolCreateInfo::default().queue_family_index(raw.queue_family).flags(vk::CommandPoolCreateFlags::RESET_COMMAND_BUFFER),None).map_err(vkerr)?;
        s.command=s.device.allocate_command_buffers(&vk::CommandBufferAllocateInfo::default().command_pool(s.pool).level(vk::CommandBufferLevel::PRIMARY).command_buffer_count(1)).map_err(vkerr)?[0];
        s.fence=s.device.create_fence(&vk::FenceCreateInfo::default(),None).map_err(vkerr)?;
        let mut export=vk::ExportSemaphoreCreateInfo::default().handle_types(vk::ExternalSemaphoreHandleTypeFlags::SYNC_FD);
        s.signal=s.device.create_semaphore(&vk::SemaphoreCreateInfo::default().push_next(&mut export),None).map_err(vkerr)?;
        Ok(s)
    }
    unsafe fn submit(&mut self,runtime:&Device,queue:&CommandQueue,texture:GpuTexture)->Result<i32>{
        let source=texture.value.vk_image().ok_or("unsupported:frame-shadow-texture")?;
        let raw=runtime.raw();let format=match texture.value.pixel_format().as_raw(){70=>vk::Format::R8G8B8A8_UNORM,80=>vk::Format::B8G8R8A8_UNORM,_=>return Err("unsupported:frame-source-format".into())};
        if !raw.instance.get_physical_device_format_properties(raw.physical_device,format).optimal_tiling_features.contains(vk::FormatFeatureFlags::BLIT_SRC){return Err("unsupported:frame-blit-source".into());}
        self.device.reset_command_buffer(self.command,vk::CommandBufferResetFlags::empty()).map_err(vkerr)?;
        self.device.reset_fences(&[self.fence]).map_err(vkerr)?;
        self.device.begin_command_buffer(self.command,&vk::CommandBufferBeginInfo::default().flags(vk::CommandBufferUsageFlags::ONE_TIME_SUBMIT)).map_err(vkerr)?;
        let ignored=(vk::QUEUE_FAMILY_IGNORED,vk::QUEUE_FAMILY_IGNORED);
        barrier(&self.device,self.command,source,(vk::ImageLayout::GENERAL,vk::ImageLayout::TRANSFER_SRC_OPTIMAL),ignored,(vk::AccessFlags::MEMORY_WRITE,vk::AccessFlags::TRANSFER_READ));
        barrier(&self.device,self.command,self.image,(if self.initialized{vk::ImageLayout::GENERAL}else{vk::ImageLayout::UNDEFINED},vk::ImageLayout::TRANSFER_DST_OPTIMAL),
            if self.initialized{(vk::QUEUE_FAMILY_FOREIGN_EXT,raw.queue_family)}else{ignored},(vk::AccessFlags::empty(),vk::AccessFlags::TRANSFER_WRITE));
        let layers=vk::ImageSubresourceLayers::default().aspect_mask(vk::ImageAspectFlags::COLOR).layer_count(1);
        let offsets=[vk::Offset3D::default(),vk::Offset3D{x:self.width as i32,y:self.height as i32,z:1}];
        let blit=vk::ImageBlit::default().src_subresource(layers).dst_subresource(layers).src_offsets(offsets).dst_offsets(offsets);
        self.device.cmd_blit_image(self.command,source,vk::ImageLayout::TRANSFER_SRC_OPTIMAL,self.image,vk::ImageLayout::TRANSFER_DST_OPTIMAL,&[blit],vk::Filter::NEAREST);
        barrier(&self.device,self.command,source,(vk::ImageLayout::TRANSFER_SRC_OPTIMAL,vk::ImageLayout::GENERAL),ignored,(vk::AccessFlags::TRANSFER_READ,vk::AccessFlags::MEMORY_READ|vk::AccessFlags::MEMORY_WRITE));
        barrier(&self.device,self.command,self.image,(vk::ImageLayout::TRANSFER_DST_OPTIMAL,vk::ImageLayout::GENERAL),(raw.queue_family,vk::QUEUE_FAMILY_FOREIGN_EXT),(vk::AccessFlags::TRANSFER_WRITE,vk::AccessFlags::empty()));
        self.device.end_command_buffer(self.command).map_err(vkerr)?;
        self.source=Some(texture);
        // A failed submission can leave device work indeterminate. Preserve the
        // slot/context until worker teardown on every submission failure.
        self.submitted=true;
        queue.with_vk_queue(|q,family|{if family!=raw.queue_family{return Err(vk::Result::ERROR_UNKNOWN);}
            let commands=[self.command];let signals=[self.signal];let submit=vk::SubmitInfo::default().command_buffers(&commands).signal_semaphores(&signals);
            self.device.queue_submit(q,&[submit],self.fence)}).map_err(vkerr)?;
        self.initialized=true;
        let external=ash::khr::external_semaphore_fd::Device::new(raw.instance,raw.device);
        external.get_semaphore_fd(&vk::SemaphoreGetFdInfoKHR::default().semaphore(self.signal).handle_type(vk::ExternalSemaphoreHandleTypeFlags::SYNC_FD)).map_err(vkerr)
    }
}

pub struct Frames {runtime:Device,queue:CommandQueue,leases:Leases,slots:[Option<Slot>;SLOTS],pub allocations:u64,pub exports:u64,pub collected:u64}
impl Drop for Frames {fn drop(&mut self){for slot in &mut self.slots{drop(slot.take());}}}
impl Frames {
    pub fn new(runtime:Device,epoch:u32)->Result<Self>{
        let queue=runtime.new_command_queue().map_err(|e|e.to_string())?;
        Ok(Self{runtime,queue,leases:Leases::new(epoch),slots:std::array::from_fn(|_|None),allocations:0,exports:0,collected:0})
    }
    pub fn collect(&mut self)->Result<bool>{
        for (index,slot) in self.slots.iter_mut().enumerate(){if let Some(s)=slot {
            if let Some(consumer)=&s.consumer {
                let producer=unsafe{s.device.get_fence_status(s.fence)}.map_err(vkerr)?;
                if self.leases.collect(index,producer,consumer.ready()?){s.source=None;s.consumer=None;s.submitted=false;self.collected+=1;}
            }
        }}Ok(self.leases.all_idle())
    }
    pub fn before_runtime_access(&mut self)->Result<()> {
        for slot in self.slots.iter_mut().flatten(){
            if slot.submitted&&slot.source.is_some(){
                unsafe{slot.device.wait_for_fences(&[slot.fence],true,8_000_000_000)}.map_err(vkerr)?;
                slot.source=None;
            }
        }Ok(())
    }
    pub fn has_prepared(&self)->bool{self.leases.has_reserved()}
    pub fn prepare(&mut self,budget:&Budget,source:GpuTexture)->Result<Frame>{
        self.collect()?;let width=u32::try_from(source.value.width()).map_err(|_|"frame:width")?;
        let height=u32::try_from(source.value.height()).map_err(|_|"frame:height")?;
        if width==0||height==0||u64::from(width)*u64::from(height)*4>32*1024*1024{return Err("frame:dimensions".into());}
        if !matches!(source.value.pixel_format().as_raw(),70|80){return Err("unsupported:frame-source-format".into());}
        let (index,token)=self.leases.reserve().map_err(str::to_owned)?;
        let result=(||{
            if self.slots[index].as_ref().is_some_and(|s|s.width!=width||s.height!=height){self.slots[index]=None;}
            if self.slots[index].is_none(){self.slots[index]=Some(unsafe{Slot::new(&self.runtime,budget,width,height)}?);self.allocations+=1;}
            let slot=self.slots[index].as_mut().unwrap();slot.source=Some(source);
            Ok(Frame{version:1,width,height,format:70,token,buffer:slot.buffer,ready_fd:-1,reserved:0})
        })();
        if result.is_err()&&!self.slots[index].as_ref().is_some_and(|s|s.submitted){self.leases.abort(index,token).map_err(str::to_owned)?;}
        result
    }
    pub fn submit(&mut self,token:u64)->Result<i32>{
        let index=self.leases.reserved(token).map_err(str::to_owned)?;
        let slot=self.slots[index].as_mut().unwrap();let source=slot.source.take().ok_or("fatal:frame-missing-prepared-source")?;
        match unsafe{slot.submit(&self.runtime,&self.queue,source)}{
            Ok(fd)=>{self.leases.publish(index,token).map_err(str::to_owned)?;self.exports+=1;Ok(fd)},
            Err(error)=>{if !slot.submitted{self.leases.abort(index,token).map_err(str::to_owned)?;}Err(error)}
        }
    }
    pub fn cancel(&mut self,token:u64)->Result<()>{
        let index=self.leases.reserved(token).map_err(str::to_owned)?;self.leases.abort(index,token).map_err(str::to_owned)?;
        self.slots[index].as_mut().unwrap().source=None;Ok(())
    }
    pub fn export(&mut self,budget:&Budget,source:GpuTexture)->Result<Frame>{
        let mut frame=self.prepare(budget,source)?;frame.ready_fd=self.submit(frame.token)?;Ok(frame)
    }
    pub fn returned(&mut self,token:u64,fd:i32)->Result<()> {
        if fd < -1{return Err("frame:invalid-consumer-fd".into());}
        if fd>=0{sync_ready(fd)?;}
        let index=self.leases.returned(token).map_err(str::to_owned)?;
        self.slots[index].as_mut().unwrap().consumer=Some(if fd==-1{Consumer::Done}else{Consumer::Fence(unsafe{OwnedFd::from_raw_fd(fd)})});
        Ok(())
    }
    pub fn all_idle(&self)->bool{self.leases.all_idle()}
}
