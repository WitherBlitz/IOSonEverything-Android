// SPDX-License-Identifier: AGPL-3.0-or-later
use std::sync::{Arc,OnceLock,atomic::{AtomicU64,Ordering}};
const SINGLE:u64=32*1024*1024;
const TOTAL:u64=256*1024*1024;
static GLOBAL:OnceLock<Arc<AtomicU64>>=OnceLock::new();
#[derive(Clone)] pub struct Budget(Arc<AtomicU64>);
pub struct Ticket {budget:Budget,bytes:u64}
impl Drop for Ticket {fn drop(&mut self){self.budget.0.fetch_sub(self.bytes,Ordering::Relaxed);}}
impl Budget {
 pub fn new()->Self{Self(GLOBAL.get_or_init(||Arc::new(AtomicU64::new(0))).clone())}
 pub fn reserve(&self,bytes:u64)->Result<Arc<Ticket>,String>{
  if bytes>SINGLE{return Err("quota:single-resource".into());}
  self.0.fetch_update(Ordering::Relaxed,Ordering::Relaxed,|old|old.checked_add(bytes).filter(|n|*n<=TOTAL)).map_err(|_|"quota:retained-resources".to_string())?;
  Ok(Arc::new(Ticket{budget:self.clone(),bytes}))
 }
}
#[derive(Clone)]pub struct QueueLimit(Arc<AtomicU64>);
pub struct QueueSlot(QueueLimit);
impl Drop for QueueSlot{fn drop(&mut self){self.0.0.fetch_sub(1,Ordering::Relaxed);}}
impl QueueLimit {
 pub fn new()->Self{Self(Arc::new(AtomicU64::new(0)))}
 pub fn reserve(&self)->Result<QueueSlot,String>{
  self.0.fetch_update(Ordering::Relaxed,Ordering::Relaxed,|old|if old<32{Some(old+1)}else{None}).map_err(|_|"quota:uncompleted-commands".to_string())?;
  Ok(QueueSlot(self.clone()))
 }
}
#[cfg(test)]mod tests{
 use super::*;
 #[test]fn retained_ticket_releases_only_at_last_reference(){
  let b=Budget::new();let mut all=Vec::new();for _ in 0..8{all.push(b.reserve(SINGLE).unwrap());}
  let retained=all[0].clone();all.remove(0);assert!(b.reserve(1).is_err());drop(retained);assert!(b.reserve(1).is_ok());
 }
 #[test]fn resource_budget_is_shared_across_contexts(){
  let a=Budget::new();let b=Budget::new();let mut tickets=Vec::new();for _ in 0..8{tickets.push(a.reserve(SINGLE).unwrap());}
  assert!(b.reserve(1).is_err());drop(tickets);assert!(b.reserve(SINGLE).is_ok());
 }
 #[test]fn queue_exhaustion_refuses_without_blocking_and_recovers(){
  let q=QueueLimit::new();let mut slots=Vec::new();for _ in 0..32{slots.push(q.reserve().unwrap());}
  assert!(q.reserve().is_err());slots.pop();assert!(q.reserve().is_ok());drop(slots);assert!(q.reserve().is_ok());
 }
}
