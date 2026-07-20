import Foundation
import SwiftUI

enum SignalColor: String, Codable, CaseIterable, Identifiable {
    case green, yellow, red
    var id: String { rawValue }
    var label: String {
        switch self {
        case .green, .yellow: return "Coming soon"
        case .red: return "Urgent"
        }
    }
    var isAvailable: Bool { self == .red }
    var color: Color {
        switch self {
        case .green: return .green
        case .yellow: return .yellow
        case .red: return .red
        }
    }
    var symbol: String { self == .red ? "exclamationmark.circle.fill" : "circle.fill" }
}

struct SignalStatus: Codable {
    let color: SignalColor?
    let acknowledged: Bool
    let sentAt: String?
    let acknowledgedAt: String?
    let message: String?
}

struct SignalRequest: Codable { let color: SignalColor }
