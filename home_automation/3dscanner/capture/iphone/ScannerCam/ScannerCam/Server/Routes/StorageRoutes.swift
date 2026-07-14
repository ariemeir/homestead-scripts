import Foundation

/// docs/scannercam_spec.md §8.12.
enum StorageRoutes {
    struct StorageResponse: Encodable {
        let projectCount: Int
        let imageCount: Int
        let scannerDataBytes: Int64
        let deviceFreeBytes: Int64
        let deviceTotalBytes: Int64

        enum CodingKeys: String, CodingKey {
            case projectCount = "project_count"
            case imageCount = "image_count"
            case scannerDataBytes = "scanner_data_bytes"
            case deviceFreeBytes = "device_free_bytes"
            case deviceTotalBytes = "device_total_bytes"
        }
    }

    static func register(on router: Router) {
        router.register("GET", "/api/v1/storage") { _ in
            let totals = StorageSummary.current()
            return .json(StorageResponse(
                projectCount: totals.projectCount,
                imageCount: totals.imageCount,
                scannerDataBytes: totals.usedBytes,
                deviceFreeBytes: DeviceStorage.freeBytes(),
                deviceTotalBytes: DeviceStorage.totalBytes()
            ))
        }
    }
}
