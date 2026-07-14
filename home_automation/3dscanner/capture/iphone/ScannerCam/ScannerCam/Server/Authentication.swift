import Foundation

enum Authentication {
    static func isAuthorized(_ request: HTTPRequest) -> Bool {
        guard let header = request.header("Authorization"), header.hasPrefix("Bearer ") else {
            return false
        }
        let provided = String(header.dropFirst("Bearer ".count))
        return constantTimeEquals(provided, KeychainTokenStore.loadOrCreateToken())
    }

    /// Avoids a timing side-channel on token comparison
    /// (docs/scannercam_spec.md §6.3) — don't replace this with `==`.
    private static func constantTimeEquals(_ lhs: String, _ rhs: String) -> Bool {
        let lhsBytes = Array(lhs.utf8)
        let rhsBytes = Array(rhs.utf8)
        guard lhsBytes.count == rhsBytes.count else { return false }
        var difference: UInt8 = 0
        for (a, b) in zip(lhsBytes, rhsBytes) {
            difference |= a ^ b
        }
        return difference == 0
    }
}
