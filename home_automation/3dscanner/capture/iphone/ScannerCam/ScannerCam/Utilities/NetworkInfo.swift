import Foundation

enum NetworkInfo {
    /// The device's current Wi-Fi (en0) IPv4 address, if connected — shown
    /// in the UI so the user can point `shika` at the phone without needing
    /// a separate network scan.
    static func wifiIPv4Address() -> String? {
        var address: String?
        var ifaddrPointer: UnsafeMutablePointer<ifaddrs>?

        guard getifaddrs(&ifaddrPointer) == 0, let firstAddr = ifaddrPointer else {
            return nil
        }
        defer { freeifaddrs(ifaddrPointer) }

        for pointer in sequence(first: firstAddr, next: { $0.pointee.ifa_next }) {
            let interface = pointer.pointee
            guard interface.ifa_addr.pointee.sa_family == UInt8(AF_INET) else { continue }
            guard String(cString: interface.ifa_name) == "en0" else { continue }

            var hostname = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            let result = getnameinfo(
                interface.ifa_addr,
                socklen_t(interface.ifa_addr.pointee.sa_len),
                &hostname,
                socklen_t(hostname.count),
                nil,
                0,
                NI_NUMERICHOST
            )
            if result == 0 {
                address = String(cString: hostname)
            }
        }

        return address
    }
}
