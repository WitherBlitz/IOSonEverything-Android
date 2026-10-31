// SPDX-License-Identifier: AGPL-3.0-or-later
//! Host-only adapter. All data arriving from the guest uses the versioned wire.
mod wire;
mod reply;
mod profile;
mod limits;
mod metallib_validation;
mod vertex_layout;
mod color_state;
mod batch;
mod frame_lease;
mod frame_export;
use wire::{Arena, Fault, Reader};
use limits::{Budget, Ticket, QueueLimit, QueueSlot};
use metal2vulkan::metal::{PixelFormat, PrimitiveType, TextureUsage, SamplerMinMagFilter, SamplerAddressMode};
use metal2vulkan::bind::SamplerDescriptor;
use metal2vulkan::pipeline::{ColorAttachmentDescriptor, RenderPipelineDescriptor, StageSource};
use metal2vulkan_runtime::{Buffer, ClearColor, CommandBuffer, CommandBufferStatus, CommandQueue,
 ComputeCommandEncoder, ComputePipelineState, Device, DeviceKind, DeviceOptions, Function,
 Library, LoadAction, Origin, PipelineOptions, Region, RenderCommandEncoder, RenderPassDescriptor,
 RenderPipelineState, ResourceOptions, Size, StoreAction, Texture, TextureDescriptor, SamplerState};
use std::{ffi::c_void, panic::{catch_unwind, AssertUnwindSafe}, path::PathBuf,
 ptr, sync::{Arc,atomic::{AtomicU32,Ordering}}, time::{Duration, Instant}};
const WAIT:Duration=Duration::from_secs(8);
type Result<T>=std::result::Result<T,String>;
fn fault(f:Fault)->String {format!("wire:{f:?}")}
fn pipeline_options()->PipelineOptions {let mut p=PipelineOptions::default();p.deadline=Some(Instant::now()+WAIT);p}
fn runtime<T>(r:std::result::Result<T,metal2vulkan_runtime::Error>)->Result<T>{r.map_err(|e|match e{
 metal2vulkan_runtime::Error::DeviceLost=>"fatal:device-lost".into(),_=>e.to_string()})}
