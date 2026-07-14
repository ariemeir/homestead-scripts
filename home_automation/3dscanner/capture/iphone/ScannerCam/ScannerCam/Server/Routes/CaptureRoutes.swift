import Foundation

/// docs/scannercam_spec.md §5.3, §5.4, §5.5, §8.3, §9.
enum CaptureRoutes {
    static func register(on router: Router, cameraController: CameraController) {
        router.register("POST", "/api/v1/captures") { request in
            handleCapture(request, cameraController: cameraController)
        }
    }

    // Blocks the server's single request-handling queue for the duration of
    // the capture (bridging the async AVFoundation callback via a
    // semaphore). That's a deliberate simplification, not an oversight: the
    // server has no persistent connections and processes one request at a
    // time anyway (docs/scannercam_spec.md §6.1), and only one capture may
    // run at a time regardless (§5.5) — so this doesn't give up any real
    // concurrency, it just makes the existing serialization explicit in the
    // code. Revisit if/when the server gets a genuine concurrent request
    // model.
    private static func handleCapture(_ request: HTTPRequest, cameraController: CameraController) -> HTTPResponse {
        guard let captureRequest = try? JSONDecoder.scannerCam.decode(CaptureRequest.self, from: request.body) else {
            return .error(code: "invalid_request", message: "Malformed capture request body.", status: 400)
        }

        guard ProjectID(rawValue: captureRequest.projectID) != nil else {
            return .error(
                code: "invalid_project_id",
                message: "project_id must match \(ProjectID.pattern).",
                status: 400
            )
        }
        guard APIConstants.frameRange.contains(captureRequest.frame) else {
            return .error(
                code: "invalid_frame",
                message: "frame must be between \(APIConstants.frameRange.lowerBound) and \(APIConstants.frameRange.upperBound).",
                status: 400
            )
        }
        if let angle = captureRequest.angleDegrees, !APIConstants.angleRange.contains(angle) {
            return .error(code: "invalid_angle", message: "angle_degrees must be in [0, 360).", status: 400)
        }

        let fingerprint = CaptureRequestFingerprint(
            projectID: captureRequest.projectID,
            frame: captureRequest.frame,
            angleDegrees: captureRequest.angleDegrees,
            overwrite: captureRequest.overwrite,
            requireLocks: captureRequest.requireLocks
        )

        if let requestID = captureRequest.requestID {
            let state = AppStateStore.load()
            if let previous = state.recentRequestIDs[requestID] {
                if previous.fingerprint == fingerprint {
                    return .json(previous.response, status: 201)
                }
                return .error(
                    code: "request_id_conflict",
                    message: "request_id was already used with different capture parameters.",
                    status: 409
                )
            }
        }

        guard cameraController.isReady else {
            return .error(code: "camera_unavailable", message: "Camera is not configured.", status: 423)
        }

        if captureRequest.requireLocks, !cameraController.isFullyLocked {
            return .error(
                code: "camera_not_locked",
                message: "require_locks was set but focus/exposure/white balance are not all locked.",
                status: 409
            )
        }

        if DeviceStorage.freeBytes() < APIConstants.minFreeBytesBeforeCapture {
            return .error(code: "insufficient_storage", message: "Less than 250MB of free space remains.", status: 507)
        }

        do {
            try ProjectStore.ensureProjectExists(captureRequest.projectID)
        } catch {
            return .error(code: "file_write_failed", message: "Could not create project directory: \(error)", status: 500)
        }

        let destination = ProjectStore.imageURL(for: captureRequest.projectID, frame: captureRequest.frame)
        let frameAlreadyExists = FileManager.default.fileExists(atPath: destination.path)
        if frameAlreadyExists, !captureRequest.overwrite {
            return .error(code: "frame_exists", message: "Frame \(captureRequest.frame) already exists.", status: 409)
        }

        let semaphore = DispatchSemaphore(value: 0)
        var captureOutcome: Result<PhotoCaptureProcessor.CapturedPhoto, CameraError>?
        cameraController.capturePhoto { result in
            captureOutcome = result
            semaphore.signal()
        }
        // Bounded wait: if AVFoundation never delivers the photo (camera stall,
        // thermal throttle), return an error instead of blocking this
        // connection's thread forever. Per-connection queues already keep such
        // a stall from wedging the whole server, but this bounds it further.
        if semaphore.wait(timeout: .now() + 25) == .timedOut {
            return .error(code: "capture_failed", message: "Capture timed out.", status: 500)
        }

        let photo: PhotoCaptureProcessor.CapturedPhoto
        switch captureOutcome {
        case .success(let capturedPhoto):
            photo = capturedPhoto
        case .failure(.captureInProgress):
            return .error(code: "capture_in_progress", message: "Another capture is currently in progress.", status: 409)
        case .failure(let error):
            return .error(code: "capture_failed", message: "\(String(describing: error))", status: 500)
        case .none:
            return .error(code: "capture_failed", message: "No capture result.", status: 500)
        }

        do {
            try ImageStore.writeImage(
                photo.data,
                projectID: captureRequest.projectID,
                frame: captureRequest.frame,
                overwrite: captureRequest.overwrite
            )
        } catch ImageStoreError.frameAlreadyExists {
            return .error(code: "frame_exists", message: "Frame \(captureRequest.frame) already exists.", status: 409)
        } catch {
            return .error(code: "file_write_failed", message: "\(error)", status: 500)
        }

        let sha256 = SHA256Hasher.hexDigest(of: photo.data)
        let capturedAt = Date()
        let filename = ProjectStore.filename(forFrame: captureRequest.frame)

        let entry = ManifestEntry(
            frame: captureRequest.frame,
            angleDegrees: captureRequest.angleDegrees,
            filename: filename,
            capturedAt: capturedAt,
            sizeBytes: photo.data.count,
            width: photo.width,
            height: photo.height,
            sha256: sha256
        )

        do {
            try ManifestStore.upsert(entry, projectID: captureRequest.projectID)
        } catch {
            return .error(code: "file_write_failed", message: "\(error)", status: 500)
        }

        try? ProjectMetadataStore.touch(projectID: captureRequest.projectID, cameraConfiguration: cameraController.configuration)

        let response = CaptureResponse(
            status: "captured",
            requestID: captureRequest.requestID,
            projectID: captureRequest.projectID,
            frame: captureRequest.frame,
            angleDegrees: captureRequest.angleDegrees,
            filename: filename,
            capturedAt: capturedAt,
            width: photo.width,
            height: photo.height,
            sizeBytes: photo.data.count,
            sha256: sha256,
            overwritten: frameAlreadyExists && captureRequest.overwrite,
            downloadURL: "/api/v1/projects/\(captureRequest.projectID)/images/\(captureRequest.frame)"
        )

        if let requestID = captureRequest.requestID {
            var state = AppStateStore.load()
            state.recentRequestIDs[requestID] = RequestRecord(fingerprint: fingerprint, response: response)
            try? AppStateStore.save(state)
        }

        return .json(response, status: 201)
    }
}
