// SPDX-License-Identifier: AGPL-3.0-or-later
//! Frame an owned reply into the caller's bounded trusted-host output.
use crate::wire;
use std::mem::MaybeUninit;

/// Fill an exact reply body in caller storage, publishing its header last.
/// A failed fill leaves body bytes unpublished; the caller may frame an error.
pub fn write_with<E>(sequence: u64, body_len: usize, output: &mut [MaybeUninit<u8>],
    fill: impl FnOnce(&mut [u8]) -> Result<(), E>) -> Result<Option<usize>, E> {
    let Some(count) = body_len.checked_add(24) else { return Ok(None) };
    let Ok(length) = u32::try_from(body_len) else { return Ok(None) };
    if count > output.len() { return Ok(None); }
    let (header, rest) = output.split_at_mut(24);
    let body = &mut rest[..body_len];
    // C may supply malloc'd or shared uninitialized output. Initialize every
    // selected byte before forming &mut [u8]; zero padding matches old Vec data.
    unsafe { std::ptr::write_bytes(body.as_mut_ptr().cast::<u8>(), 0, body_len); }
    let initialized = unsafe { std::slice::from_raw_parts_mut(body.as_mut_ptr().cast::<u8>(), body_len) };
    fill(initialized)?;
    let mut bytes = [0u8; 24];
    bytes[..4].copy_from_slice(&wire::MAGIC.to_le_bytes());
    bytes[4..8].copy_from_slice(&wire::VERSION.to_le_bytes());
    bytes[12..16].copy_from_slice(&length.to_le_bytes());
    bytes[16..24].copy_from_slice(&sequence.to_le_bytes());
    // Only a successful, complete fill publishes a status=0 header.
    unsafe { std::ptr::copy_nonoverlapping(bytes.as_ptr(), header.as_mut_ptr().cast::<u8>(), 24); }
    Ok(Some(count))
}

