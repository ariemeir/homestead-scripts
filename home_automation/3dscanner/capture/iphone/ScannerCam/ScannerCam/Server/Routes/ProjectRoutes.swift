import Foundation

/// docs/scannercam_spec.md §8.4-8.11.
enum ProjectRoutes {
    struct ProjectSummary: Encodable {
        let projectID: String
        let createdAt: Date
        let updatedAt: Date
        let imageCount: Int
        let sizeBytes: Int64

        enum CodingKeys: String, CodingKey {
            case projectID = "project_id"
            case createdAt = "created_at"
            case updatedAt = "updated_at"
            case imageCount = "image_count"
            case sizeBytes = "size_bytes"
        }
    }

    struct ProjectListResponse: Encodable {
        let projects: [ProjectSummary]
    }

    struct ProjectDetailResponse: Encodable {
        let projectID: String
        let createdAt: Date
        let updatedAt: Date
        let imageCount: Int
        let sizeBytes: Int64
        let minimumFrame: Int?
        let maximumFrame: Int?
        let missingFrames: [Int]
        let manifestURL: String
        let imagesURL: String

        enum CodingKeys: String, CodingKey {
            case projectID = "project_id"
            case createdAt = "created_at"
            case updatedAt = "updated_at"
            case imageCount = "image_count"
            case sizeBytes = "size_bytes"
            case minimumFrame = "minimum_frame"
            case maximumFrame = "maximum_frame"
            case missingFrames = "missing_frames"
            case manifestURL = "manifest_url"
            case imagesURL = "images_url"
        }
    }

    struct ImageSummary: Encodable {
        let frame: Int
        let angleDegrees: Double?
        let filename: String
        let capturedAt: Date
        let width: Int
        let height: Int
        let sizeBytes: Int
        let sha256: String
        let downloadURL: String

        enum CodingKeys: String, CodingKey {
            case frame
            case angleDegrees = "angle_degrees"
            case filename
            case capturedAt = "captured_at"
            case width, height
            case sizeBytes = "size_bytes"
            case sha256
            case downloadURL = "download_url"
        }
    }

    struct ImageListResponse: Encodable {
        let projectID: String
        let images: [ImageSummary]
        let nextAfterFrame: Int?
        let hasMore: Bool

        enum CodingKeys: String, CodingKey {
            case projectID = "project_id"
            case images
            case nextAfterFrame = "next_after_frame"
            case hasMore = "has_more"
        }
    }

    struct DeleteAllResponse: Encodable {
        let status: String
        let deletedProjects: Int
        let deletedImages: Int
        let freedBytes: Int64

        enum CodingKeys: String, CodingKey {
            case status
            case deletedProjects = "deleted_projects"
            case deletedImages = "deleted_images"
            case freedBytes = "freed_bytes"
        }
    }

    static func register(on router: Router) {
        router.register("GET", "/api/v1/projects") { _ in
            .json(ProjectListResponse(projects: allSummaries()))
        }

        router.register("GET", "/api/v1/projects/:project_id") { request in
            projectDetail(request)
        }

        router.register("GET", "/api/v1/projects/:project_id/manifest") { request in
            projectManifest(request)
        }

        router.register("GET", "/api/v1/projects/:project_id/images") { request in
            listImages(request)
        }

        router.register("GET", "/api/v1/projects/:project_id/images/:frame") { request in
            downloadResponse(request, includeBody: true)
        }

        router.register("HEAD", "/api/v1/projects/:project_id/images/:frame") { request in
            downloadResponse(request, includeBody: false)
        }

        router.register("DELETE", "/api/v1/projects/:project_id/images/:frame") { request in
            deleteImage(request)
        }

        router.register("DELETE", "/api/v1/projects/:project_id") { request in
            deleteProject(request)
        }

        router.register("DELETE", "/api/v1/projects") { request in
            deleteAllProjects(request)
        }
    }

    // MARK: - Handlers

