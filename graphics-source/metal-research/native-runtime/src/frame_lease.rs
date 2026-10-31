// SPDX-License-Identifier: AGPL-3.0-or-later
//! Host frame leases. GPU submission and consumer completion are distinct events.
pub const SLOTS: usize = 3;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum State { Idle, Reserved(u64), Published(u64), Returned(u64) }
pub struct Leases { epoch: u32, next: u32, slots: [State; SLOTS] }
impl Leases {
    pub fn new(epoch: u32) -> Self { Self {epoch, next: 1, slots: [State::Idle; SLOTS]} }
    pub fn reserve(&mut self) -> Result<(usize,u64), &'static str> {
        if self.epoch==0 || self.next==u32::MAX { return Err("frame:token-exhausted"); }
        let slot=self.slots.iter().position(|s|*s==State::Idle).ok_or("frame:pool-busy")?;
        let token=(u64::from(self.epoch)<<32)|u64::from(self.next);self.next+=1;
        self.slots[slot]=State::Reserved(token);Ok((slot,token))
    }
    pub fn publish(&mut self, slot:usize, token:u64) -> Result<(), &'static str> {
        if self.slots.get(slot)!=Some(&State::Reserved(token)){return Err("frame:not-reserved");}
        self.slots[slot]=State::Published(token);Ok(())
    }
    pub fn reserved(&self,token:u64)->Result<usize,&'static str>{
        self.slots.iter().position(|s|*s==State::Reserved(token)).ok_or("frame:stale-or-foreign-token")
    }
    pub fn has_reserved(&self)->bool{self.slots.iter().any(|s|matches!(s,State::Reserved(_)))}
    pub fn abort(&mut self, slot:usize, token:u64) -> Result<(), &'static str> {
        if self.slots.get(slot)!=Some(&State::Reserved(token)){return Err("frame:not-reserved");}
        self.slots[slot]=State::Idle;Ok(())
    }
    pub fn returned(&mut self, token:u64) -> Result<usize, &'static str> {
        let slot=self.slots.iter().position(|s|*s==State::Published(token)).ok_or("frame:stale-or-foreign-token")?;
        self.slots[slot]=State::Returned(token);Ok(slot)
    }
    pub fn collect(&mut self, slot:usize, producer:bool, consumer:bool) -> bool {
        if producer&&consumer&&matches!(self.slots.get(slot),Some(State::Returned(_))){self.slots[slot]=State::Idle;true}else{false}
    }
    #[cfg(test)] pub fn idle(&self, slot:usize) -> bool { self.slots.get(slot)==Some(&State::Idle) }
    pub fn all_idle(&self) -> bool { self.slots.iter().all(|s|*s==State::Idle) }
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn third_lease_exhausts_pool_without_reuse() {
        let mut p=Leases::new(7); let mut tokens=Vec::new();
        for _ in 0..SLOTS {let (slot,t)=p.reserve().unwrap();p.publish(slot,t).unwrap();tokens.push(t);}
        assert!(p.reserve().is_err());assert!(tokens.windows(2).all(|t|t[0]!=t[1]));
    }
    #[test] fn both_completions_are_required() {
        let mut p=Leases::new(7);let (slot,t)=p.reserve().unwrap();p.publish(slot,t).unwrap();
        assert!(!p.collect(slot,true,true));p.returned(t).unwrap();
        assert!(!p.collect(slot,true,false));assert!(!p.collect(slot,false,true));
        assert!(!p.idle(slot));assert!(p.collect(slot,true,true));assert!(p.all_idle());
    }
    #[test] fn foreign_epoch_and_stale_or_duplicate_returns_are_refused() {
        let mut a=Leases::new(7);let mut b=Leases::new(8);
        let (s,t)=a.reserve().unwrap();a.publish(s,t).unwrap();let (bs,bt)=b.reserve().unwrap();b.publish(bs,bt).unwrap();
        assert!(b.returned(t).is_err());assert!(a.returned(bt).is_err());
        a.returned(t).unwrap();assert!(a.returned(t).is_err());assert!(a.collect(s,true,true));
        let (s2,t2)=a.reserve().unwrap();assert_ne!(t,t2);a.publish(s2,t2).unwrap();assert!(a.returned(t).is_err());
    }
    #[test] fn failed_pre_submission_reservation_can_abort_only_once() {
        let mut p=Leases::new(9);let (s,t)=p.reserve().unwrap();assert!(p.returned(t).is_err());
        assert!(p.abort(s,t^1).is_err());p.abort(s,t).unwrap();assert!(p.all_idle());assert!(p.publish(s,t).is_err());
        let (s,t)=p.reserve().unwrap();p.publish(s,t).unwrap();assert!(p.abort(s,t).is_err());
    }
    #[test] fn token_exhaustion_never_wraps_and_bad_indices_do_not_mutate() {
        let mut p=Leases::new(7);p.next=u32::MAX;assert!(p.reserve().is_err());assert!(p.all_idle());
        assert!(p.publish(SLOTS,1).is_err());assert!(!p.collect(SLOTS,true,true));assert!(!p.idle(SLOTS));
        assert!(Leases::new(0).reserve().is_err());
    }
    #[test] fn prepared_tokens_resolve_only_until_publish_or_cancel() {
        let mut p=Leases::new(11);assert!(!p.has_reserved());let (s,t)=p.reserve().unwrap();
        assert!(p.has_reserved());assert_eq!(p.reserved(t).unwrap(),s);assert!(p.reserved(t^1).is_err());
        assert!(p.returned(t).is_err());p.publish(s,t).unwrap();assert!(!p.has_reserved());assert!(p.reserved(t).is_err());
        let (s2,t2)=p.reserve().unwrap();p.abort(s2,t2).unwrap();assert!(!p.has_reserved());assert!(p.reserved(t2).is_err());
    }
}
