// SPDX-License-Identifier: AGPL-3.0-or-later
//! Container validation must precede any runtime artifact-cache lookup.
use metal2vulkan_air::{budget::{Budget,Meter},container::{self,Library,LibraryType,FunctionStage}};
use std::time::{Duration,Instant};
pub fn validate(data: &[u8]) -> Result<(), String> {
    if data.is_empty() || data.len()>8*1024*1024 { return Err("quota:shader-bytes".into()); }
    let budget=Budget::with_deadline(Some(Instant::now()+Duration::from_secs(8)));
    let mut meter=Meter::new(&budget);
    let parsed=container::parse(data).map_err(|e|e.to_string())?;
    meter.tick(1).map_err(|e|e.to_string())?;
    let Library::Metallib(library)=parsed else { return Err("invalid:expected-metallib".into()); };
    if library.library_type()!=LibraryType::Executable { return Err("unsupported:dynamic-library".into()); }
    for function in &library.functions {
        if !matches!(function.stage,FunctionStage::Kernel|FunctionStage::Vertex|FunctionStage::Fragment) {
            return Err("unsupported:metallib-function-stage".into());
        }
        let mut decoded=metal2vulkan_air::decode(function.bitcode,&mut meter).map_err(|e|e.to_string())?;
        decoded.abi.check_container(&decoded.module,function,&mut meter).map_err(|e|e.to_string())?;
    }
    Ok(())
}

#[cfg(test)]
#[path = "../tests/metallib-fixtures.rs"]
mod fixtures;
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accepts_valid_owned_container() {
        assert!(validate(fixtures::VALID).is_ok());
    }
    #[test]
    fn rejects_multi_entry_modules_before_a_cache_can_be_consulted() {
        let error=validate(fixtures::INVALID).expect_err("invalid container must not reach cache");
        assert!(error.contains("ContainerMismatch"), "{error}");
    }
}
