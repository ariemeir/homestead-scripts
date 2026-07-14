import Foundation
import Security

/// Generates and persists the bearer token used to authenticate API
/// requests (docs/scannercam_spec.md §6.3): 32 random bytes, base64url
/// encoded, stored in the Keychain, shown in the Settings screen.
enum KeychainTokenStore {
    private static let service = "com.ariemeir.ScannerCam.apiToken"
    private static let account = "api-token"

    static func loadOrCreateToken() -> String {
        if let existing = load() {
            return existing
        }
        let generated = generateToken()
        save(generated)
        return generated
    }

    static func regenerate() -> String {
        let generated = generateToken()
        save(generated)
        return generated
    }

    private static func generateToken() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        let status = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        precondition(status == errSecSuccess, "SecRandomCopyBytes failed with status \(status)")
        return Data(bytes).base64URLEncodedString()
    }

    private static func load() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func save(_ token: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)

        var attributes = query
        attributes[kSecValueData as String] = Data(token.utf8)
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        let status = SecItemAdd(attributes as CFDictionary, nil)
        precondition(status == errSecSuccess, "SecItemAdd failed with status \(status)")
    }
}

private extension Data {
    func base64URLEncodedString() -> String {
        base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
