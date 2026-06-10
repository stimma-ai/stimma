fn main() {
  // Rebuild when the build distribution changes so the compile-time
  // STIMMA_DISTRIBUTION constant in lib.rs stays accurate.
  println!("cargo:rerun-if-env-changed=STIMMA_DISTRIBUTION");
  tauri_build::build()
}
