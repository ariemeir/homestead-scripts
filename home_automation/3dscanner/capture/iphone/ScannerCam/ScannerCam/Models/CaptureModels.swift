import Foundation

/// `POST /api/v1/captures` request body (docs/scannercam_spec.md §8.3).
struct CaptureRequest: Decodable {
    let projectID: String
    let frame: Int
    let angleDegrees: Double?
    let overwrite: Bool
    let requireLocks: Bool
    let requestID: String?

    enum CodingKeys: String, CodingKey {
        case projectID = "project_id"
        case frame
        case angleDegrees = "angle_degrees"
        case overwrite
        case requireLocks = "require_locks"
        case requestID = "request_id"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        projectID = try container.decode(String.self, forKey: .projectID)
        frame = try container.decode(Int.self, forKey: .frame)
        angleDegrees = try container.decodeIfPresent(Double.self, forKey: .angleDegrees)
        overwrite = try container.decodeIfPresent(Bool.self, forKey: .overwrite) ?? false
        requireLocks = try container.decodeIfPresent(Bool.self, forKey: .requireLocks) ?? false
        requestID = try container.decodeIfPresent(String.self, forKey: .requestID)
    }
}

/// `POST /api/v1/captures` success body. Also persisted (keyed by
/// `request_id`) in app_state.json for idempotent retries (§9), hence Codable
/// rather than just Encodable.
struct CaptureResponse: Codable {
    let status: String
    let requestID: String?
    let projectID: String
    let frame: Int
    let angleDegrees: Double?
    let filename: String
    let capturedAt: Date
    let width: Int
    let height: Int
    let sizeBytes: Int
    let sha256: String
    let overwritten: Bool
    let downloadURL: String

    enum CodingKeys: String, CodingKey {
        case status
        case requestID = "request_id"
        case projectID = "project_id"
        case frame
        case angleDegrees = "angle_degrees"
        case filename
        case capturedAt = "captured_at"
        case width
        case height
        case sizeBytes = "size_bytes"
        case sha256
        case overwritten
        case downloadURL = "download_url"
    }
}

/// The subset of a capture request that must match on retry for a
/// `request_id` to be treated as an idempotent replay rather than a
/// conflict (docs/scannercam_spec.md §9).
struct CaptureRequestFingerprint: Codable, Equatable {
    let projectID: String
    let frame: Int
    let angleDegrees: Double?
    let overwrite: Bool
    let requireLocks: Bool

    enum CodingKeys: String, CodingKey {
        case projectID = "project_id"
        case frame
        case angleDegrees = "angle_degrees"
        case overwrite
        case requireLocks = "require_locks"
    }
}

struct RequestRecord: Codable {
    let fingerprint: CaptureRequestFingerprint
    let response: CaptureResponse
}
