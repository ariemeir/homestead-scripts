import Foundation

enum ImageStoreError: Error {
    case frameAlreadyExists
}

enum ImageStore {
    /// Writes photo `data` for `frame` in `projectID`, honoring the
    /// existing-frame / overwrite semantics from
    /// docs/scannercam_spec.md §5.4. Does not touch the manifest — callers
    /// update it via ManifestStore after a successful write.
    static func writeImage(_ data: Data, projectID: String, frame: Int, overwrite: Bool) throws {
        let destination = ProjectStore.imageURL(for: projectID, frame: frame)

        if !overwrite, FileManager.default.fileExists(atPath: destination.path) {
            throw ImageStoreError.frameAlreadyExists
        }

        try AtomicFileWriter.write(data, to: destination, tempPrefix: ".pending_")
    }

    static func deleteImage(projectID: String, frame: Int) throws {
        try FileManager.default.removeItem(at: ProjectStore.imageURL(for: projectID, frame: frame))
    }

    /// Startup recovery per §11.3: remove any incomplete `.pending_*.jpg`
    /// files left behind by a capture that didn't finish (e.g. app was
    /// killed mid-write).
    static func cleanupPendingFiles() throws {
        let fileManager = FileManager.default
        guard let enumerator = fileManager.enumerator(
            at: ProjectStore.projectsRoot,
            includingPropertiesForKeys: nil
        ) else { return }

        for case let url as URL in enumerator where url.lastPathComponent.hasPrefix(".pending_") {
            try? fileManager.removeItem(at: url)
        }
    }
}
