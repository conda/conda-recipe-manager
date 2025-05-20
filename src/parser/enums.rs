//!
//! Description: Enums common to the parser module.
//!

/// Indicates the schema of the current recipe file.
/// NOTE: The Rust parser only supports V1 recipes.
enum SchemaVersion {
    V0,
    V1,
}
