import Foundation

struct HTTPRequest {
    let method: String
    let path: String
    let queryItems: [String: String]
    let headers: [String: String]
    let body: Data
    var pathParameters: [String: String] = [:]

    func header(_ name: String) -> String? {
        headers.first { $0.key.caseInsensitiveCompare(name) == .orderedSame }?.value
    }
}

enum HTTPRequestParser {
    /// Parses a full HTTP/1.1 request out of `buffer`. Returns nil if the
    /// buffer doesn't yet contain a complete request (headers terminated by
    /// CRLFCRLF, plus `Content-Length` bytes of body) — the caller should
    /// keep accumulating and try again.
    ///
    /// Deliberately minimal (docs/scannercam_spec.md §6.1): no chunked
    /// transfer encoding, no multipart. Assumes the whole request arrives
    /// within a bounded number of `receive` calls, which holds for the curl
    /// / URLSession clients this API targets.
    static func parse(_ buffer: Data) -> HTTPRequest? {
        guard let headerEnd = buffer.range(of: Data("\r\n\r\n".utf8)) else {
            return nil
        }

        let headerData = buffer.subdata(in: buffer.startIndex..<headerEnd.lowerBound)
        guard let headerText = String(data: headerData, encoding: .utf8) else {
            return nil
        }

        var lines = headerText.components(separatedBy: "\r\n")
        guard !lines.isEmpty else { return nil }
        let requestLineParts = lines.removeFirst().split(separator: " ", maxSplits: 2)
        guard requestLineParts.count >= 2 else { return nil }
        let method = String(requestLineParts[0])
        let rawPath = String(requestLineParts[1])

        var headers: [String: String] = [:]
        for line in lines where !line.isEmpty {
            guard let colon = line.firstIndex(of: ":") else { continue }
            let name = line[line.startIndex..<colon].trimmingCharacters(in: .whitespaces)
            let value = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
            headers[name] = value
        }

        let contentLength = headers.first { $0.key.caseInsensitiveCompare("Content-Length") == .orderedSame }
            .flatMap { Int($0.value) } ?? 0

        let bodyStart = headerEnd.upperBound
        let availableBody = buffer.distance(from: bodyStart, to: buffer.endIndex)
        guard availableBody >= contentLength else {
            return nil
        }
        let bodyEnd = buffer.index(bodyStart, offsetBy: contentLength)
        let body = buffer.subdata(in: bodyStart..<bodyEnd)

        let (path, query) = splitQuery(rawPath)
        return HTTPRequest(method: method, path: path, queryItems: query, headers: headers, body: body)
    }

    private static func splitQuery(_ rawPath: String) -> (String, [String: String]) {
        guard let questionMark = rawPath.firstIndex(of: "?") else {
            return (rawPath.removingPercentEncoding ?? rawPath, [:])
        }
        let path = String(rawPath[rawPath.startIndex..<questionMark])
        let queryString = rawPath[rawPath.index(after: questionMark)...]

        var items: [String: String] = [:]
        for pair in queryString.split(separator: "&") {
            let parts = pair.split(separator: "=", maxSplits: 1)
            guard let rawKey = parts.first else { continue }
            let rawValue = parts.count > 1 ? String(parts[1]) : ""
            let key = String(rawKey).removingPercentEncoding ?? String(rawKey)
            items[key] = rawValue.removingPercentEncoding ?? rawValue
        }
        return (path.removingPercentEncoding ?? path, items)
    }
}
