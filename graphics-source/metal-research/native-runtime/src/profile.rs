// SPDX-License-Identifier: AGPL-3.0-or-later
//! Opt-in numeric diagnostics only. No payloads, addresses or shader data.
use std::time::Instant;
const BUCKETS: usize = 65;
const UNKNOWN: usize = 64;
const WINDOW_NS: u64 = 5_000_000_000;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
struct Stats {
    calls: u64,
    ns: u64,
    max_ns: u64,
    input_bytes: u64,
    output_bytes: u64,
    errors: u64,
}

struct Aggregate {
    stats: [Stats; BUCKETS],
    since: u64,
}
impl Aggregate {
    fn new(since: u64) -> Self { Self { stats: [Stats::default(); BUCKETS], since } }
    fn record(&mut self, op: u32, ns: u64, input: u64, output: u64, error: bool) {
        let s = &mut self.stats[(op as usize).min(UNKNOWN)];
        s.calls = s.calls.saturating_add(1);
        s.ns = s.ns.saturating_add(ns);
        s.max_ns = s.max_ns.max(ns);
        s.input_bytes = s.input_bytes.saturating_add(input);
        s.output_bytes = s.output_bytes.saturating_add(output);
        s.errors = s.errors.saturating_add(u64::from(error));
    }
    fn take(&mut self, now: u64) -> Option<(u64, [Stats; BUCKETS])> {
        let span = now.checked_sub(self.since)?;
        if span < WINDOW_NS { return None; }
        self.since = now;
        Some((span, std::mem::replace(&mut self.stats, [Stats::default(); BUCKETS])))
    }
}
fn enabled(value: Option<&str>) -> bool { value == Some("1") }

pub struct Profile { origin: Instant, owner: u32, aggregate: Aggregate }
impl Profile {
    // Environment and allocation are consulted only at context creation. Inactive
    // contexts carry one null pointer; no clock read on their request path.
    pub fn from_environment(owner: u32) -> Option<Box<Self>> {
        if !enabled(std::env::var("IOSVM_GPU_PROFILE").ok().as_deref()) { return None; }
        Some(Box::new(Self { origin: Instant::now(), owner, aggregate: Aggregate::new(0) }))
    }
}
pub fn begin(profile: &Option<Box<Profile>>) -> Option<Instant> {
    profile.as_ref().map(|_| Instant::now())
}
pub fn finish(profile: &mut Option<Box<Profile>>, start: Option<Instant>, op: u32,
              input: u32, output: u32, error: bool) {
    let (Some(profile), Some(start)) = (profile.as_mut(), start) else { return; };
    let now = Instant::now();
    let ns = |from| now.saturating_duration_since(from).as_nanos().min(u64::MAX as u128) as u64;
    profile.aggregate.record(op, ns(start), input as u64, output as u64, error);
    if let Some((span, stats)) = profile.aggregate.take(ns(profile.origin)) {
        for (op, s) in stats.iter().enumerate().filter(|(_, s)| s.calls != 0) {
            log(&format!("owner={} op={} calls={} avg_us={} total_us={} max_us={} in_bytes={} out_bytes={} errors={} span_ms={}",
                profile.owner, op, s.calls, s.ns / s.calls / 1000, s.ns / 1000,
                s.max_ns / 1000, s.input_bytes, s.output_bytes, s.errors, span / 1_000_000));
        }
    }
}

#[cfg(target_os = "android")]
fn log(message: &str) {
    #[link(name = "log")]
    extern "C" { fn __android_log_write(priority: i32, tag: *const std::ffi::c_char, text: *const std::ffi::c_char) -> i32; }
    if let Ok(text) = std::ffi::CString::new(message) {
        // Both strings remain live and NUL terminated for the synchronous call.
        unsafe { __android_log_write(4, b"IosMetalPerf\0".as_ptr().cast(), text.as_ptr()); }
    }
}
#[cfg(not(target_os = "android"))]
fn log(message: &str) {
    use std::io::Write;
    let _ = writeln!(std::io::stderr().lock(), "IosMetalPerf {message}");
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn enabled_only_by_explicit_one() {
        assert!(enabled(Some("1")));
        for value in [None, Some(""), Some("0"), Some("true"), Some(" 1"), Some("1 ")] {
            assert!(!enabled(value));
        }
        assert!(begin(&None).is_none());
        finish(&mut None, None, 20, 0, 0, false);
    }
    #[test]
    fn aggregates_numeric_operations_and_preserves_boundaries() {
        let mut a = Aggregate::new(10);
        a.record(15, 4_000, 32, 28, false);
        a.record(15, 9_000, 32, 0, true);
        a.record(20, 17_000, 64, 18_000_024, false);
        assert!(a.take(WINDOW_NS + 9).is_none());
        let (span, stats) = a.take(WINDOW_NS + 10).unwrap();
        assert_eq!(span, WINDOW_NS);
        assert_eq!(stats[15], Stats { calls: 2, ns: 13_000, max_ns: 9_000, input_bytes: 64, output_bytes: 28, errors: 1 });
        assert_eq!(stats[20], Stats { calls: 1, ns: 17_000, max_ns: 17_000, input_bytes: 64, output_bytes: 18_000_024, errors: 0 });
        assert_eq!(stats[0], Stats::default());
    }
    #[test]
    fn snapshot_resets_counts_and_starts_a_new_window() {
        let mut a = Aggregate::new(0);
        a.record(20, 25, 10, 100, false);
        assert!(a.take(WINDOW_NS).is_some());
        assert!(a.take(WINDOW_NS * 2 - 1).is_none());
        a.record(15, 2, 3, 4, false);
        let (span, stats) = a.take(WINDOW_NS * 2).unwrap();
        assert_eq!(span, WINDOW_NS);
        assert_eq!(stats[20], Stats::default());
        assert_eq!(stats[15].calls, 1);
    }
    #[test]
    fn untrusted_opcode_uses_one_fixed_unknown_bucket() {
        let mut a = Aggregate::new(0);
        for op in [64, 65, u32::MAX] { a.record(op, 1, 2, 3, true); }
        a.record(63, 7, 8, 9, false);
        let (_, stats) = a.take(WINDOW_NS).unwrap();
        assert_eq!(stats[UNKNOWN].calls, 3);
        assert_eq!(stats[UNKNOWN].errors, 3);
        assert_eq!(stats[63].calls, 1);
    }
    #[test]
    fn counters_saturate_and_clock_regression_does_not_flush() {
        let mut a = Aggregate::new(100);
        a.stats[20] = Stats { calls: u64::MAX, ns: u64::MAX, max_ns: 1, input_bytes: u64::MAX, output_bytes: u64::MAX, errors: u64::MAX };
        a.record(20, 123, 44, 88, true);
        assert_eq!(a.stats[20], Stats { calls: u64::MAX, ns: u64::MAX, max_ns: 123, input_bytes: u64::MAX, output_bytes: u64::MAX, errors: u64::MAX });
        assert!(a.take(99).is_none());
        assert!(a.take(WINDOW_NS + 99).is_none());
        assert!(a.take(WINDOW_NS + 100).is_some());
    }
}
