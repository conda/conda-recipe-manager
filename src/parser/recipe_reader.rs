//!
//! Description: Rust implementation of a V1 recipe file parser
//!

mod enums

struct RecipeParser {
    content: str,
    is_modified: bool,
    schema_version: enums::SchemaVersion,
}
