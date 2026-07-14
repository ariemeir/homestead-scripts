import Foundation

/// Shared by StatusRoutes, StorageRoutes, and the on-device UI so project/
/// image totals are computed the same way everywhere.
enum StorageSummary {
    struct Totals {
        let projectCount: Int
        let imageCount: Int
        let usedBytes: Int64
    }

    static func current() -> Totals {
        let projectIDs = (try? ProjectStore.listProjectIDs()) ?? []
        var imageCount = 0
        var usedBytes: Int64 = 0
        for projectID in projectIDs {
            guard let manifest = try? ManifestStore.load(projectID: projectID) else { continue }
            imageCount += manifest.imageCount
            usedBytes += manifest.images.reduce(0) { $0 + Int64($1.sizeBytes) }
        }
        return Totals(projectCount: projectIDs.count, imageCount: imageCount, usedBytes: usedBytes)
    }
}
