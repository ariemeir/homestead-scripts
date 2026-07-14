import CryptoKit
import Foundation

enum SHA256Hasher {
    static func hexDigest(of data: Data) -> String {
        CryptoKit.SHA256.hash(data: data)
            .map { String(format: "%02x", $0) }
            .joined()
    }

    static func hexDigest(ofFileAt url: URL) throws -> String {
        hexDigest(of: try Data(contentsOf: url, options: .mappedIfSafe))
    }
}
