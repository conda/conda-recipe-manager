//!
//! Description: Rust implementation of a V1 recipe file parser
//!

use crate::parser::enums::SchemaVersion;

pub struct RecipeReader {
    content: Box<str>,
    is_modified: bool,
    schema_version: SchemaVersion,
}

impl RecipeReader {
    /// Constructs a RecipeReader instance
    pub fn new(content: Box<str>) -> Self {
        RecipeReader {
            content: content,
            is_modified: false,
            // V0 is not supported by the rust formatter.
            schema_version: SchemaVersion::V1,
        }
    }
}
