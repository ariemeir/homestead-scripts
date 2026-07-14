import Foundation

/// docs/scannercam_spec.md §8.1 — the one endpoint that doesn't require auth
/// and exposes nothing sensitive.
enum HealthRoutes {
    struct HealthResponse: Encodable {
        let status: String
        let app: String
        let version: String
        let apiVersion: Int
        let serverTime: String

        enum CodingKeys: String, CodingKey {
            case status, app, version
            case apiVersion = "api_version"
            case serverTime = "server_time"
        }
    }

    static func register(on router: Router) {
        router.register("GET", "/api/v1/health", requiresAuth: false) { _ in
            .json(HealthResponse(
                status: "ok",
                app: "ScannerCam",
                version: "0.1.0",
                apiVersion: 1,
                serverTime: ISO8601.string(from: Date())
            ))
        }
    }
}
