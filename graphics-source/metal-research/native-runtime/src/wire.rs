// SPDX-License-Identifier: AGPL-3.0-or-later
// Wire contract and object ownership have no Vulkan dependency.
pub const MAGIC: u32 = 0x314c544d;
pub const VERSION: u32 = 1;
pub const MAX_MESSAGE: usize = 32 * 1024 * 1024;
pub const MAX_OBJECTS: usize = 1024;
pub const MAX_RESOURCE: u64 = 32 * 1024 * 1024;
pub const MAX_RESOURCES: u64 = 256 * 1024 * 1024;
pub const MAX_SHADER: usize = 8 * 1024 * 1024;
pub const MAX_BINDINGS: u32 = 31;
#[derive(Debug, PartialEq, Eq)]
pub enum Fault { Invalid, Truncated, Unsupported, Handle, Quota, #[allow(dead_code)] State }
pub type Result<T> = std::result::Result<T, Fault>;
pub struct Request<'a> { pub op: u32, pub id: u64, pub body: &'a [u8] }
pub fn decode(data: &[u8]) -> Result<Request<'_>> {
    if data.len()>MAX_MESSAGE { return Err(Fault::Quota); }
    let mut r=Reader::new(data);
    if r.u32()?!=MAGIC || r.u32()?!=VERSION {return Err(Fault::Invalid);}
    let op=r.u32()?;let size=r.u32()? as usize;let id=r.u64()?;
    if !(1..=64).contains(&op)||id==0 {return Err(Fault::Invalid);}
    let body=r.take(size)?;r.finish()?;Ok(Request {op,id,body})
}

pub struct Reader<'a> { data: &'a [u8], at: usize }
impl<'a> Reader<'a> {
    pub fn new(data: &'a [u8]) -> Self { Self { data, at: 0 } }
    pub fn take(&mut self, n: usize) -> Result<&'a [u8]> {
        let end = self.at.checked_add(n).ok_or(Fault::Invalid)?;
        let value = self.data.get(self.at..end).ok_or(Fault::Truncated)?;
        self.at = end; Ok(value)
    }
    pub fn u32(&mut self) -> Result<u32> { Ok(u32::from_le_bytes(self.take(4)?.try_into().unwrap())) }
    pub fn u64(&mut self) -> Result<u64> { Ok(u64::from_le_bytes(self.take(8)?.try_into().unwrap())) }
    pub fn finish(&self) -> Result<()> { if self.at == self.data.len() { Ok(()) } else { Err(Fault::Invalid) } }
    pub fn rest(&mut self) -> &'a [u8] { let v = &self.data[self.at..]; self.at = self.data.len(); v }
}
struct Slot<T> { generation: u32, value: Option<T>, charge: u64 }
pub struct Arena<T> { slots: Vec<Slot<T>>, bytes: u64, owner: u32 }
impl<T> Arena<T> {
    pub fn new(owner: u32) -> Self { Self { slots: Vec::new(), bytes: 0, owner } }
    pub fn ensure_slot(&mut self) -> Result<()> {
        if self.slots.iter().any(|s|s.value.is_none()&&s.generation<u32::MAX){return Ok(());}
        if self.slots.len()>=MAX_OBJECTS{return Err(Fault::Quota);}
        self.slots.try_reserve(1).map_err(|_|Fault::Quota)
    }
    pub fn insert(&mut self, value: T, charge: u64) -> Result<u64> {
        let total=self.bytes.checked_add(charge).ok_or(Fault::Quota)?;
        if charge>MAX_RESOURCE||total>MAX_RESOURCES {return Err(Fault::Quota);}
        let slot=self.slots.iter().position(|s|s.value.is_none()&&s.generation<u32::MAX);
        let index=match slot {Some(i)=>i,None=>{
            if self.slots.len()>=MAX_OBJECTS {return Err(Fault::Quota);}
            self.slots.push(Slot {generation:0,value:None,charge:0});self.slots.len()-1
        }};
        let s=&mut self.slots[index];s.generation+=1;s.value=Some(value);s.charge=charge;
        self.bytes=total;Ok(((s.generation as u64)<<32)|(index as u64+1))
    }
    fn index(&self, owner: u32, id: u64) -> Result<usize> {
        if owner!=self.owner {return Err(Fault::Handle);}
        let index=(id as u32).checked_sub(1).ok_or(Fault::Handle)? as usize;
        let s=self.slots.get(index).ok_or(Fault::Handle)?;
        if s.value.is_none()||s.generation!=(id>>32) as u32 {return Err(Fault::Handle);}
        Ok(index)
    }
    pub fn get(&self, owner: u32, id: u64) -> Result<&T> {Ok(self.slots[self.index(owner,id)?].value.as_ref().unwrap())}
    pub fn values(&self) -> impl Iterator<Item=&T> { self.slots.iter().filter_map(|s|s.value.as_ref()) }
    pub fn get_mut(&mut self, owner: u32, id: u64) -> Result<&mut T> {
        let i=self.index(owner,id)?;Ok(self.slots[i].value.as_mut().unwrap())
    }
    pub fn remove(&mut self, owner: u32, id: u64) -> Result<T> {
        let i=self.index(owner,id)?;let s=&mut self.slots[i];self.bytes-=s.charge;s.charge=0;
        Ok(s.value.take().unwrap())
    }
    #[cfg(test)] pub fn bytes(&self) -> u64 { self.bytes }
}
pub fn region(length: u64, offset: u64, size: u64) -> Result<()> {
    if offset.checked_add(size).is_some_and(|end|end<=length) {Ok(())} else {Err(Fault::Invalid)}
}
pub fn grid(threads: [u64;3], group: [u64;3]) -> Result<()> {
    fn product(a:[u64;3],limit:u64)->bool {
        a.into_iter().try_fold(1u64,|p,v|if v==0 {None} else {p.checked_mul(v)})
            .is_some_and(|v|v<=limit)
    }
    if product(threads,16*1024*1024)&&product(group,1024)&&group[2]<=64 {Ok(())} else {Err(Fault::Quota)}
}
pub fn dispatch_grid(threads:[u64;3],group:[u64;3],group_counts:bool)->Result<()> {
    grid(threads,group)?;
    if group_counts {
        let a=threads.into_iter().product::<u64>();let b=group.into_iter().product::<u64>();
        if a.checked_mul(b).is_none_or(|n|n>16*1024*1024){return Err(Fault::Quota);}
    }
    Ok(())
}

