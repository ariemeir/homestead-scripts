import Combine
import Foundation
import UIKit

@MainActor
final class AppState: ObservableObject {
    @Published var serverRunning = false
    @Published var focusLocked = false
    @Published var exposureLocked = false
    @Published var whiteBalanceLocked = false
    @Published var projectCount = 0
    @Published var imageCount = 0

    let cameraController = CameraController()
    private var httpServer: HTTPServer?

    /// Cleans up any incomplete captures from a previous run (§11.3), brings
    /// up the camera session, then starts the HTTP server regardless of
    /// whether the camera configured successfully — `/health` should work
    /// even if the camera isn't ready, and capture requests will fail
    /// cleanly with `camera_unavailable` in that case.
    func bootstrap() {
        try? ImageStore.cleanupPendingFiles()
        cameraController.configureSession { [weak self] result in
            if case .failure(let error) = result {
                ScannerCamLog.camera.error("camera configuration failed: \(String(describing: error))")
            } else {
                self?.cameraController.startSession()
            }
            DispatchQueue.main.async {
                self?.startServer()
            }
        }
    }

    func startServer() {
        let router = Router()
        HealthRoutes.register(on: router)
        StatusRoutes.register(on: router, cameraController: cameraController)
        CaptureRoutes.register(on: router, cameraController: cameraController)
        ProjectRoutes.register(on: router)
        StorageRoutes.register(on: router)

        let server = HTTPServer(router: router)
        do {
            try server.start(port: 8765)
            httpServer = server
            serverRunning = true
            // docs/scannercam_spec.md §11.2: the server only runs while the
            // app is foreground-active, so letting the screen auto-lock
            // mid-scan silently kills it. Restored when the server stops.
            UIApplication.shared.isIdleTimerDisabled = true
        } catch {
            ScannerCamLog.server.error("failed to start server: \(error.localizedDescription)")
            serverRunning = false
        }
    }

    func stopServer() {
        httpServer?.stop()
        httpServer = nil
        serverRunning = false
        UIApplication.shared.isIdleTimerDisabled = false
    }
}
