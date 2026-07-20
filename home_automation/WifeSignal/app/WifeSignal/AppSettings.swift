import Foundation

@MainActor
final class AppSettings: ObservableObject {
    @Published var serverURL: String { didSet { UserDefaults.standard.set(serverURL, forKey: "serverURL") } }
    @Published var apiToken: String { didSet { UserDefaults.standard.set(apiToken, forKey: "apiToken") } }
    init() {
        serverURL = UserDefaults.standard.string(forKey: "serverURL") ?? ""
        apiToken = UserDefaults.standard.string(forKey: "apiToken") ?? ""
    }
    var isConfigured: Bool { URL(string: serverURL) != nil && !apiToken.isEmpty }
}
