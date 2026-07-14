import Foundation
import UIKit

enum ProjectMetadataStore {
    static func load(projectID: String) -> ProjectMetadata? {
        guard let data = try? Data(contentsOf: ProjectStore.projectMetadataURL(for: projectID)) else {
            return nil
        }
        return try? JSONDecoder.scannerCam.decode(ProjectMetadata.self, from: data)
    }

    static func save(_ metadata: ProjectMetadata) throws {
        let data = try JSONEncoder.scannerCam.encode(metadata)
        try AtomicFileWriter.write(data, to: ProjectStore.projectMetadataURL(for: metadata.projectID))
    }

    /// Creates project.json on first capture, otherwise bumps `updated_at`
    /// (docs/scannercam_spec.md §2.1, §4.6).
    static func touch(projectID: String, cameraConfiguration: CameraConfiguration) throws {
        let now = Date()
        if var existing = load(projectID: projectID) {
            existing.updatedAt = now
            try save(existing)
        } else {
            let metadata = ProjectMetadata(
                projectID: projectID,
                createdAt: now,
                updatedAt: now,
                device: DeviceInfo(
                    model: UIDevice.current.model,
                    systemVersion: UIDevice.current.systemVersion
                ),
                camera: CameraInfo(
                    position: cameraConfiguration.position == .front ? "front" : "back",
                    lens: "wide",
                    requestedZoomFactor: Double(cameraConfiguration.zoomFactor),
                    outputFormat: "jpeg",
                    orientation: cameraConfiguration.orientation.rawValue
                )
            )
            try save(metadata)
        }
    }
}
