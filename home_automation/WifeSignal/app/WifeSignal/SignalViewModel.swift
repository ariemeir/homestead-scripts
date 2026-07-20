import Foundation

@MainActor
final class SignalViewModel: ObservableObject {
    @Published var status: SignalStatus?
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var showSettings = false
    let settings = AppSettings()
    private var pollingTask: Task<Void, Never>?
    deinit { pollingTask?.cancel() }
    private var api: SignalAPI { SignalAPI(baseURL: settings.serverURL, token: settings.apiToken) }

    func send(_ color: SignalColor) async {
        guard settings.isConfigured else { showSettings = true; return }
        isLoading = true; errorMessage = nil; defer { isLoading = false }
        do { status = try await api.send(color) } catch { errorMessage = error.localizedDescription }
    }
    func clear() async {
        guard settings.isConfigured else { showSettings = true; return }
        isLoading = true; errorMessage = nil; defer { isLoading = false }
        do { status = try await api.clear() } catch { errorMessage = error.localizedDescription }
    }
    func refreshStatus() async {
        guard settings.isConfigured else { return }
        do { status = try await api.status(); errorMessage = nil }
        catch { if status == nil { errorMessage = error.localizedDescription } }
    }
    func startPolling() {
        pollingTask?.cancel()
        pollingTask = Task {
            while !Task.isCancelled {
                await refreshStatus()
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }
}