pub fn write(status: i32, sequence: u64, body: &[u8], output: &mut [MaybeUninit<u8>]) -> Option<usize> {
    let count = body.len().checked_add(24)?;
    let length = u32::try_from(body.len()).ok()?;
    if count > output.len() { return None; }
    // Validate before publishing anything. The body is already owned by the
    // request dispatcher; framing needs no second allocation or staging copy.
    let mut header = [0u8; 24];
    header[..4].copy_from_slice(&wire::MAGIC.to_le_bytes());
    header[4..8].copy_from_slice(&wire::VERSION.to_le_bytes());
    header[8..12].copy_from_slice(&status.to_le_bytes());
    header[12..16].copy_from_slice(&length.to_le_bytes());
    header[16..24].copy_from_slice(&sequence.to_le_bytes());
    // C callers may provide malloc'd, uninitialized output. MaybeUninit makes
    // that contract explicit; only the reported prefix becomes initialized.
    // Both destinations fit the unique output slice, which cannot alias body.
    unsafe {
        std::ptr::copy_nonoverlapping(header.as_ptr(), output.as_mut_ptr().cast::<u8>(), 24);
        std::ptr::copy_nonoverlapping(body.as_ptr(), output.as_mut_ptr().add(24).cast::<u8>(), body.len());
    }
    Some(count)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::alloc::{GlobalAlloc, Layout, System};
    use std::cell::Cell;

    struct Tracked;
    thread_local! {
        static ENABLED: Cell<bool> = const { Cell::new(false) };
        static ALLOCATIONS: Cell<usize> = const { Cell::new(0) };
    }
    fn allocated() {
        if ENABLED.try_with(Cell::get).unwrap_or(false) {
            let _ = ALLOCATIONS.try_with(|n| n.set(n.get() + 1));
        }
    }
    unsafe impl GlobalAlloc for Tracked {
        unsafe fn alloc(&self, layout: Layout) -> *mut u8 { allocated(); System.alloc(layout) }
        unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 { allocated(); System.alloc_zeroed(layout) }
        unsafe fn realloc(&self, p: *mut u8, layout: Layout, n: usize) -> *mut u8 { allocated(); System.realloc(p, layout, n) }
        unsafe fn dealloc(&self, p: *mut u8, layout: Layout) { System.dealloc(p, layout) }
    }
    #[global_allocator] static TRACKED: Tracked = Tracked;

    // Initialized test buffers can also be passed through the C output contract.
    fn writable(bytes: &mut [u8]) -> &mut [MaybeUninit<u8>] {
        unsafe { std::slice::from_raw_parts_mut(bytes.as_mut_ptr().cast(), bytes.len()) }
    }

    #[test]
    fn exact_header_and_body_preserve_unused_output() {
        let mut output = [0xa7; 33];
        assert_eq!(write(0, 0x0807060504030201, &[0x13, 0x25, 0x42], writable(&mut output)), Some(27));
        assert_eq!(&output[..24], &[0x4d,0x54,0x4c,0x31,1,0,0,0,0,0,0,0,3,0,0,0,1,2,3,4,5,6,7,8]);
        assert_eq!(&output[24..27], &[0x13, 0x25, 0x42]);
        assert_eq!(&output[27..], &[0xa7; 6]);
    }
    #[test]
    fn negative_status_and_empty_payload_are_encoded_exactly() {
        let mut output = [0u8; 24];
        assert_eq!(write(-2, u64::MAX, &[], writable(&mut output)), Some(24));
        assert_eq!(&output[8..16], &[0xfe,0xff,0xff,0xff,0,0,0,0]);
        assert_eq!(&output[16..], &[0xff; 8]);
    }
    #[test]
    fn insufficient_capacity_never_publishes_partial_header_or_body() {
        for capacity in 0..28 {
            let mut output = [0xa7; 28];
            assert_eq!(write(-1, 0, &[1,2,3,4], writable(&mut output[..capacity])), None);
            assert_eq!(output, [0xa7; 28]);
        }
    }
    #[test]
    fn native_size_framing_allocates_nothing_and_preserves_every_byte() {
        let size = 1440 * 3120 * 4;
        let body: Vec<u8> = (0..size).map(|i| ((i * 31 + i / 997) % 251) as u8).collect();
        let mut output = vec![0xa7; size + 24 + 16];
        ALLOCATIONS.set(0); ENABLED.set(true);
        let count = write(0, 43, &body, writable(&mut output));
        ENABLED.set(false);
        assert_eq!(count, Some(size + 24));
        assert_eq!(&output[24..size + 24], &body);
        assert_eq!(&output[size + 24..], &[0xa7; 16]);
        assert_eq!(ALLOCATIONS.get(), 0, "Framing duplicates a full native-resolution response allocation");
    }
    #[test]
    fn uninitialized_c_output_initializes_only_the_reported_prefix() {
        let mut output = [MaybeUninit::<u8>::uninit(); 1048];
        let count = write(0, 11, &[3,1,4,1,5,9,2,6], &mut output).unwrap();
        assert_eq!(count, 32);
        // Never inspect the uninitialized capacity beyond the returned count.
        let bytes: Vec<u8> = output[..count].iter().map(|value| unsafe { value.assume_init() }).collect();
        assert_eq!(&bytes[..8], &[0x4d,0x54,0x4c,0x31,1,0,0,0]);
        assert_eq!(&bytes[12..16], &[8,0,0,0]);
        assert_eq!(&bytes[24..], &[3,1,4,1,5,9,2,6]);
    }

    #[test]
    fn direct_fill_initializes_padding_and_preserves_tail() {
        let mut output = [0xa7; 48];
        let mut calls = 0;
        let count = write_with::<&str>(19, 13, writable(&mut output), |body| {
            calls += 1;
            assert_eq!(body, &[0; 13]);
            body[0] = 0x42; body[12] = 0x13;
            Ok(())
        });
        assert_eq!(count, Ok(Some(37))); assert_eq!(calls, 1);
        assert_eq!(&output[..24], &[0x4d,0x54,0x4c,0x31,1,0,0,0,0,0,0,0,13,0,0,0,19,0,0,0,0,0,0,0]);
        assert_eq!(&output[24..37], &[0x42,0,0,0,0,0,0,0,0,0,0,0,0x13]);
        assert_eq!(&output[37..], &[0xa7; 11]);
    }

    #[test]
    fn direct_short_capacity_never_calls_fill_or_changes_output() {
        for capacity in 0..37 {
            let mut output = [0xa7; 48];
            let count = write_with::<&str>(7, 13, writable(&mut output[..capacity]), |_| panic!("capacity preflight was late"));
            assert_eq!(count, Ok(None)); assert_eq!(output, [0xa7; 48]);
        }
        let mut output = [0xa7; 48];
        assert_eq!(write_with::<&str>(7, usize::MAX, writable(&mut output), |_| panic!("overflow accepted")), Ok(None));
        assert_eq!(output, [0xa7; 48]);
    }

    #[test]
    fn direct_fill_failure_and_panic_never_publish_success_header() {
        let mut output = [0xa7; 48];
        let result = write_with(9, 13, writable(&mut output), |body| {
            body[0] = 3; Err("read failed")
        });
        assert_eq!(result, Err("read failed"));
        assert_eq!(&output[..24], &[0xa7; 24]); assert_eq!(&output[37..], &[0xa7; 11]);
        let mut output = [0xa7; 48];
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            write_with::<&str>(9, 13, writable(&mut output), |body| { body[0] = 4; panic!("backend panic control") })
        }));
        assert!(result.is_err());
        assert_eq!(&output[..24], &[0xa7; 24]); assert_eq!(&output[37..], &[0xa7; 11]);
    }

    #[test]
    fn direct_uninitialized_c_storage_and_empty_body_are_supported() {
        let mut output = [MaybeUninit::<u8>::uninit(); 1050];
        let count = write_with::<&str>(11, 257, &mut output, |body| {
            for (i, byte) in body.iter_mut().enumerate() { *byte = (i % 251) as u8; } Ok(())
        }).unwrap().unwrap();
        assert_eq!(count, 281);
        for (i, byte) in output[24..count].iter().enumerate() { assert_eq!(unsafe { byte.assume_init() }, (i % 251) as u8); }
        let mut output = [0xa7; 32];
        assert_eq!(write_with::<&str>(12, 0, writable(&mut output), |body| { assert!(body.is_empty()); Ok(()) }), Ok(Some(24)));
        assert_eq!(&output[24..], &[0xa7; 8]);
    }

    #[test]
    fn direct_native_size_fill_allocates_nothing() {
        let size = 1440 * 3120 * 4;
        let mut output = vec![0xa7; size + 24 + 16];
        ALLOCATIONS.set(0); ENABLED.set(true);
        let count = write_with::<&str>(43, size, writable(&mut output), |body| {
            for (i, byte) in body.iter_mut().enumerate() { *byte = ((i * 31 + i / 997) % 251) as u8; }
            Ok(())
        });
        ENABLED.set(false);
        assert_eq!(count, Ok(Some(size + 24)));
        for (i, byte) in output[24..size + 24].iter().enumerate() { assert_eq!(*byte, ((i * 31 + i / 997) % 251) as u8); }
        assert_eq!(&output[size + 24..], &[0xa7; 16]);
        assert_eq!(ALLOCATIONS.get(), 0, "Direct fill allocated an intermediate full-frame reply");
    }
}
