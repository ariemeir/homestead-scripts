import AVFoundation
import Foundation

enum CameraError: Error {
    case deviceUnavailable
    case notAuthorized
    case captureInProgress
    case emptyPhotoData
    case captureFailed(Error)
    case configurationFailed(Error)
}

struct CameraStatusSnapshot {
    let authorized: Bool
    let sessionRunning: Bool
    let position: String
    let deviceType: String
    let zoomFactor: Double
    let orientation: String
    let photoWidth: Int
    let photoHeight: Int
    let focusMode: String
    let focusLensPosition: Float
    let focusAdjusting: Bool
    let exposureMode: String
    let exposureTargetBias: Float
    let exposureDurationSeconds: Double
    let exposureISO: Float
    let exposureTargetOffset: Float
    let exposureAdjusting: Bool
    let whiteBalanceMode: String
    let whiteBalanceAdjusting: Bool
}

/// Owns the AVCaptureSession lifecycle: device selection, focus/exposure
/// locking, and single-photo capture. All session mutation happens on
/// `sessionQueue`, matching docs/scannercam_spec.md §12 ("camera session
/// changes never occur concurrently with capture").
final class CameraController: NSObject {
    private let session = AVCaptureSession()
    private let photoOutput = AVCapturePhotoOutput()
    private let sessionQueue = DispatchQueue(label: "com.ariemeir.ScannerCam.camera.session")

    private var device: AVCaptureDevice?
    private var activeProcessor: PhotoCaptureProcessor?

    var configuration = CameraConfiguration()

    var captureSession: AVCaptureSession { session }

    /// True once a physical device has been successfully configured.
    var isReady: Bool { sessionQueue.sync { device != nil } }

    var isCaptureInProgress: Bool { sessionQueue.sync { activeProcessor != nil } }

    var isFullyLocked: Bool {
        sessionQueue.sync {
            guard let device else { return false }
            return device.focusMode == .locked
                && device.exposureMode == .locked
                && device.whiteBalanceMode == .locked
        }
    }

    // MARK: - Session configuration (docs/scannercam_spec.md §5.1-5.2)

