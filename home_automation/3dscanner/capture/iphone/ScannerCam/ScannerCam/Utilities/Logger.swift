import os

enum ScannerCamLog {
    static let capture = Logger(subsystem: "com.ariemeir.ScannerCam", category: "capture")
    static let server = Logger(subsystem: "com.ariemeir.ScannerCam", category: "server")
    static let storage = Logger(subsystem: "com.ariemeir.ScannerCam", category: "storage")
    static let camera = Logger(subsystem: "com.ariemeir.ScannerCam", category: "camera")
}

// TODO: mirror events into the rolling on-disk diagnostic log described in
// docs/scannercam_spec.md §13 (5 MB / 10 file cap, exposed via
// GET /api/v1/logs/recent). os.Logger alone isn't queryable over the API.