#[cfg(test)] mod tests {
 use super::*;
 fn packet(body: &[u8]) -> Vec<u8> {
   let mut p=Vec::new(); for v in [MAGIC,VERSION,1,body.len() as u32] {p.extend(v.to_le_bytes());}
   p.extend(123u64.to_le_bytes());p.extend(body);p
 }
 #[test] fn valid_request_and_exact_length() {
   let p=packet(&[4,5,6]);let r=decode(&p).unwrap();assert_eq!((r.op,r.id,r.body),(1,123,&[4,5,6][..]));
   for n in 0..p.len() {assert!(decode(&p[..n]).is_err());}
   let mut extra=p.clone();extra.push(0);assert!(decode(&extra).is_err());
 }
 #[test] fn bad_headers_and_oversize() {
   for offset in [0,4,8,16] {let mut p=packet(&[]);p[offset..offset+4].copy_from_slice(&0u32.to_le_bytes());assert!(decode(&p).is_err());}
   assert!(decode(&vec![0;MAX_MESSAGE+1]).is_err());
 }
 #[test] fn reader_checks_trailing_and_overflow() {
   let mut r=Reader::new(&[0;8]);assert_eq!(r.u64().unwrap(),0);assert!(r.finish().is_ok());
   assert_eq!(r.take(usize::MAX),Err(Fault::Invalid));
   assert_eq!(Reader::new(&[0]).finish(),Err(Fault::Invalid));
 }
 #[test] fn ownership_generations_and_double_release() {
   let mut a=Arena::new(9);let id=a.insert(17,4096).unwrap();assert_eq!(*a.get(9,id).unwrap(),17);
   assert_eq!(a.get(8,id),Err(Fault::Handle));assert_eq!(a.remove(8,id),Err(Fault::Handle));
   assert_eq!(a.remove(9,id).unwrap(),17);assert_eq!(a.bytes(),0);assert_eq!(a.remove(9,id),Err(Fault::Handle));
   let next=a.insert(19,1).unwrap();assert_ne!(id,next);assert_eq!(a.get(9,id),Err(Fault::Handle));
   *a.get_mut(9,next).unwrap()=20;assert_eq!(*a.get(9,next).unwrap(),20);
 }
 #[test] fn quotas_are_transactional_and_release_recovers() {
   let mut a=Arena::new(1);assert_eq!(a.insert(0,MAX_RESOURCE+1),Err(Fault::Quota));
   let mut ids=Vec::new();for _ in 0..8 {ids.push(a.insert(0,MAX_RESOURCE).unwrap());}
   assert_eq!(a.insert(0,1),Err(Fault::Quota));assert_eq!(a.bytes(),MAX_RESOURCES);
   a.remove(1,ids[0]).unwrap();assert!(a.insert(0,1).is_ok());
   let mut a=Arena::new(2);for _ in 0..MAX_OBJECTS {a.insert(0,0).unwrap();}
   assert_eq!(a.ensure_slot(),Err(Fault::Quota));
   assert_eq!(a.insert(0,0),Err(Fault::Quota));
 }
 #[test] fn ranges_include_offsets_and_reject_wrap() {
   assert!(region(1024,512,512).is_ok());assert!(region(1024,1024,0).is_ok());
   assert_eq!(region(1024,513,512),Err(Fault::Invalid));
   assert!(region(u64::MAX,u64::MAX,1).is_err());
 }
 #[test] fn grid_caps_and_checked_products() {
   assert!(grid([1000,1,1],[64,1,1]).is_ok());assert!(grid([1,1,1],[1,1,1]).is_ok());
   for (t,g) in [([0,1,1],[64,1,1]),([u64::MAX,2,1],[1,1,1]),([1,1,1],[1025,1,1]),([1,1,1],[1,0,1])] {assert!(grid(t,g).is_err());}
 }
 #[test] fn groups_limit_counts_total_invocations() {
   assert!(dispatch_grid([16384,1,1],[1024,1,1],true).is_ok());
   assert!(dispatch_grid([16385,1,1],[1024,1,1],true).is_err());
   assert!(dispatch_grid([16*1024*1024,1,1],[1024,1,1],false).is_ok());
 }
}
