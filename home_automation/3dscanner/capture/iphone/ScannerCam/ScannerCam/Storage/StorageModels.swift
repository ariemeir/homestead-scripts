import Foundation

/// One entry in manifest.json (docs/scannercam_spec.md §4.7).
struct ManifestEntry: Codable {
    let frame: Int
    let angleDegrees: Double?
    let filename: String
    let capturedAt: Date
    let sizeBytes: Int
    let width: Int
    let height: Int
    let sha256: String

    enum CodingKeys: String, CodingKey {
        case frame
        case angleDegrees = "angle_degrees"
        case filename
        case capturedAt = "captured_at"
        case sizeBytes = "size_bytes"
        case width
        case height
        case sha256
    }
}

/// manifest.json. `image_count` is derived, not stored, so it can never
/// drift out of sync with `images.count`.
struct Manifest: Codable {
    var schemaVersion: Int = 1
    let projectID: String
    var images: [ManifestEntry]

    var imageCount: Int { images.count }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case projectID = "project_id"
        case imageCount = "image_count"
        case images
    }

    init(projectID: String, images: [ManifestEntry] = []) {
        self.projectID = projectID
        self.images = images
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decode(Int.self, forKey: .schemaVersion)
        projectID = try container.decode(String.self, forKey: .projectID)
        images = try container.decode([ManifestEntry].self, forKey: .images)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(projectID, forKey: .projectID)
        try container.encode(imageCount, forKey: .imageCount)
        try container.encode(images.sorted { $0.frame < $1.frame }, forKey: .images)
    }
}

enum DeviceStorage {
    static func freeBytes() -> Int64 {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let values = try? documents.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
        return values?.volumeAvailableCapacityForImportantUsage ?? 0
    }

    static func totalBytes() -> Int64 {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let values = try? documents.resourceValues(forKeys: [.volumeTotalCapacityKey])
        return Int64(values?.volumeTotalCapacity ?? 0)
    }
}
