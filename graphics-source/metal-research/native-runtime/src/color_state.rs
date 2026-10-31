// SPDX-License-Identifier: AGPL-3.0-or-later
//! Owned descriptor values only; no GPU effects during wire parsing.
use crate::{fault, wire::Reader, Result};
use metal2vulkan::{metal::{BlendFactor, BlendOperation, ColorWriteMask, PixelFormat}, pipeline::ColorAttachmentDescriptor};

pub fn decode(reader: &mut Reader<'_>, format: PixelFormat) -> Result<ColorAttachmentDescriptor> {
    let enabled = match reader.u32().map_err(fault)? {
        0 => false, 1 => true, _ => return Err("invalid:blend-enabled".into()),
    };
    let mut color = ColorAttachmentDescriptor::new(format);
    color.blending_enabled = enabled;
    color.source_rgb_blend_factor = BlendFactor::try_from(reader.u32().map_err(fault)?).map_err(|e| e.to_string())?;
    color.destination_rgb_blend_factor = BlendFactor::try_from(reader.u32().map_err(fault)?).map_err(|e| e.to_string())?;
    color.rgb_blend_operation = BlendOperation::try_from(reader.u32().map_err(fault)?).map_err(|e| e.to_string())?;
    color.source_alpha_blend_factor = BlendFactor::try_from(reader.u32().map_err(fault)?).map_err(|e| e.to_string())?;
    color.destination_alpha_blend_factor = BlendFactor::try_from(reader.u32().map_err(fault)?).map_err(|e| e.to_string())?;
    color.alpha_blend_operation = BlendOperation::try_from(reader.u32().map_err(fault)?).map_err(|e| e.to_string())?;
    let mask = reader.u32().map_err(fault)?;
    if mask & !15 != 0 { return Err("invalid:color-write-mask".into()); }
    color.write_mask = ColorWriteMask::try_from(mask).map_err(|e| e.to_string())?;
    Ok(color)
}
