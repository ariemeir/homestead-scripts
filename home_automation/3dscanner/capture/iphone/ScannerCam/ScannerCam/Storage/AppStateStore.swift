import Foundation

/// app_state.json: server settings and the recent request-id history used
/// for capture idempotency (docs/scannercam_spec.md §9).
struct AppStateFile: Codable {
    var apiServerEnabled: Bool = false
    var recentRequestIDs: [String: RequestRecord] = [:]

    enum CodingKeys: String, CodingKey {
        case apiServerEnabled = "api_server_enabled"
        case recentRequestIDs = "recent_request_ids"
    }
}

enum AppStateStore {
    private static let maxRetainedRequestIDs = 1000

    static func load() -> AppStateFile {
        guard let data = try? Data(contentsOf: ProjectStore.appStateURL) else {
            return AppStateFile()
        }
        return (try? JSONDecoder.scannerCam.decode(AppStateFile.self, from: data)) ?? AppStateFile()
    }

    static func save(_ state: AppStateFile) throws {
        var trimmed = state
        if trimmed.recentRequestIDs.count > maxRetainedRequestIDs {
            // Dictionary iteration order isn't insertion order, so this
            // doesn't evict the strictly *oldest* entries — good enough to
            // bound memory/disk for MVP. Revisit with an ordered structure
            // if exact LRU eviction ends up mattering.
            let overflow = trimmed.recentRequestIDs.count - maxRetainedRequestIDs
            for key in trimmed.recentRequestIDs.keys.prefix(overflow) {
                trimmed.recentRequestIDs.removeValue(forKey: key)
            }
        }
        let data = try JSONEncoder.scannerCam.encode(trimmed)
        try FileManager.default.createDirectory(
            at: ProjectStore.scannerCamRoot,
            withIntermediateDirectories: true
        )
        try AtomicFileWriter.write(data, to: ProjectStore.appStateURL)
    }
}