#[derive(Clone)] struct GpuBuffer {value:Buffer,ticket:Arc<Ticket>}
#[derive(Clone)] struct GpuTexture {value:Texture,ticket:Arc<Ticket>}
#[derive(Clone)] struct GpuSampler {value:SamplerState,ticket:Arc<Ticket>}
#[derive(Clone)] struct GpuLibrary {value:Library,ticket:Arc<Ticket>}
#[derive(Clone)] struct GpuFunction {value:Function,ticket:Arc<Ticket>}
#[derive(Clone)] struct GpuComputePipeline {value:ComputePipelineState,ticket:Arc<Ticket>}
#[derive(Clone)] struct GpuRenderPipeline {value:RenderPipelineState,tickets:[Arc<Ticket>;2]}
#[derive(Clone)] struct Queue {value:CommandQueue,limit:QueueLimit}
struct Command {value:CommandBuffer,retained:Vec<Arc<Ticket>>,operations:u32,active_encoder:bool,slot:Option<QueueSlot>}
enum Object {
 Buffer(GpuBuffer),Texture(GpuTexture),Sampler(GpuSampler),Library(GpuLibrary),Function(GpuFunction),
 ComputePipeline(GpuComputePipeline),RenderPipeline(GpuRenderPipeline),
 Queue(Queue),Command(Command),
 ComputeEncoder{value:ComputeCommandEncoder,command:u64},
 RenderEncoder{value:RenderCommandEncoder,command:u64},
}
enum Readback {
 Buffer{value:GpuBuffer,offset:usize,count:usize},
 Texture{value:GpuTexture,region:Region,stride:u64,span:usize},
}
impl Readback {
 fn len(&self)->usize {match self{Self::Buffer{count,..}=>*count,Self::Texture{span,..}=>*span}}
 fn fill(&self,output:&mut [u8])->Result<()> {
  if output.len()!=self.len(){return Err("fatal:readback-output-span".into());}
  match self {
   Self::Buffer{value,offset,count}=>{
    let source=value.value.contents().ok_or("buffer:unmapped")?;
    // The validated retained buffer remains live; commits synchronously finish
    // before this read. The caller owns distinct bounded response storage.
    unsafe{ptr::copy_nonoverlapping(source.as_ptr().add(*offset),output.as_mut_ptr(),*count);}
    Ok(())
   },
   Self::Texture{value,region,stride,..}=>runtime(value.value.get_bytes(output,*stride,0,*region,0,0)),
  }
 }
}
enum Reply {Owned(Vec<u8>),Readback(Readback)}
pub struct Context {owner:u32,device:Device,objects:Arena<Object>,budget:Budget,next:u64,poisoned:bool,profile:Option<Box<profile::Profile>>,frames:Option<frame_export::Frames>}
impl Context {
 fn object(&self,id:u64)->Result<&Object>{self.objects.get(self.owner,id).map_err(fault)}
 fn object_mut(&mut self,id:u64)->Result<&mut Object>{self.objects.get_mut(self.owner,id).map_err(fault)}
 fn put(&mut self,object:Object)->Result<Vec<u8>> {Ok(self.objects.insert(object,0).map_err(fault)?.to_le_bytes().to_vec())}
 fn buffer(&self,id:u64)->Result<GpuBuffer>{match self.object(id)?{Object::Buffer(v)=>Ok(v.clone()),_=>Err("handle:expected-buffer".into())}}
 fn texture(&self,id:u64)->Result<GpuTexture>{match self.object(id)?{Object::Texture(v)=>Ok(v.clone()),_=>Err("handle:expected-texture".into())}}
 fn command(&self,id:u64)->Result<CommandBuffer>{match self.object(id)?{Object::Command(v)=>Ok(v.value.clone()),_=>Err("handle:expected-command".into())}}
 fn retain(&mut self,id:u64,ticket:Arc<Ticket>)->Result<()> {
  match self.object_mut(id)? {Object::Command(v)=>{
    if v.retained.len()>=4096{return Err("quota:command-resource-references".into());}
    if !v.retained.iter().any(|t|Arc::ptr_eq(t,&ticket)){v.retained.push(ticket);}Ok(())
  },_=>Err("handle:expected-command".into())}
 }
 fn operation(&mut self,id:u64)->Result<()> {match self.object_mut(id)?{
  Object::Command(v)=>{if v.operations>=4096{return Err("quota:command-operations".into());}v.operations+=1;Ok(())},
  _=>Err("handle:expected-command".into())}}
 fn active(&mut self,id:u64,active:bool)->Result<()> {match self.object_mut(id)?{
  Object::Command(v)=>{v.active_encoder=active;Ok(())},_=>Err("handle:expected-command".into())}}
 fn dispatch(&mut self,op:u32,body:&[u8])->Result<Vec<u8>> {
  let mut r=Reader::new(body);
  macro_rules! u32v {()=>{r.u32().map_err(fault)?};}
  macro_rules! u64v {()=>{r.u64().map_err(fault)?};}
  macro_rules! done {()=>{r.finish().map_err(fault)?};}
  macro_rules! id {()=>{u64v!()};}
  match op {
   1=>{done!();let mut b=Vec::new();b.extend(1u32.to_le_bytes()); // implemented wire revision
       b.extend((wire::MAX_RESOURCE).to_le_bytes());b.extend(self.device.name().as_bytes());Ok(b)}
   2=>{let length=u64v!();let options=u64v!();done!();
       if length==0||options!=0 {return Err("unsupported:buffer-options-or-empty".into());}
       let ticket=self.budget.reserve(length)?;
       let value=runtime(self.device.new_buffer(length,ResourceOptions::shared()))?;
       self.put(Object::Buffer(GpuBuffer{value,ticket}))}
   3=>{let id=id!();let offset=u64v!();let bytes=r.rest();let b=self.buffer(id)?;
       wire::region(b.value.length(),offset,bytes.len() as u64).map_err(fault)?;
       let dest=b.value.contents().ok_or("buffer:unmapped")?;
       // All commits wait to completion before any subsequent request can access contents.
       unsafe{ptr::copy_nonoverlapping(bytes.as_ptr(),dest.as_ptr().add(offset as usize),bytes.len());}Ok(Vec::new())}
   4=>{let id=id!();let offset=u64v!();let count=u32v!() as usize;done!();let b=self.buffer(id)?;
       wire::region(b.value.length(),offset,count as u64).map_err(fault)?;
       let data=b.value.contents().ok_or("buffer:unmapped")?;
       Ok(unsafe{std::slice::from_raw_parts(data.as_ptr().add(offset as usize),count)}.to_vec())}
   5=>{let kind=u32v!();let data=r.rest();if data.len()>wire::MAX_SHADER{return Err("quota:shader-bytes".into());}
       if kind==1 { metallib_validation::validate(data)?; }
       let ticket=self.budget.reserve(data.len() as u64)?;
       let library=match kind {1=>runtime(self.device.new_library_with_data(data))?,
        2=>{ // Explicit internal AIR entry, never silently accepted as public metallib.
         let parsed=metal2vulkan::library::Library::from_air(data).map_err(|e|e.to_string())?;
         self.device.new_library_with_compile_library(parsed)
        },_=>return Err("unsupported:library-container-kind".into())};
         if library.library_type()!=metal2vulkan::library::LibraryType::Executable{return Err("unsupported:dynamic-library".into());}
         self.put(Object::Library(GpuLibrary{value:library,ticket}))}
   6=>{let library=id!();let count=u32v!() as usize;
       if count==0||count>256{return Err("invalid:function-name-length".into());}
       let name=std::str::from_utf8(r.take(count).map_err(fault)?).map_err(|_|"invalid:function-name-utf8")?;done!();
       let f=match self.object(library)?{Object::Library(v)=>GpuFunction{value:runtime(v.value.new_function_with_name(name))?,ticket:v.ticket.clone()},_=>return Err("handle:expected-library".into())};
       let kind=runtime(f.value.function_type())?.as_raw();
       let mut data=self.put(Object::Function(f))?;data.extend(kind.to_le_bytes());Ok(data)}
   7=>{let id=id!();done!();let f=match self.object(id)?{Object::Function(v)=>v.clone(),_=>return Err("handle:expected-function".into())};
       let p=runtime(self.device.new_compute_pipeline_state_with_function(&f.value,&pipeline_options()))?;
       let width=p.thread_execution_width();let max=p.max_total_threads_per_threadgroup();let shared=p.static_threadgroup_memory_length();
       let mut b=self.put(Object::ComputePipeline(GpuComputePipeline{value:p,ticket:f.ticket}))?;for v in [width,max,shared]{b.extend(v.to_le_bytes());}Ok(b)}
   8=>{done!();let q=runtime(self.device.new_command_queue())?;self.put(Object::Queue(Queue{value:q,limit:QueueLimit::new()}))}
   9=>{let id=id!();done!();let (c,slot)=match self.object(id)?{Object::Queue(v)=>{let slot=v.limit.reserve()?;(runtime(v.value.command_buffer())?,slot)},_=>return Err("handle:expected-queue".into())};
       self.put(Object::Command(Command{value:c,retained:Vec::new(),operations:0,active_encoder:false,slot:Some(slot)}))}
   10=>{let id=id!();done!();let c=self.command(id)?;
       self.operation(id)?;
       let e=runtime(c.compute_command_encoder())?;self.active(id,true)?;self.put(Object::ComputeEncoder{value:e,command:id})}
   11=>{let encoder=id!();let state=id!();done!();let state=match self.object(state)?{Object::ComputePipeline(v)=>v.clone(),_=>return Err("handle:expected-compute-pipeline".into())};
       let command=match self.object(encoder)?{Object::ComputeEncoder{command,..}=>*command,_=>return Err("handle:expected-compute-encoder".into())};self.retain(command,state.ticket)?;
       self.operation(command)?;
       match self.object_mut(encoder)?{Object::ComputeEncoder{value,..}=>runtime(value.set_compute_pipeline_state(&state.value))?,_=>unreachable!()}Ok(Vec::new())}
   12=>{let encoder=id!();let buffer=id!();let offset=u64v!();let index=u32v!();let stage=u32v!();done!();
       if index>=wire::MAX_BINDINGS{return Err("quota:binding-index".into());}
       let b=self.buffer(buffer)?;wire::region(b.value.length(),offset,0).map_err(fault)?;
       let command=match self.object(encoder)?{Object::ComputeEncoder{command,..} if stage==0=>*command,
        Object::RenderEncoder{command,..} if stage==1||stage==2=>*command,_=>return Err("handle:encoder-stage-mismatch".into())};
       self.retain(command,b.ticket.clone())?;self.operation(command)?;
       match self.object_mut(encoder)?{
        Object::ComputeEncoder{value,..}=>runtime(value.set_buffer(Some(&b.value),offset,index))?,
        Object::RenderEncoder{value,..} if stage==1=>runtime(value.set_vertex_buffer(Some(&b.value),offset,index))?,
        Object::RenderEncoder{value,..}=>runtime(value.set_fragment_buffer(Some(&b.value),offset,index))?,_=>unreachable!()};Ok(Vec::new())}
   13=>{let encoder=id!();let threads=[u64v!(),u64v!(),u64v!()];let group=[u64v!(),u64v!(),u64v!()];let mode=u32v!();done!();
       if mode>1{return Err("unsupported:dispatch-mode".into());}
       wire::dispatch_grid(threads,group,mode==1).map_err(fault)?;
       let command=match self.object(encoder)?{Object::ComputeEncoder{command,..}=>*command,_=>return Err("handle:expected-compute-encoder".into())};
       self.operation(command)?;
       match self.object_mut(encoder)?{Object::ComputeEncoder{value,..}=>{
        let t=Size::new(threads[0],threads[1],threads[2]);let g=Size::new(group[0],group[1],group[2]);
        runtime(if mode==0 {value.dispatch_threads(t,g)} else {value.dispatch_threadgroups(t,g)})?
       },_=>unreachable!()};Ok(Vec::new())}
   14=>{let id=id!();done!();if !matches!(self.object(id)?,Object::ComputeEncoder{..}|Object::RenderEncoder{..}){return Err("handle:expected-encoder".into());}
       let e=self.objects.remove(self.owner,id).map_err(fault)?;
       match e{Object::ComputeEncoder{value,command}=>{self.active(command,false)?;runtime(value.end_encoding())?;},Object::RenderEncoder{value,command}=>{self.active(command,false)?;runtime(value.end_encoding())?;},_=>unreachable!()};Ok(Vec::new())}
   15=>{let id=id!();done!();let c=self.command(id)?;
       runtime(c.commit())?;
       if c.wait_until_completed_for(WAIT).is_err(){self.poisoned=true;return Err("fatal:gpu-wait-timeout".into());}
       if c.status()!=CommandBufferStatus::Completed{self.poisoned=true;return Err(format!("fatal:command-failed:{:?}",c.error()));}
       if let Object::Command(v)=self.object_mut(id)?{v.slot.take();}
       Ok(c.status().raw().to_le_bytes().to_vec())}
   16=>{let id=id!();done!();Ok(self.command(id)?.status().raw().to_le_bytes().to_vec())}
   17=>{let id=id!();done!();if matches!(self.object(id)?,Object::ComputeEncoder{..}|Object::RenderEncoder{..}){return Err("state:encoder-must-end-before-release".into());}
       if matches!(self.object(id)?,Object::Command(Command{active_encoder:true,..})){return Err("state:command-has-active-encoder".into());}
       self.objects.remove(self.owner,id).map_err(fault)?;Ok(Vec::new())}
   18=>{let format=u32v!();let width=u32v!() as u64;let height=u32v!() as u64;let usage=u32v!();done!();
       if width==0||height==0||width>8192||height>8192||usage&!7!=0{return Err("invalid:texture-shape-or-usage".into());}
       let format=pixel_format(format)?;let ticket=self.budget.reserve(width*height*4)?;
       let mut d=TextureDescriptor::texture_2d(format,width,height,false);
       d.usage=TextureUsage::default();if usage&1!=0{d.usage|=TextureUsage::SHADER_READ;}if usage&2!=0{d.usage|=TextureUsage::SHADER_WRITE;}if usage&4!=0{d.usage|=TextureUsage::RENDER_TARGET;}
       d.resource_options=ResourceOptions::shared();let value=runtime(self.device.new_texture(&d))?;
       self.put(Object::Texture(GpuTexture{value,ticket}))}
   19|20=>{let id=id!();let x=u32v!() as u64;let y=u32v!() as u64;let w=u32v!() as u64;let h=u32v!() as u64;let stride=u32v!() as u64;
       let tex=self.texture(id)?;
       if w==0||h==0||x>tex.value.width()||w>tex.value.width()-x||y>tex.value.height()||h>tex.value.height()-y||stride<w*4{return Err("invalid:texture-region".into());}
       let span=(h-1).checked_mul(stride).and_then(|v|v.checked_add(w*4)).filter(|v|*v<=wire::MAX_RESOURCE).ok_or("quota:texture-transfer")? as usize;
       let region=Region{origin:Origin::new(x,y,0),size:Size::new(w,h,1)};
       if op==19{let data=r.take(span).map_err(fault)?;done!();runtime(tex.value.replace_region(region,0,0,data,stride,0))?;Ok(Vec::new())}
       else {done!();let mut data=vec![0;span];runtime(tex.value.get_bytes(&mut data,stride,0,region,0,0))?;Ok(data)}}
   21|29|30=>{let vertex=id!();let fragment=id!();let format=u32v!();
       let vertex_descriptor=if op==29||op==30 {Some(vertex_layout::decode(&mut r)?)} else {None};
       let color=if op==30 {color_state::decode(&mut r,pixel_format(format)?)?} else {ColorAttachmentDescriptor::new(pixel_format(format)?)};done!();
       let v=match self.object(vertex)?{Object::Function(v)=>v.clone(),_=>return Err("handle:expected-vertex-function".into())};
       let f=match self.object(fragment)?{Object::Function(v)=>v.clone(),_=>return Err("handle:expected-fragment-function".into())};
       let mut d=RenderPipelineDescriptor::new(StageSource::Function(v.value.function_descriptor()));d.fragment=Some(StageSource::Function(f.value.function_descriptor()));
       d.vertex_descriptor=vertex_descriptor;
       d.color_attachments[0]=Some(color);
       let p=runtime(self.device.new_render_pipeline_state(&d,&pipeline_options()))?;self.put(Object::RenderPipeline(GpuRenderPipeline{value:p,tickets:[v.ticket,f.ticket]}))}
   22=>{let command=id!();let target=id!();let load=u32v!();let store=u32v!();let clear=[u64v!(),u64v!(),u64v!(),u64v!()];done!();
       let load=match load{0=>LoadAction::DontCare,1=>LoadAction::Load,2=>LoadAction::Clear,_=>return Err("invalid:load-action".into())};
       let store=match store{0=>StoreAction::DontCare,1=>StoreAction::Store,_=>return Err("unsupported:store-action".into())};
       let clear=clear.map(f64::from_bits);if !clear.iter().all(|v|v.is_finite()){return Err("invalid:clear-color".into());}
       let c=self.command(command)?;let t=self.texture(target)?;self.retain(command,t.ticket.clone())?;self.operation(command)?;
       let mut p=RenderPassDescriptor::new();p.color_attachments[0].texture=Some(t.value);p.color_attachments[0].load_action=load;p.color_attachments[0].store_action=store;
       p.color_attachments[0].clear_color=ClearColor::new(clear[0],clear[1],clear[2],clear[3]);
       let e=runtime(c.render_command_encoder(&p))?;self.active(command,true)?;self.put(Object::RenderEncoder{value:e,command})}
   23=>{let encoder=id!();let pipeline=id!();done!();let p=match self.object(pipeline)?{Object::RenderPipeline(v)=>v.clone(),_=>return Err("handle:expected-render-pipeline".into())};
       let command=match self.object(encoder)?{Object::RenderEncoder{command,..}=>*command,_=>return Err("handle:expected-render-encoder".into())};
       self.operation(command)?;
       for ticket in p.tickets{self.retain(command,ticket)?;}
       match self.object_mut(encoder)?{Object::RenderEncoder{value,..}=>runtime(value.set_render_pipeline_state(&p.value))?,_=>unreachable!()}Ok(Vec::new())}
   24=>{let encoder=id!();let primitive=u32v!();let start=u64v!();let count=u64v!();let instances=u64v!();let base=u64v!();done!();
       let primitive=match primitive{0=>PrimitiveType::Point,1=>PrimitiveType::Line,2=>PrimitiveType::LineStrip,3=>PrimitiveType::Triangle,4=>PrimitiveType::TriangleStrip,_=>return Err("invalid:primitive".into())};
       if count==0||instances==0||count.checked_mul(instances).is_none_or(|v|v>16*1024*1024)||start.checked_add(count).is_none()||base.checked_add(instances).is_none(){return Err("quota:draw-dimensions".into());}
       let command=match self.object(encoder)?{Object::RenderEncoder{command,..}=>*command,_=>return Err("handle:expected-render-encoder".into())};self.operation(command)?;
       let start=u32::try_from(start).map_err(|_|"invalid:vertex-start-width")?;
       let count=u32::try_from(count).map_err(|_|"invalid:vertex-count-width")?;
       let instances=u32::try_from(instances).map_err(|_|"invalid:instance-count-width")?;
       let base=u32::try_from(base).map_err(|_|"invalid:base-instance-width")?;
       match self.object_mut(encoder)?{Object::RenderEncoder{value,..}=>runtime(value.draw_primitives(primitive,start,count,instances,base))?,_=>unreachable!()}Ok(Vec::new())}
   25=>{let id=id!();done!();let names=match self.object(id)?{Object::Library(v)=>v.value.function_names(),_=>return Err("handle:expected-library".into())};
       if names.len()>4096{return Err("quota:library-function-count".into());}
       let mut data=Vec::new();data.extend((names.len() as u32).to_le_bytes());
       for name in names{if name.len()>4096{return Err("quota:function-name-bytes".into());}data.extend((name.len() as u32).to_le_bytes());data.extend(name.as_bytes());if data.len()>512*1024{return Err("quota:function-name-table".into());}}
       Ok(data)}
   26=>{let encoder=id!();let texture=id!();let index=u32v!();let stage=u32v!();done!();
       if index>=wire::MAX_BINDINGS{return Err("quota:texture-binding-index".into());}
       let command=match self.object(encoder)?{Object::ComputeEncoder{command,..} if stage==0=>*command,
        Object::RenderEncoder{command,..} if stage==1||stage==2=>*command,_=>return Err("handle:encoder-stage-mismatch".into())};
       let texture=if texture==0{None}else{Some(self.texture(texture)?)};
       if let Some(t)=&texture{self.retain(command,t.ticket.clone())?;}self.operation(command)?;
       let value=texture.as_ref().map(|t|&t.value);
       match self.object_mut(encoder)?{
        Object::ComputeEncoder{value:e,..}=>runtime(e.set_texture(value,index))?,
        Object::RenderEncoder{value:e,..} if stage==1=>runtime(e.set_vertex_texture(value,index))?,
        Object::RenderEncoder{value:e,..}=>runtime(e.set_fragment_texture(value,index))?,_=>unreachable!()};Ok(Vec::new())}
   27=>{let min=u32v!();let mag=u32v!();let s=u32v!();let t=u32v!();let z=u32v!();let normalized=u32v!();done!();
       if normalized!=1{return Err("unsupported:sampler-pixel-coordinates".into());}
       let filter=|v|match v{0=>Ok(SamplerMinMagFilter::Nearest),1=>Ok(SamplerMinMagFilter::Linear),_=>Err("unsupported:sampler-filter")};
       let address=|v|match v{0=>Ok(SamplerAddressMode::ClampToEdge),2=>Ok(SamplerAddressMode::Repeat),_=>Err("unsupported:sampler-address-mode")};
       let mut d=SamplerDescriptor::new();d.min_filter=filter(min)?;d.mag_filter=filter(mag)?;
       d.s_address_mode=address(s)?;d.t_address_mode=address(t)?;d.r_address_mode=address(z)?;
       let ticket=self.budget.reserve(256)?;let value=runtime(self.device.new_sampler_state(&d))?;
       self.put(Object::Sampler(GpuSampler{value,ticket}))}
   28=>{let encoder=id!();let sampler=id!();let index=u32v!();let stage=u32v!();done!();
       if index>=16{return Err("quota:sampler-binding-index".into());}
       let command=match self.object(encoder)?{Object::ComputeEncoder{command,..} if stage==0=>*command,
        Object::RenderEncoder{command,..} if stage==1||stage==2=>*command,_=>return Err("handle:encoder-stage-mismatch".into())};
       let sampler=if sampler==0{None}else{Some(match self.object(sampler)?{Object::Sampler(v)=>v.clone(),_=>return Err("handle:expected-sampler".into())})};
       if let Some(s)=&sampler{self.retain(command,s.ticket.clone())?;}self.operation(command)?;
       let value=sampler.as_ref().map(|s|&s.value);
       match self.object_mut(encoder)?{
        Object::ComputeEncoder{value:e,..}=>runtime(e.set_sampler_state(value,index))?,
        Object::RenderEncoder{value:e,..} if stage==1=>runtime(e.set_vertex_sampler_state(value,index))?,
        Object::RenderEncoder{value:e,..}=>runtime(e.set_fragment_sampler_state(value,index))?,_=>unreachable!()};Ok(Vec::new())}
   31=>{let encoder=id!();let color=[u32v!(),u32v!(),u32v!(),u32v!()].map(f32::from_bits);done!();
       if !color.iter().all(|v|v.is_finite()){return Err("invalid:blend-color-nonfinite".into());}
       let command=match self.object(encoder)?{Object::RenderEncoder{command,..}=>*command,_=>return Err("handle:expected-render-encoder".into())};
       self.operation(command)?;
       match self.object_mut(encoder)?{Object::RenderEncoder{value,..}=>value.set_blend_color(color[0],color[1],color[2],color[3]),_=>unreachable!()};Ok(Vec::new())}
   32=>{
       let entries=batch::decode(body).map_err(fault)?;let count=entries.len() as u32;
       for (index,entry) in entries.iter().enumerate(){
        match self.dispatch(entry.op,entry.body){
         Ok(reply) if reply.is_empty()=>{},
         other=>{self.poisoned=true;return Err(format!("fatal:batch-operation:{index}:{other:?}"));}
        }
       }
       Ok(count.to_le_bytes().to_vec())
   }
   33=>{done!();let mut value=Vec::with_capacity(16);for item in [1u32,1,batch::MAX_OPERATIONS as u32,batch::MAX_BYTES as u32]{value.extend(item.to_le_bytes());}Ok(value)}
   _=>Err(format!("unsupported:metal-operation:{op}")),
  }
 }
 fn readback(&self,op:u32,body:&[u8])->Result<Readback> {
  let mut r=Reader::new(body);
  let id=r.u64().map_err(fault)?;
  if op==4 {
   let offset=r.u64().map_err(fault)?;let count=r.u32().map_err(fault)? as usize;r.finish().map_err(fault)?;
   let value=self.buffer(id)?;wire::region(value.value.length(),offset,count as u64).map_err(fault)?;
   Ok(Readback::Buffer{value,offset:offset as usize,count})
  } else {
   let x=r.u32().map_err(fault)? as u64;let y=r.u32().map_err(fault)? as u64;
   let w=r.u32().map_err(fault)? as u64;let h=r.u32().map_err(fault)? as u64;let stride=r.u32().map_err(fault)? as u64;r.finish().map_err(fault)?;
   let value=self.texture(id)?;
   if w==0||h==0||x>value.value.width()||w>value.value.width()-x||y>value.value.height()||h>value.value.height()-y||stride<w*4{return Err("invalid:texture-region".into());}
   let span=(h-1).checked_mul(stride).and_then(|v|v.checked_add(w*4)).filter(|v|*v<=wire::MAX_RESOURCE).ok_or("quota:texture-transfer")? as usize;
   Ok(Readback::Texture{value,region:Region{origin:Origin::new(x,y,0),size:Size::new(w,h,1)},stride,span})
  }
 }
 fn request(&mut self,data:&[u8],capacity:usize)->Result<Reply> {
  let q=wire::decode(data).map_err(fault)?;
  if self.poisoned{return Err("fatal:context-poisoned".into());}
  if q.id!=self.next{return Err("state:request-sequence".into());}
  self.next=self.next.checked_add(1).ok_or("state:sequence-exhausted")?;
  // Check capacity before calls with side effects. Fixed replies are bounded;
  // larger reads derive an exact upper bound from the validated request fields.
  let needed=match q.op {
   4=>{let mut r=Reader::new(q.body);r.u64().map_err(fault)?;r.u64().map_err(fault)?;let n=r.u32().map_err(fault)? as usize;r.finish().map_err(fault)?;n},
   20=>{let mut r=Reader::new(q.body);r.u64().map_err(fault)?;r.u32().map_err(fault)?;r.u32().map_err(fault)?;let w=r.u32().map_err(fault)? as usize;let h=r.u32().map_err(fault)? as usize;let stride=r.u32().map_err(fault)? as usize;r.finish().map_err(fault)?;
     h.checked_sub(1).and_then(|v|v.checked_mul(stride)).and_then(|v|v.checked_add(w.checked_mul(4)?)).ok_or("invalid:read-span")?},
   1=>12+self.device.name().len(),6=>12,7=>20,25=>512*1024,32=>4,33=>16,
   2|5|8|9|10|15|16|18|21|22|27|29|30=>8,
   _=>0,
  };
  if needed.checked_add(24).is_none_or(|n|n>capacity){return Err("wire:reply-capacity".into());}
  if matches!(q.op,2|5|6|7|8|9|10|18|21|22|27|29|30){self.objects.ensure_slot().map_err(fault)?;}
  // Raw export reads are outside the runtime's resource tracker. A subsequent
  // runtime operation may mutate that image on another queue; producer fences,
  // not retained object lifetime, authorize access again.
  if self.frames.as_ref().is_some_and(|f|f.has_prepared()){return Err("state:frame-preparation-pending".into());}
  if !matches!(q.op,1|16|17|25|33){if let Some(frames)=&mut self.frames{frames.before_runtime_access()?;}}
  if q.op==4||q.op==20 {return self.readback(q.op,q.body).map(Reply::Readback);}
  self.dispatch(q.op,q.body).map(Reply::Owned)
 }
}
fn pixel_format(raw:u32)->Result<PixelFormat>{match raw{70=>Ok(PixelFormat::RGBA8Unorm),80=>Ok(PixelFormat::BGRA8Unorm),_=>Err(format!("unsupported:pixel-format:{raw}"))}}

