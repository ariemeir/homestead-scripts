import AVFoundation
import Foundation

enum CaptureOrientation: String, Codable {
    case portrait
    case portraitUpsideDown
    case landscapeLeft
    case landscapeRight
}

/// docs/scannercam_spec.md §5.1/§5.7: fixed to the rear wide camera at 1x,
/// with one user-selected orientation held stable for a whole project.
struct CameraConfiguration {
    var position: AVCaptureDevice.Position = .back
    var deviceType: AVCaptureDevice.DeviceType = .builtInWideAngleCamera
    var zoomFactor: CGFloat = 1.0
    var orientation: CaptureOrientation = .landscapeRight
}
