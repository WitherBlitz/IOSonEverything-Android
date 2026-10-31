// SPDX-License-Identifier: AGPL-3.0-or-later
//! Bounded wire representation of MTLVertexDescriptor; no device effects while decoding.
use crate::{fault, wire::{Reader, MAX_BINDINGS}, Result};
use metal2vulkan::{metal::{VertexFormat, VertexStepFunction}, pipeline::{VertexDescriptor, VertexAttributeDescriptor, VertexBufferLayoutDescriptor}};

pub fn decode(reader: &mut Reader<'_>) -> Result<VertexDescriptor> {
    let mut descriptor = VertexDescriptor::new();
    let count = reader.u32().map_err(fault)?;
    if count > MAX_BINDINGS { return Err("quota:vertex-attributes".into()); }
    for _ in 0..count {
        let index = reader.u32().map_err(fault)?;
        let raw = reader.u32().map_err(fault)?;
        let offset = reader.u64().map_err(fault)?;
        let buffer = reader.u32().map_err(fault)?;
        if index >= MAX_BINDINGS || buffer >= MAX_BINDINGS { return Err("invalid:vertex-attribute-index".into()); }
        let format = VertexFormat::try_from(raw).map_err(|e| e.to_string())?;
        let offset = u32::try_from(offset).map_err(|_| "invalid:vertex-attribute-offset")?;
        if descriptor.attributes.insert(index, VertexAttributeDescriptor::new(format, offset, buffer)).is_some() {
            return Err("invalid:duplicate-vertex-attribute".into());
        }
    }
    let count = reader.u32().map_err(fault)?;
    if count > MAX_BINDINGS { return Err("quota:vertex-layouts".into()); }
    for _ in 0..count {
        let index = reader.u32().map_err(fault)?;
        let stride = reader.u64().map_err(fault)?;
        let step = reader.u32().map_err(fault)?;
        let rate = reader.u64().map_err(fault)?;
        if index >= MAX_BINDINGS { return Err("invalid:vertex-layout-index".into()); }
        let stride = u32::try_from(stride).map_err(|_| "unsupported:dynamic-or-wide-vertex-stride")?;
        let rate = u32::try_from(rate).map_err(|_| "invalid:vertex-step-rate")?;
        let mut layout = VertexBufferLayoutDescriptor::new(Some(stride));
        layout.step_function = VertexStepFunction::try_from(step).map_err(|e| e.to_string())?;
        layout.step_rate = rate;
        if descriptor.layouts.insert(index, layout).is_some() { return Err("invalid:duplicate-vertex-layout".into()); }
    }
    Ok(descriptor)
}
