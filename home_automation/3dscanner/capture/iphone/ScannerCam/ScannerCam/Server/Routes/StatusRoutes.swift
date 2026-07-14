import Foundation

/// docs/scannercam_spec.md §8.2.
enum StatusRoutes {
    struct StatusResponse: Encodable {
        struct Focus: Encodable {
            let mode: String
            let lensPosition: Float
            let adjusting: Bool
            enum CodingKeys: String, CodingKey {
                case mode
                case lensPosition = "lens_position"
                case adjusting
            }
        }
        struct Exposure: Encodable {
            let mode: String
            let durationSeconds: Double
            let iso: Float
            let targetOffset: Float
            let adjusting: Bool
            enum CodingKeys: String, CodingKey {
                case mode
                case durationSeconds = "duration_seconds"
                case iso
                case targetOffset = "target_offset"
                case adjusting
            }
        }
        struct WhiteBalance: Encodable {
            let mode: String
            let adjusting: Bool
            enum CodingKeys: String, CodingKey {
                case mode
                case adjusting
            }
        }
        struct PhotoDimensions: Encodable {
            let width: Int
            let height: Int
        }
        struct Camera: Encodable {
            let authorized: Bool
            let sessionRunning: Bool
            let position: String
            let deviceType: String
            let zoomFactor: Double
            let orientation: String
            let photoDimensions: PhotoDimensions
            let focus: Focus
            let exposure: Exposure
            let whiteBalance: WhiteBalance
            enum CodingKeys: String, CodingKey {
                case authorized
                case sessionRunning = "session_running"
                case position
                case deviceType = "device_type"
                case zoomFactor = "zoom_factor"
                case orientation
                case photoDimensions = "photo_dimensions"
                case focus, exposure
                case whiteBalance = "white_balance"
            }
        }
        struct Storage: Encodable {
            let projectCount: Int
            let imageCount: Int
            let usedBytes: Int64
            let freeBytes: Int64
            enum CodingKeys: String, CodingKey {
                case projectCount = "project_count"
                case imageCount = "image_count"
                case usedBytes = "used_bytes"
                case freeBytes = "free_bytes"
            }
        }
        struct Network: Encodable {
            let port: Int
            let bonjourName: String
            enum CodingKeys: String, CodingKey {
                case port
                case bonjourName = "bonjour_name"
            }
        }

        let status: String
        let captureInProgress: Bool
        let camera: Camera
        let storage: Storage
        let network: Network

        enum CodingKeys: String, CodingKey {
            case status
            case captureInProgress = "capture_in_progress"
            case camera, storage, network
        }
    }

    static func register(on router: Router, cameraController: CameraController) {
        router.register("GET", "/api/v1/status") { _ in
            let snapshot = cameraController.statusSnapshot()
            let totals = StorageSummary.current()

            let response = StatusResponse(
                status: cameraController.isReady ? "ready" : "degraded",
                captureInProgress: cameraController.isCaptureInProgress,
                camera: StatusResponse.Camera(
                    authorized: snapshot.authorized,
                    sessionRunning: snapshot.sessionRunning,
                    position: snapshot.position,
                    deviceType: snapshot.deviceType,
                    zoomFactor: snapshot.zoomFactor,
                    orientation: snapshot.orientation,
                    photoDimensions: StatusResponse.PhotoDimensions(width: snapshot.photoWidth, height: snapshot.photoHeight),
                    focus: StatusResponse.Focus(mode: snapshot.focusMode, lensPosition: snapshot.focusLensPosition, adjusting: snapshot.focusAdjusting),
                    exposure: StatusResponse.Exposure(
                        mode: snapshot.exposureMode,
                        durationSeconds: snapshot.exposureDurationSeconds,
                        iso: snapshot.exposureISO,
                        targetOffset: snapshot.exposureTargetOffset,
                        adjusting: snapshot.exposureAdjusting
                    ),
                    whiteBalance: StatusResponse.WhiteBalance(mode: snapshot.whiteBalanceMode, adjusting: snapshot.whiteBalanceAdjusting)
                ),
                storage: StatusResponse.Storage(
                    projectCount: totals.projectCount,
                    imageCount: totals.imageCount,
                    usedBytes: totals.usedBytes,
                    freeBytes: DeviceStorage.freeBytes()
                ),
                network: StatusResponse.Network(port: 8765, bonjourName: "ScannerCam-saru")
            )
            return .json(response)
        }
    }
}