    func configureSession(completion: @escaping (Result<Void, CameraError>) -> Void) {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            sessionQueue.async { [weak self] in self?.performConfiguration(completion: completion) }
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                guard let self else { return }
                guard granted else {
                    completion(.failure(.notAuthorized))
                    return
                }
                self.sessionQueue.async { self.performConfiguration(completion: completion) }
            }
        case .denied, .restricted:
            completion(.failure(.notAuthorized))
        @unknown default:
            completion(.failure(.notAuthorized))
        }
    }

    /// Discovers the rear wide camera only (docs/scannercam_spec.md §5.1: no
    /// front/ultra-wide/digital zoom/automatic lens switching), configures
    /// the session for full-resolution 4:3 stills, and applies the fixed
    /// output orientation.
    private func performConfiguration(completion: @escaping (Result<Void, CameraError>) -> Void) {
        guard let discovered = AVCaptureDevice.default(
            configuration.deviceType,
            for: .video,
            position: configuration.position
        ) else {
            completion(.failure(.deviceUnavailable))
            return
        }

        session.beginConfiguration()

        do {
            let input = try AVCaptureDeviceInput(device: discovered)
            guard session.canAddInput(input) else {
                session.commitConfiguration()
                completion(.failure(.deviceUnavailable))
                return
            }
            session.inputs.forEach { session.removeInput($0) }
            session.addInput(input)
        } catch {
            session.commitConfiguration()
            completion(.failure(.configurationFailed(error)))
            return
        }

        if !session.outputs.contains(photoOutput) {
            guard session.canAddOutput(photoOutput) else {
                session.commitConfiguration()
                completion(.failure(.deviceUnavailable))
                return
            }
            session.addOutput(photoOutput)
        }

        session.sessionPreset = .photo
        photoOutput.maxPhotoQualityPrioritization = .quality
        if let maxDimensions = Self.largestDimensions(discovered.activeFormat.supportedMaxPhotoDimensions) {
            photoOutput.maxPhotoDimensions = maxDimensions
        }

        if let connection = photoOutput.connection(with: .video) {
            let angle = Self.rotationAngle(for: configuration.orientation)
            if connection.isVideoRotationAngleSupported(angle) {
                connection.videoRotationAngle = angle
            }
        }

        session.commitConfiguration()
        device = discovered
        completion(.success(()))
    }

    /// Clockwise rotation (degrees) needed to make the video source upright,
    /// per the AVCaptureConnection.videoRotationAngle convention that
    /// replaced the deprecated videoOrientation API.
    private static func rotationAngle(for orientation: CaptureOrientation) -> CGFloat {
        switch orientation {
        case .portrait: return 90
        case .portraitUpsideDown: return 270
        case .landscapeLeft: return 180
        case .landscapeRight: return 0
        }
    }

    func startSession() {
        sessionQueue.async { [session] in
            guard !session.isRunning else { return }
            session.startRunning()
        }
    }

    func stopSession() {
        sessionQueue.async { [session] in
            guard session.isRunning else { return }
            session.stopRunning()
        }
    }

    // MARK: - Focus/exposure/white balance locking (docs/scannercam_spec.md §5.6)

    func lockFocus(completion: @escaping (Result<Void, CameraError>) -> Void = { _ in }) {
        mutateDevice(completion: completion) { device in
            if device.isFocusModeSupported(.locked) {
                device.focusMode = .locked
            }
        }
    }

    func lockExposure(completion: @escaping (Result<Void, CameraError>) -> Void = { _ in }) {
        mutateDevice(completion: completion) { device in
            if device.isExposureModeSupported(.locked) {
                device.exposureMode = .locked
            }
        }
    }

    func lockWhiteBalance(completion: @escaping (Result<Void, CameraError>) -> Void = { _ in }) {
        mutateDevice(completion: completion) { device in
            if device.isWhiteBalanceModeSupported(.locked) {
                device.whiteBalanceMode = .locked
            }
        }
    }

    func unlockAll(completion: @escaping (Result<Void, CameraError>) -> Void = { _ in }) {
        mutateDevice(completion: completion) { device in
            if device.isFocusModeSupported(.continuousAutoFocus) {
                device.focusMode = .continuousAutoFocus
            }
            if device.isExposureModeSupported(.continuousAutoExposure) {
                device.exposureMode = .continuousAutoExposure
            }
            if device.isWhiteBalanceModeSupported(.continuousAutoWhiteBalance) {
                device.whiteBalanceMode = .continuousAutoWhiteBalance
            }
        }
    }

    /// Returns focus to continuous auto without touching exposure/white
    /// balance (unlike `unlockAll`) — used when the UI's manual-focus slider
    /// is switched off.
    func unlockFocus(completion: @escaping (Result<Void, CameraError>) -> Void = { _ in }) {
        mutateDevice(completion: completion) { device in
            if device.isFocusModeSupported(.continuousAutoFocus) {
                device.focusMode = .continuousAutoFocus
            }
        }
    }

    /// Tap-to-focus: sets a one-shot autofocus/autoexpose point
    /// (docs/scannercam_spec.md §10.1: "Tapping the preview sets focus/
    /// exposure point before locking"). `point` is in device coordinates —
    /// (0,0) top-left to (1,1) bottom-right of the sensor's un-rotated
    /// frame, as produced by
    /// `AVCaptureVideoPreviewLayer.captureDevicePointConverted(fromLayerPoint:)`.
    func focusAndExpose(at point: CGPoint, completion: @escaping (Result<Void, CameraError>) -> Void = { _ in }) {
        mutateDevice(completion: completion) { device in
            if device.isFocusPointOfInterestSupported {
                device.focusPointOfInterest = point
            }
            if device.isFocusModeSupported(.autoFocus) {
                device.focusMode = .autoFocus
            }
            if device.isExposurePointOfInterestSupported {
                device.exposurePointOfInterest = point
            }
            if device.isExposureModeSupported(.autoExpose) {
                device.exposureMode = .autoExpose
            }
        }
    }

    /// Valid range for `setExposureBias`. Falls back to a conservative
    /// default when no device is configured yet.
    var exposureBiasRange: ClosedRange<Float> {
        sessionQueue.sync {
            guard let device, device.minExposureTargetBias <= device.maxExposureTargetBias else {
                return -2...2
            }
            return device.minExposureTargetBias...device.maxExposureTargetBias
        }
    }

    func setExposureBias(_ bias: Float, completion: @escaping (Result<Void, CameraError>) -> Void = { _ in }) {
        mutateDevice(completion: completion) { device in
            let clamped = min(max(bias, device.minExposureTargetBias), device.maxExposureTargetBias)
            device.setExposureTargetBias(clamped)
        }
    }

    /// Sets a fixed manual lens position (0 = nearest focus, 1 = farthest)
    /// and locks focus there — the "Optional manual focus slider where
    /// supported" from docs/scannercam_spec.md §5.6.
    func setFocusLensPosition(_ position: Float, completion: @escaping (Result<Void, CameraError>) -> Void = { _ in }) {
        mutateDevice(completion: completion) { device in
            guard device.isLockingFocusWithCustomLensPositionSupported else { return }
            let clamped = min(max(position, 0), 1)
            device.setFocusModeLocked(lensPosition: clamped)
        }
    }

    private func mutateDevice(
        completion: @escaping (Result<Void, CameraError>) -> Void,
        _ body: @escaping (AVCaptureDevice) -> Void
    ) {
        sessionQueue.async { [weak self] in
            guard let self, let device = self.device else {
                completion(.failure(.deviceUnavailable))
                return
            }
            do {
                try device.lockForConfiguration()
                body(device)
                device.unlockForConfiguration()
                completion(.success(()))
            } catch {
                completion(.failure(.configurationFailed(error)))
            }
        }
    }

    // MARK: - Status (docs/scannercam_spec.md §5.6, §8.2)

    func statusSnapshot() -> CameraStatusSnapshot {
        sessionQueue.sync {
            let dimensions = photoOutput.maxPhotoDimensions
            return CameraStatusSnapshot(
                authorized: AVCaptureDevice.authorizationStatus(for: .video) == .authorized,
                sessionRunning: session.isRunning,
                position: configuration.position == .front ? "front" : "back",
                deviceType: Self.shortDeviceTypeName(device?.deviceType),
                zoomFactor: Double(device?.videoZoomFactor ?? configuration.zoomFactor),
                orientation: configuration.orientation.rawValue,
                photoWidth: Int(dimensions.width),
                photoHeight: Int(dimensions.height),
                focusMode: device?.focusMode == .locked ? "locked" : "auto",
                focusLensPosition: device?.lensPosition ?? 0,
                focusAdjusting: device?.isAdjustingFocus ?? false,
                exposureMode: device?.exposureMode == .locked ? "locked" : "auto",
                exposureTargetBias: device?.exposureTargetBias ?? 0,
                exposureDurationSeconds: device.map { CMTimeGetSeconds($0.exposureDuration) } ?? 0,
                exposureISO: device?.iso ?? 0,
                exposureTargetOffset: device?.exposureTargetOffset ?? 0,
                exposureAdjusting: device?.isAdjustingExposure ?? false,
                whiteBalanceMode: device?.whiteBalanceMode == .locked ? "locked" : "auto",
                whiteBalanceAdjusting: device?.isAdjustingWhiteBalance ?? false
            )
        }
    }

    private static func largestDimensions(_ candidates: [CMVideoDimensions]) -> CMVideoDimensions? {
        var best: CMVideoDimensions?
        var bestArea = -1
        for candidate in candidates {
            let area = Int(candidate.width) * Int(candidate.height)
            if area > bestArea {
                bestArea = area
                best = candidate
            }
        }
        return best
    }

    private static func shortDeviceTypeName(_ type: AVCaptureDevice.DeviceType?) -> String {
        switch type {
        case .some(.builtInWideAngleCamera): return "builtInWideAngleCamera"
        case .some(let other): return other.rawValue
        case .none: return "unknown"
        }
    }

    // MARK: - Capture (docs/scannercam_spec.md §5.3, §5.5)

    /// Captures exactly one photo. Rejects with `.captureInProgress` if a
    /// capture is already in flight (only one capture at a time).
    func capturePhoto(completion: @escaping (Result<PhotoCaptureProcessor.CapturedPhoto, CameraError>) -> Void) {
        sessionQueue.async { [weak self] in
            guard let self else { return }
            guard self.activeProcessor == nil else {
                completion(.failure(.captureInProgress))
                return
            }
            guard self.device != nil else {
                completion(.failure(.deviceUnavailable))
                return
            }

            let settings = AVCapturePhotoSettings()
            settings.photoQualityPrioritization = .quality
            settings.flashMode = .off
            settings.maxPhotoDimensions = self.photoOutput.maxPhotoDimensions

            let processor = PhotoCaptureProcessor { [weak self] result in
                self?.sessionQueue.async {
                    self?.activeProcessor = nil
                }
                completion(result)
            }
            self.activeProcessor = processor
            self.photoOutput.capturePhoto(with: settings, delegate: processor)
        }
    }
}
