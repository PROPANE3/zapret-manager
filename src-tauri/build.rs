fn main() {
    tauri_build::build();
    // UAC ставится пост-шагом stamp-manifest.bat (см. beforeBundleCommand):
    // полный манифест в линковку дублировал rustc-default (CVT1100),
    // а /MANIFESTUAC линковщик молча игнорировал.
}
