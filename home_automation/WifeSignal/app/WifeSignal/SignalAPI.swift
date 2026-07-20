import Foundation

enum SignalAPIError: LocalizedError {
    case invalidURL, invalidResponse, server(String)
    var errorDescription: String? {
        switch self {
        case .invalidURL: return "The server URL is invalid."
        case .invalidResponse: return "The server returned an invalid response."
        case .server(let message): return message
        }
    }
}

struct SignalAPI {
    let baseURL: String
    let token: String

    private func request(path: String, method: String = "GET", body: Data? = nil) throws -> URLRequest {
        let normalized = baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: normalized + path) else { throw SignalAPIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 15
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = body
        }
        return request
    }

    private func execute(_ request: URLRequest) async throws -> Data {
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw SignalAPIError.invalidResponse }
        guard (200...299).contains(http.statusCode) else {
            throw SignalAPIError.server(String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)")
        }
        return data
    }

    func send(_ color: SignalColor) async throws -> SignalStatus {
        let body = try JSONEncoder().encode(SignalRequest(color: color))
        let data = try await execute(try request(path: "/v1/signal", method: "POST", body: body))
        return try JSONDecoder().decode(SignalStatus.self, from: data)
    }

    func clear() async throws -> SignalStatus {
        let data = try await execute(try request(path: "/v1/clear", method: "POST"))
        return try JSONDecoder().decode(SignalStatus.self, from: data)
    }

    func status() async throws -> SignalStatus {
        let data = try await execute(try request(path: "/v1/status"))
        return try JSONDecoder().decode(SignalStatus.self, from: data)
    }
}
