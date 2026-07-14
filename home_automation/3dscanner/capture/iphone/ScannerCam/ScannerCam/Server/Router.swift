import Foundation

typealias RouteHandler = (HTTPRequest) -> HTTPResponse

struct Route {
    let method: String
    /// Path segments; a segment starting with ":" is a wildcard capture,
    /// e.g. ["api","v1","projects",":project_id","images",":frame"].
    let pattern: [String]
    let requiresAuth: Bool
    let handler: RouteHandler
}

/// Not thread-safe during registration — all `register` calls must complete
/// before `HTTPServer.start` is called. `handle` itself is read-only and
/// safe to call concurrently from multiple connection callbacks afterward.
final class Router {
    private var routes: [Route] = []

    func register(
        _ method: String,
        _ path: String,
        requiresAuth: Bool = true,
        handler: @escaping RouteHandler
    ) {
        let pattern = path.split(separator: "/").map(String.init)
        routes.append(Route(method: method, pattern: pattern, requiresAuth: requiresAuth, handler: handler))
    }

    func handle(_ request: HTTPRequest) -> HTTPResponse {
        let requestSegments = request.path.split(separator: "/").map(String.init)

        for route in routes where route.method == request.method {
            guard let params = Self.match(pattern: route.pattern, segments: requestSegments) else {
                continue
            }
            if route.requiresAuth, !Authentication.isAuthorized(request) {
                return .error(code: "unauthorized", message: "Missing or invalid bearer token.", status: 401)
            }
            var authorizedRequest = request
            authorizedRequest.pathParameters = params
            return route.handler(authorizedRequest)
        }

        return .error(code: "not_found", message: "No route for \(request.method) \(request.path).", status: 404)
    }

    private static func match(pattern: [String], segments: [String]) -> [String: String]? {
        guard pattern.count == segments.count else { return nil }
        var params: [String: String] = [:]
        for (patternSegment, segment) in zip(pattern, segments) {
            if patternSegment.hasPrefix(":") {
                params[String(patternSegment.dropFirst())] = segment
            } else if patternSegment != segment {
                return nil
            }
        }
        return params
    }
}