    private static func projectDetail(_ request: HTTPRequest) -> HTTPResponse {
        guard let projectID = request.pathParameters["project_id"],
              FileManager.default.fileExists(atPath: ProjectStore.directory(for: projectID).path),
              let manifest = try? ManifestStore.load(projectID: projectID) else {
            return .error(code: "not_found", message: "Project not found.", status: 404)
        }
        let metadata = ProjectMetadataStore.load(projectID: projectID)
        let frames = manifest.images.map(\.frame).sorted()
        let sizeBytes = manifest.images.reduce(0) { $0 + Int64($1.sizeBytes) }

        var missing: [Int] = []
        if let lowest = frames.first, let highest = frames.last, highest > lowest {
            let present = Set(frames)
            missing = (lowest...highest).filter { !present.contains($0) }
        }

        return .json(ProjectDetailResponse(
            projectID: projectID,
            createdAt: metadata?.createdAt ?? Date(),
            updatedAt: metadata?.updatedAt ?? Date(),
            imageCount: manifest.imageCount,
            sizeBytes: sizeBytes,
            minimumFrame: frames.first,
            maximumFrame: frames.last,
            missingFrames: missing,
            manifestURL: "/api/v1/projects/\(projectID)/manifest",
            imagesURL: "/api/v1/projects/\(projectID)/images"
        ))
    }

    private static func projectManifest(_ request: HTTPRequest) -> HTTPResponse {
        guard let projectID = request.pathParameters["project_id"],
              FileManager.default.fileExists(atPath: ProjectStore.directory(for: projectID).path),
              let manifest = try? ManifestStore.load(projectID: projectID) else {
            return .error(code: "not_found", message: "Project not found.", status: 404)
        }
        return .json(manifest)
    }

    private static func listImages(_ request: HTTPRequest) -> HTTPResponse {
        guard let projectID = request.pathParameters["project_id"],
              FileManager.default.fileExists(atPath: ProjectStore.directory(for: projectID).path),
              let manifest = try? ManifestStore.load(projectID: projectID) else {
            return .error(code: "not_found", message: "Project not found.", status: 404)
        }

        let afterFrame = request.queryItems["after_frame"].flatMap(Int.init)
        let requestedLimit = request.queryItems["limit"].flatMap(Int.init) ?? APIConstants.imagesListDefaultLimit
        let limit = min(max(requestedLimit, 1), APIConstants.imagesListMaxLimit)

        let sorted = manifest.images.sorted { $0.frame < $1.frame }
        let filtered = afterFrame.map { after in sorted.filter { $0.frame > after } } ?? sorted
        let page = Array(filtered.prefix(limit))
        let hasMore = filtered.count > page.count

        let images = page.map { entry in
            ImageSummary(
                frame: entry.frame,
                angleDegrees: entry.angleDegrees,
                filename: entry.filename,
                capturedAt: entry.capturedAt,
                width: entry.width,
                height: entry.height,
                sizeBytes: entry.sizeBytes,
                sha256: entry.sha256,
                downloadURL: "/api/v1/projects/\(projectID)/images/\(entry.frame)"
            )
        }

        return .json(ImageListResponse(
            projectID: projectID,
            images: images,
            nextAfterFrame: page.last?.frame,
            hasMore: hasMore
        ))
    }

    /// Handles both GET and HEAD. Looks up the manifest entry (for hash/size/
    /// angle) and reads the file *before* returning, so a concurrent delete's
    /// unlink can't race an as-yet-unopened read (docs/scannercam_spec.md
    /// §8.8, §12).
    private static func downloadResponse(_ request: HTTPRequest, includeBody: Bool) -> HTTPResponse {
        guard let projectID = request.pathParameters["project_id"],
              let frame = request.pathParameters["frame"].flatMap(Int.init) else {
            return .error(code: "invalid_request", message: "Missing project_id or frame.", status: 400)
        }
        guard let manifest = try? ManifestStore.load(projectID: projectID),
              let entry = manifest.images.first(where: { $0.frame == frame }) else {
            return .error(code: "not_found", message: "Image not found.", status: 404)
        }

        let url = ProjectStore.imageURL(for: projectID, frame: frame)
        let body: Data
        if includeBody {
            guard let loaded = try? Data(contentsOf: url) else {
                return .error(code: "not_found", message: "Image not found.", status: 404)
            }
            body = loaded
        } else {
            guard FileManager.default.fileExists(atPath: url.path) else {
                return .error(code: "not_found", message: "Image not found.", status: 404)
            }
            body = Data()
        }

        let downloadFilename = entry.angleDegrees.map {
            String(format: "frame_%06d_angle_%07.3f.jpg", frame, $0)
        } ?? "frame_\(String(format: "%06d", frame))_angle_unknown.jpg"

        var response = HTTPResponse.jpeg(
            body,
            sha256: entry.sha256,
            projectID: projectID,
            frame: frame,
            downloadFilename: downloadFilename
        )
        if !includeBody {
            response.headers["Content-Length"] = String(entry.sizeBytes)
        }
        return response
    }

