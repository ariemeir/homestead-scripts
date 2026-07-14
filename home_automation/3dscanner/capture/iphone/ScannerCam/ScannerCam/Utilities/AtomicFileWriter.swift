import Foundation

enum AtomicFileWriter {
    /// Writes `data` to a temporary sibling file, then renames it over
    /// `destination`. The rename is atomic on APFS, so `destination` never
    /// observably contains partial content (docs/scannercam_spec.md §12).
    ///
    /// `tempPrefix` matters for image writes specifically: the startup
    /// recovery scan (§11.3) looks for `.pending_*.jpg` files left behind by
    /// a capture that didn't finish. Manifest/app-state writes use the
    /// default prefix since they're recovered by full rebuild, not by
    /// filename convention.
    static func write(_ data: Data, to destination: URL, tempPrefix: String = ".tmp_") throws {
        let ext = destination.pathExtension
        let tempName = "\(tempPrefix)\(UUID().uuidString)\(ext.isEmpty ? "" : "." + ext)"
        let tempURL = destination.deletingLastPathComponent().appendingPathComponent(tempName)

        try data.write(to: tempURL)
        _ = try FileManager.default.replaceItemAt(destination, withItemAt: tempURL)
    }
}
