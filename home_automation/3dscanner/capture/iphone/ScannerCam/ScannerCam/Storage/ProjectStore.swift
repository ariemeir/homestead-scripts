import Foundation

/// Resolves and creates the on-disk directory layout described in
/// docs/scannercam_spec.md §4.5:
///
///   Documents/ScannerCam/projects/<project_id>/{project.json,manifest.json,images/}
///
/// Filenames are frame-only (`frame_000034.jpg`) — see the §4.4 revision
/// note on why angle was dropped from the on-disk name.
enum ProjectStore {
    static var scannerCamRoot: URL {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        return documents.appendingPathComponent("ScannerCam", isDirectory: true)
    }

    static var projectsRoot: URL {
        scannerCamRoot.appendingPathComponent("projects", isDirectory: true)
    }

    static var appStateURL: URL {
        scannerCamRoot.appendingPathComponent("app_state.json")
    }

    static func directory(for projectID: String) -> URL {
        projectsRoot.appendingPathComponent(projectID, isDirectory: true)
    }

    static func imagesDirectory(for projectID: String) -> URL {
        directory(for: projectID).appendingPathComponent("images", isDirectory: true)
    }

    static func projectMetadataURL(for projectID: String) -> URL {
        directory(for: projectID).appendingPathComponent("project.json")
    }

    static func manifestURL(for projectID: String) -> URL {
        directory(for: projectID).appendingPathComponent("manifest.json")
    }

    static func filename(forFrame frame: Int) -> String {
        String(format: "frame_%06d.jpg", frame)
    }

    static func imageURL(for projectID: String, frame: Int) -> URL {
        imagesDirectory(for: projectID).appendingPathComponent(filename(forFrame: frame))
    }

    /// Creates the directory layout for a project if it doesn't already
    /// exist. Safe to call before every capture — matches §2.1 "automatic
    /// creation of a project on first capture".
    static func ensureProjectExists(_ projectID: String) throws {
        try FileManager.default.createDirectory(
            at: imagesDirectory(for: projectID),
            withIntermediateDirectories: true
        )
    }

    static func listProjectIDs() throws -> [String] {
        guard FileManager.default.fileExists(atPath: projectsRoot.path) else { return [] }
        return try FileManager.default.contentsOfDirectory(atPath: projectsRoot.path)
    }
}
