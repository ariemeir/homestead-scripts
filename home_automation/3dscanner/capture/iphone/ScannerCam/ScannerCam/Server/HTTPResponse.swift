import Foundation

struct HTTPResponse {
    var status: Int
    var reason: String
    var headers: [String: String]
    var body: Data

    static func json<T: Encodable>(_ value: T, status: Int = 200) -> HTTPResponse {
        let data = (try? JSONEncoder.scannerCam.encode(value)) ?? Data()
        return HTTPResponse(
            status: status,
            reason: reasonPhrase(for: status),
            headers: ["Content-Type": "application/json"],
            body: data
        )
    }

    static func error(code: String, message: String, status: Int) -> HTTPResponse {
        json(APIError.make(code: code, message: message), status: status)
    }

    static func jpeg(
        _ data: Data,
        sha256: String,
        projectID: String,
        frame: Int,
        downloadFilename: String
    ) -> HTTPResponse {
        HTTPResponse(
            status: 200,
            reason: "OK",
            headers: [
                "Content-Type": "image/jpeg",
                "Content-Disposition": "attachment; filename=\"\(downloadFilename)\"",
                "ETag": "\"\(sha256)\"",
                "X-ScannerCam-SHA256": sha256,
                "X-ScannerCam-Project-ID": projectID,
                "X-ScannerCam-Frame": String(frame),
            ],
            body: data
        )
    }

    static func noContent() -> HTTPResponse {
        HTTPResponse(status: 204, reason: "No Content", headers: [:], body: Data())
    }

    private static func reasonPhrase(for status: Int) -> String {
        switch status {
        case 200: return "OK"
        case 201: return "Created"
        case 204: return "No Content"
        case 400: return "Bad Request"
        case 401: return "Unauthorized"
        case 404: return "Not Found"
        case 409: return "Conflict"
        case 423: return "Locked"
        case 500: return "Internal Server Error"
        case 507: return "Insufficient Storage"
        default: return "Unknown"
        }
    }
}

enum HTTPResponseSerializer {
    /// Every response is self-contained: accurate Content-Length, no
    /// chunked encoding, `Connection: close` (docs/scannercam_spec.md §6.1).
    ///
    /// A caller may pre-set `Content-Length` (HEAD responses: the body is
    /// empty but the header must report what the equivalent GET would
    /// return) — only fill it in from the actual body size otherwise.
    static func serialize(_ response: HTTPResponse) -> Data {
        var headers = response.headers
        if headers["Content-Length"] == nil {
            headers["Content-Length"] = String(response.body.count)
        }
        headers["Connection"] = "close"
        headers["X-ScannerCam-Version"] = "0.1.0"

        var head = "HTTP/1.1 \(response.status) \(response.reason)\r\n"
        for (name, value) in headers {
            head += "\(name): \(value)\r\n"
        }
        head += "\r\n"

        var data = Data(head.utf8)
        data.append(response.body)
        return data
    }
}