/// Trusted-host ABI. Cache must be a private absolute path, supplied by worker.
#[no_mangle] pub unsafe extern "C" fn iosmetal_open(owner:u32,cache:*const u8,length:u32,error:*mut u8,error_capacity:u32)->*mut c_void {
 open_context(owner,cache,length,error,error_capacity,false)
}
/// Same serialized trusted-host contract as iosmetal_open, with explicit public
/// AHB/sync-fd/foreign-queue capabilities. Legacy opens do not enable them.
#[no_mangle] pub unsafe extern "C" fn iosmetal_open_shared_frames(owner:u32,cache:*const u8,length:u32,error:*mut u8,error_capacity:u32)->*mut c_void {
 open_context(owner,cache,length,error,error_capacity,true)
}
unsafe fn open_context(owner:u32,cache:*const u8,length:u32,error:*mut u8,error_capacity:u32,shared_frames:bool)->*mut c_void {
 static NEXT_EPOCH:AtomicU32=AtomicU32::new(1);
 let result=catch_unwind(AssertUnwindSafe(||->Result<Context>{
  if owner==0||cache.is_null()||length==0||length>4096{return Err("invalid:host-open-arguments".into());}
  let path=std::str::from_utf8(std::slice::from_raw_parts(cache,length as usize)).map_err(|_|"invalid:cache-path-utf8")?;
  if !path.starts_with('/')||path.as_bytes().contains(&0){return Err("invalid:cache-path".into());}
  let mut options=DeviceOptions::default();options.kinds=vec![DeviceKind::Integrated,DeviceKind::Discrete];
  if shared_frames{options.device_extensions=["VK_ANDROID_external_memory_android_hardware_buffer","VK_KHR_external_semaphore_fd","VK_EXT_queue_family_foreign"].into_iter().map(|s|std::ffi::CString::new(s).unwrap()).collect();}
  // Phone qualification explicitly requires the Vulkan1.4 loader measured by
  // the prerequisite probe. Core promoted commands must be requested at their
  // API level; lower-version portability needs separate capability validation.
  options.instance_api_version=Some(metal2vulkan::device::ApiVersion{major:1,minor:4});
  options.shader_cache.directory=Some(PathBuf::from(path));options.shader_cache.capacity=256*1024*1024;options.shader_cache.memory_capacity=32*1024*1024;
  let device=runtime(Device::system_default_with(&options))?;
  eprintln!("IOSMETAL_DEVICE hardware=true owner={owner} name={:?} wire=1",device.name());
  let frames=if shared_frames{
   let epoch=NEXT_EPOCH.fetch_update(Ordering::Relaxed,Ordering::Relaxed,|value|value.checked_add(1)).map_err(|_|"frame:epoch-exhausted")?;
   Some(frame_export::Frames::new(device.clone(),epoch)?)
  }else{None};
  Ok(Context{owner,device,objects:Arena::new(owner),budget:Budget::new(),next:1,poisoned:false,profile:profile::Profile::from_environment(owner),frames})
 }));
 match result{Ok(Ok(c))=>Box::into_raw(Box::new(c)).cast(),other=>{
  let text=match other{Ok(Err(e))=>e,_=>"fatal:panic-opening-device".into()};
  if !error.is_null()&&error_capacity>0{let n=text.len().min(error_capacity as usize-1);ptr::copy_nonoverlapping(text.as_ptr(),error,n);*error.add(n)=0;}
  ptr::null_mut()
 }}
}
/// Returns outer errno only for invalid trusted-host buffers; semantic errors
/// are an inner response. Poisoned context returns fatal outer EIO thereafter.
#[no_mangle] pub unsafe extern "C" fn iosmetal_call(context:*mut c_void,input:*const u8,size:u32,output:*mut u8,capacity:u32,written:*mut u32)->i64 {
 if written.is_null(){return -22;}*written=0;
 if context.is_null()||input.is_null()||output.is_null()||size as usize>wire::MAX_MESSAGE||capacity<24||capacity as usize>wire::MAX_MESSAGE{return -22;}
 let c=&mut *context.cast::<Context>();if c.poisoned{return -5;}
 let began=profile::begin(&c.profile);
 let data=std::slice::from_raw_parts(input,size as usize);let (sequence,op)=wire::decode(data).map(|q|(q.id,q.op)).unwrap_or((0,u32::MAX));
 let result=catch_unwind(AssertUnwindSafe(||->Result<usize>{
  let plan=c.request(data,capacity as usize)?;
  // C output may be uninitialized; the direct fill helper initializes only
  // its validated body span before borrowing bytes and publishes header last.
  let storage=std::slice::from_raw_parts_mut(output.cast::<std::mem::MaybeUninit<u8>>(),capacity as usize);
  let count=match plan {
   Reply::Owned(body)=>reply::write(0,sequence,&body,storage),
   Reply::Readback(read)=>reply::write_with(sequence,read.len(),storage,|bytes|read.fill(bytes))?,
  };
  count.ok_or_else(||"fatal:reply-framing-capacity".into())
 }));
 let (code,failed)=match result {
  Ok(Ok(count))=>{*written=count as u32;(0,false)},
  Ok(Err(error))=>{
   if error.starts_with("fatal:"){c.poisoned=true;}
   if c.poisoned {(if error=="fatal:reply-framing-capacity"{-71}else{-5},true)}
   else {
    let count=error.len().min(1024).min(capacity as usize-24);
    let storage=std::slice::from_raw_parts_mut(output.cast::<std::mem::MaybeUninit<u8>>(),capacity as usize);
    match reply::write(-1,sequence,&error.as_bytes()[..count],storage){
     Some(count)=>{*written=count as u32;(0,true)},None=>{c.poisoned=true;(-71,true)}
    }
   }
  },
  Err(_)=>{c.poisoned=true;(-5,true)},
 };
 profile::finish(&mut c.profile,began,op,size,*written,failed);
 code
}
/// Caller invokes only after calls stop. In-flight failures require process
/// termination by the supervisor rather than recovery/reusing live allocations.
#[no_mangle] pub unsafe extern "C" fn iosmetal_close(context:*mut c_void){
 if context.is_null(){return;}
 let mut context=Box::from_raw(context.cast::<Context>());
 if let Some(frames)=&mut context.frames {
  let end=Instant::now()+WAIT;
  while !frames.all_idle(){
   match frames.collect(){Ok(true)=>break,Ok(false) if Instant::now()<end=>std::thread::sleep(Duration::from_millis(1)),_=>{
    context.poisoned=true;eprintln!("IOSMETAL_FRAME_CLOSE retained_until_worker_exit=true reason=undrained-frame");
    let _=Box::into_raw(context);return;
   }}
  }
 }
 drop(context);
}