    private static func deleteImage(_ request: HTTPRequest) -> HTTPResponse {
        guard let projectID = request.pathParameters["project_id"],
              let frame = request.pathParameters["frame"].flatMap(Int.init) else {
            return .error(code: "invalid_request", message: "Missing project_id or frame.", status: 400)
        }
        do {
            try ImageStore.deleteImage(projectID: projectID, frame: frame)
            try ManifestStore.remove(frame: frame, projectID: projectID)
            return .noContent()
        } catch {
            return .error(code: "not_found", message: "Image not found.", status: 404)
        }
    }

    private static func deleteProject(_ request: HTTPRequest) -> HTTPResponse {
        guard let projectID = request.pathParameters["project_id"] else {
            return .error(code: "invalid_request", message: "Missing project_id.", status: 400)
        }
        guard request.header("X-Confirm-Delete") == projectID else {
            return .error(
                code: "invalid_request",
                message: "X-Confirm-Delete header must equal the project_id.",
                status: 400
            )
        }
        let directory = ProjectStore.directory(for: projectID)
        guard FileManager.default.fileExists(atPath: directory.path) else {
            return .error(code: "not_found", message: "Project not found.", status: 404)
        }
        do {
            try FileManager.default.removeItem(at: directory)
            return .noContent()
        } catch {
            return .error(code: "file_write_failed", message: "\(error)", status: 500)
        }
    }

    private static func deleteAllProjects(_ request: HTTPRequest) -> HTTPResponse {
        guard request.header("X-Confirm-Delete") == "DELETE_ALL_SCANNERCAM_PROJECTS" else {
            return .error(
                code: "invalid_request",
                message: "X-Confirm-Delete: DELETE_ALL_SCANNERCAM_PROJECTS header required.",
                status: 400
            )
        }
        let projectIDs = (try? ProjectStore.listProjectIDs()) ?? []
        var deletedImages = 0
        var freedBytes: Int64 = 0
        for projectID in projectIDs {
            if let manifest = try? ManifestStore.load(projectID: projectID) {
                deletedImages += manifest.imageCount
                freedBytes += manifest.images.reduce(0) { $0 + Int64($1.sizeBytes) }
            }
            try? FileManager.default.removeItem(at: ProjectStore.directory(for: projectID))
        }
        return .json(DeleteAllResponse(
            status: "deleted",
            deletedProjects: projectIDs.count,
            deletedImages: deletedImages,
            freedBytes: freedBytes
        ))
    }

    private static func allSummaries() -> [ProjectSummary] {
        let projectIDs = (try? ProjectStore.listProjectIDs()) ?? []
        var summaries: [ProjectSummary] = []
        for projectID in projectIDs {
            guard let manifest = try? ManifestStore.load(projectID: projectID) else { continue }
            let metadata = ProjectMetadataStore.load(projectID: projectID)
            let sizeBytes = manifest.images.reduce(0) { $0 + Int64($1.sizeBytes) }
            summaries.append(ProjectSummary(
                projectID: projectID,
                createdAt: metadata?.createdAt ?? Date(),
                updatedAt: metadata?.updatedAt ?? Date(),
                imageCount: manifest.imageCount,
                sizeBytes: sizeBytes
            ))
        }
        return summaries.sorted { $0.updatedAt > $1.updatedAt }
    }
}
