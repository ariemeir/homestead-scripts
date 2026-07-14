import AVFoundation
import Foundation

/// One instance per capture, matching Apple's AVCapturePhotoCaptureDelegate
/// pattern: a fresh AVCapturePhotoSettings + delegate for every single photo
/// (docs/scannercam_spec.md §1, §5.3).
final class PhotoCaptureProcessor: NSObject, AVCapturePhotoCaptureDelegate {
    struct CapturedPhoto {
        let data: Data
        let width: Int
        let height: Int
    }

    private let completion: (Result<CapturedPhoto, CameraError>) -> Void

    init(completion: @escaping (Result<CapturedPhoto, CameraError>) -> Void) {
        self.completion = completion
    }

    func photoOutput(
        _ output: AVCapturePhotoOutput,
        didFinishProcessingPhoto photo: AVCapturePhoto,
        error: Error?
    ) {
        if let error {
            completion(.failure(.captureFailed(error)))
            return
        }
        guard let data = photo.fileDataRepresentation(), !data.isEmpty else {
            completion(.failure(.emptyPhotoData))
            return
        }
        let dimensions = photo.resolvedSettings.photoDimensions
        completion(.success(CapturedPhoto(
            data: data,
            width: Int(dimensions.width),
            height: Int(dimensions.height)
        )))
    }
}
