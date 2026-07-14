import Foundation
import Network

enum HTTPServerError: Error {
    case invalidPort
}

/// Minimal HTTP/1.1 server sufficient for the ScannerCam API
/// (docs/scannercam_spec.md §6.1). Deliberately does not support persistent
/// connections or chunked transfer encoding: every response carries an
/// accurate Content-Length and Connection: close, and the socket is closed
/// once the response is written. Binds all interfaces (0.0.0.0) so both the
/// Wi-Fi and Tailscale (utun*) paths reach it — see §0.
final class HTTPServer {
    private var listener: NWListener?
    private let router: Router
    private let queue = DispatchQueue(label: "com.ariemeir.ScannerCam.server")

    init(router: Router) {
        self.router = router
    }

    func start(port: UInt16) throws {
        guard let nwPort = NWEndpoint.Port(rawValue: port) else {
            throw HTTPServerError.invalidPort
        }
        let parameters = NWParameters.tcp
        parameters.allowLocalEndpointReuse = true

        let listener = try NWListener(using: parameters, on: nwPort)
        listener.newConnectionHandler = { [weak self] connection in
            self?.accept(connection)
        }
        listener.stateUpdateHandler = { state in
            ScannerCamLog.server.info("listener state: \(String(describing: state))")
        }
        listener.start(queue: queue)
        self.listener = listener
    }

    func stop() {
        listener?.cancel()
        listener = nil
    }

    private func accept(_ connection: NWConnection) {
        connection.start(queue: queue)
        readRequest(from: connection, buffer: Data())
    }

    // TODO: this simplified reader assumes the full HTTP request (headers +
    // body, per Content-Length) arrives across a small number of `receive`
    // calls — fine for LAN/Tailscale curl/URLSession clients, but doesn't
    // defend against a slow-loris style drip-fed request or an unbounded
    // Content-Length. Add a max-request-size guard before trusting this
    // beyond the tailnet.
    private func readRequest(from connection: NWConnection, buffer: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1024) { [weak self] data, _, isComplete, error in
            guard let self else { return }

            var buffer = buffer
            if let data, !data.isEmpty {
                buffer.append(data)
            }

            if let error {
                ScannerCamLog.server.error("connection error: \(error.localizedDescription)")
                connection.cancel()
                return
            }

            if let request = HTTPRequestParser.parse(buffer) {
                let response = self.router.handle(request)
                self.write(response, to: connection)
                return
            }

            if isComplete {
                connection.cancel()
                return
            }

            self.readRequest(from: connection, buffer: buffer)
        }
    }

    private func write(_ response: HTTPResponse, to connection: NWConnection) {
        let data = HTTPResponseSerializer.serialize(response)
        connection.send(content: data, completion: .contentProcessed { _ in
            connection.cancel()
        })
    }
}
