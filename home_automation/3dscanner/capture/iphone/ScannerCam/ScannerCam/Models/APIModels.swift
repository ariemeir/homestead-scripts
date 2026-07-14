import Foundation

struct APIError: Encodable {
    struct Body: Encodable {
        let code: String
        let message: String
    }
    let error: Body

    static func make(code: String, message: String) -> APIError {
        APIError(error: Body(code: code, message: message))
    }
}

/// Mirrors capture/protocols/constants.json — keep in sync.
enum APIConstants {
    static let minFreeBytesBeforeCapture: Int64 = 262_144_000
    static let imagesListDefaultLimit = 100
    static let imagesListMaxLimit = 500
    static let frameRange = 0...999_999
    static let angleRange: Range<Double> = 0.0..<360.0
}

/// Mirrors capture/protocols/constants.json `error_codes` — keep in sync.
enum APIErrorCode: String {
    case invalidRequest = "invalid_request"
    case invalidProjectID = "invalid_project_id"
    case invalidFrame = "invalid_frame"
    case invalidAngle = "invalid_angle"
    case unauthorized
    case captureInProgress = "capture_in_progress"
    case frameExists = "frame_exists"
    case cameraNotLocked = "camera_not_locked"
    case requestIDConflict = "request_id_conflict"
    case cameraUnavailable = "camera_unavailable"
    case insufficientStorage = "insufficient_storage"
    case captureFailed = "capture_failed"
    case fileWriteFailed = "file_write_failed"
    case notFound = "not_found"
}
