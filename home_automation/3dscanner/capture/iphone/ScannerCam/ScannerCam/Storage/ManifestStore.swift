import Foundation

enum ManifestStore {
    static func load(projectID: String) throws -> Manifest {
        let url = ProjectStore.manifestURL(for: projectID)
        guard FileManager.default.fileExists(atPath: url.path) else {
            return Manifest(projectID: projectID)
        }
        let data = try Data(contentsOf: url)
        return try JSONDecoder.scannerCam.decode(Manifest.self, from: data)
    }

    /// Rewrites manifest.json atomically (temp file + rename), per
    /// docs/scannercam_spec.md §12.
    static func save(_ manifest: Manifest) throws {
        let data = try JSONEncoder.scannerCam.encode(manifest)
        try AtomicFileWriter.write(data, to: ProjectStore.manifestURL(for: manifest.projectID))
    }

    static func upsert(_ entry: ManifestEntry, projectID: String) throws {
        var manifest = try load(projectID: projectID)
        manifest.images.removeAll { $0.frame == entry.frame }
        manifest.images.append(entry)
        try save(manifest)
    }

    static func remove(frame: Int, projectID: String) throws {
        var manifest = try load(projectID: projectID)
        manifest.images.removeAll { $0.frame == frame }
        try save(manifest)
    }
}