fn frame_result(c:&mut Context,result:Result<()>)->i32{match result{Ok(())=>0,Err(error)=>{
 eprintln!("IOSMETAL_FRAME_ERROR {error}");if error.starts_with("fatal:"){c.poisoned=true;-5}else if error=="frame:pool-busy"{-11}else{-22}
}}}
/// Trusted serialized host only. Output remains unchanged on failure. The
/// buffer is borrowed until frame_return; ready_fd ownership passes to caller.
#[no_mangle] pub unsafe extern "C" fn iosmetal_frame_export(context:*mut c_void,texture:u64,out:*mut frame_export::Frame)->i32{
 frame_create(context,texture,out,false)
}
#[no_mangle] pub unsafe extern "C" fn iosmetal_frame_prepare(context:*mut c_void,texture:u64,out:*mut frame_export::Frame)->i32{
 frame_create(context,texture,out,true)
}
unsafe fn frame_create(context:*mut c_void,texture:u64,out:*mut frame_export::Frame,prepare:bool)->i32{
 if context.is_null()||out.is_null(){return -22;}let c=&mut *context.cast::<Context>();if c.poisoned{return -5;}
 let result=(||->Result<()>{
  let source=c.texture(texture)?;
  if c.objects.values().any(|o|matches!(o,Object::Command(command) if command.value.status()!=CommandBufferStatus::Completed&&command.retained.iter().any(|t|Arc::ptr_eq(t,&source.ticket)))){return Err("frame:uncompleted-source-command".into());}
  let frames=c.frames.as_mut().ok_or("unsupported:shared-frames-not-enabled")?;
  let value=if prepare{frames.prepare(&c.budget,source)?}else{frames.export(&c.budget,source)?};ptr::write(out,value);Ok(())
 })();frame_result(c,result)
}
#[no_mangle] pub unsafe extern "C" fn iosmetal_frame_submit(context:*mut c_void,token:u64,out_fd:*mut i32)->i32{
 if context.is_null()||out_fd.is_null(){return -22;}let c=&mut *context.cast::<Context>();if c.poisoned{return -5;}
 let result=(||->Result<()>{let fd=c.frames.as_mut().ok_or("unsupported:shared-frames-not-enabled")?.submit(token)?;ptr::write(out_fd,fd);Ok(())})();frame_result(c,result)
}
#[no_mangle] pub unsafe extern "C" fn iosmetal_frame_cancel(context:*mut c_void,token:u64)->i32{
 if context.is_null(){return -22;}let c=&mut *context.cast::<Context>();if c.poisoned{return -5;}
 let result=c.frames.as_mut().ok_or("unsupported:shared-frames-not-enabled".to_owned()).and_then(|f|f.cancel(token));frame_result(c,result)
}
/// Consumes a valid consumer sync fd only on success; -1 means consumer done.
/// Never pass guest-supplied native descriptors through this host-only API.
#[no_mangle] pub unsafe extern "C" fn iosmetal_frame_return(context:*mut c_void,token:u64,fd:i32)->i32{
 if context.is_null(){return -22;}let c=&mut *context.cast::<Context>();if c.poisoned{return -5;}
 let result=c.frames.as_mut().ok_or("unsupported:shared-frames-not-enabled".to_owned()).and_then(|f|f.returned(token,fd));frame_result(c,result)
}
/// Polls actual producer and consumer completion without blocking. 0 drained,
/// -11 still leased/pending; errors never release in-flight storage.
#[no_mangle] pub unsafe extern "C" fn iosmetal_frame_collect(context:*mut c_void)->i32{
 if context.is_null(){return -22;}let c=&mut *context.cast::<Context>();if c.poisoned{return -5;}
 let result=c.frames.as_mut().ok_or("unsupported:shared-frames-not-enabled".to_owned()).and_then(|f|f.collect());
 match result{Ok(true)=>0,Ok(false)=>-11,Err(error)=>frame_result(c,Err(error))}
}
/// Five host counters: allocations,exports,collected,transport CPU bytes(0),slots.
#[no_mangle] pub unsafe extern "C" fn iosmetal_frame_stats(context:*mut c_void,out:*mut u64)->i32{
 if context.is_null()||out.is_null(){return -22;}let c=&*context.cast::<Context>();if c.poisoned{return -5;}
 let Some(f)=&c.frames else{return -22;};let values=[f.allocations,f.exports,f.collected,0,frame_lease::SLOTS as u64];ptr::copy_nonoverlapping(values.as_ptr(),out,5);0
}
