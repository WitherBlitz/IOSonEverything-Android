// SPDX-License-Identifier: AGPL-3.0-or-later
//! Bounded encoder-only stream. No effects until the whole body is decoded.
use crate::wire::{Fault,Reader,Result};
pub const MAX_OPERATIONS:usize=256;
pub const MAX_BYTES:usize=65536;
#[derive(Debug,PartialEq,Eq)]
pub struct Entry<'a>{pub op:u32,pub body:&'a [u8]}
pub fn decode(data:&[u8])->Result<Vec<Entry<'_>>>{
 if data.len()>MAX_BYTES{return Err(Fault::Quota);}
 let mut r=Reader::new(data);let count=r.u32()? as usize;
 if count==0||count>MAX_OPERATIONS{return Err(Fault::Quota);}
 let mut entries=Vec::new();entries.try_reserve_exact(count).map_err(|_|Fault::Quota)?;
 for _ in 0..count{
  let op=r.u32()?;let size=r.u32()? as usize;
  let expected=match op{11|23=>16,12=>32,13=>60,14=>8,24=>44,26|28|31=>24,_=>return Err(Fault::Unsupported)};
  if size!=expected{return Err(Fault::Invalid);}
  entries.push(Entry{op,body:r.take(size)?});
 }
 r.finish()?;Ok(entries)
}

#[cfg(test)] mod tests{
 use super::*;
 fn packet(entries:&[(u32,usize)])->Vec<u8>{let mut v=(entries.len() as u32).to_le_bytes().to_vec();for (index,(op,size)) in entries.iter().enumerate(){v.extend(op.to_le_bytes());v.extend((*size as u32).to_le_bytes());v.extend(vec![(index+1) as u8;*size]);}v}
 #[test] fn all_encoder_operations_keep_order_and_exact_bodies(){let specs=[(11,16),(12,32),(13,60),(14,8),(23,16),(24,44),(26,24),(28,24),(31,24)];let bytes=packet(&specs);let entries=decode(&bytes).unwrap();assert_eq!(entries.len(),specs.len());for (i,e) in entries.iter().enumerate(){assert_eq!(e.op,specs[i].0);assert_eq!(e.body,vec![(i+1) as u8;specs[i].1]);}}
 #[test] fn truncated_or_trailing_last_record_rejects_entire_batch(){let bytes=packet(&[(11,16),(14,8)]);for n in 0..bytes.len(){assert!(decode(&bytes[..n]).is_err(),"truncated at{n}");}let mut extra=bytes;extra.push(0);assert!(decode(&extra).is_err());}
 #[test] fn no_creates_reads_uploads_release_commit_or_recursive_batch(){for op in [1,2,3,4,5,6,7,8,9,10,15,16,17,18,19,20,21,22,25,27,29,30,32,33,64,u32::MAX]{assert_eq!(decode(&packet(&[(11,16),(op,8)])),Err(Fault::Unsupported));}}
 #[test] fn wrong_body_size_rejected_before_any_dispatch(){for (op,size) in [(11,16),(12,32),(13,60),(14,8),(23,16),(24,44),(26,24),(28,24),(31,24)]{for wrong in [0,size-1,size+1]{assert_eq!(decode(&packet(&[(14,8),(op,wrong)])),Err(Fault::Invalid));}}}
 #[test] fn exact_count_bounds_and_byte_budget(){assert!(decode(&packet(&vec![(14,8);MAX_OPERATIONS])).is_ok());assert_eq!(decode(&packet(&[])),Err(Fault::Quota));assert_eq!(decode(&packet(&vec![(14,8);MAX_OPERATIONS+1])),Err(Fault::Quota));assert_eq!(decode(&vec![0;MAX_BYTES+1]),Err(Fault::Quota));let huge=u32::MAX.to_le_bytes();assert_eq!(decode(&huge),Err(Fault::Quota));}
}
