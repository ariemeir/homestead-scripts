import Foundation

/// Validates project_id against docs/scannercam_spec.md §4.1
/// (`^[A-Za-z0-9_-]{1,64}$` — see capture/protocols/constants.json).
struct ProjectID: RawRepresentable, Hashable, Codable {
    static let pattern = "^[A-Za-z0-9_-]{1,64}$"

    let rawValue: String

    init?(rawValue: String) {
        guard rawValue.range(of: Self.pattern, options: .regularExpression) != nil else {
            return nil
        }
        self.rawValue = rawValue
    }
}

struct DeviceInfo: Codable {
    let model: String
    let systemVersion: String

    enum CodingKeys: String, CodingKey {
        case model
        case systemVersion = "system_version"
    }
}

struct CameraInfo: Codable {
    let position: String
    let lens: String
    let requestedZoomFactor: Double
    let outputFormat: String
    let orientation: String

    enum CodingKeys: String, CodingKey {
        case position
        case lens
        case requestedZoomFactor = "requested_zoom_factor"
        case outputFormat = "output_format"
        case orientation
    }
}

/// project.json (docs/scannercam_spec.md §4.6).
struct ProjectMetadata: Codable {
    var schemaVersion: Int = 1
    let projectID: String
    let createdAt: Date
    var updatedAt: Date
    let device: DeviceInfo
    let camera: CameraInfo

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case projectID = "project_id"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case device
        case camera
    }
}
