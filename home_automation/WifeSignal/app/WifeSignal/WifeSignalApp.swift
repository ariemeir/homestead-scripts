import SwiftUI

@main
struct WifeSignalApp: App {
    @StateObject private var model = SignalViewModel()
    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .task {
                    await model.refreshStatus()
                    model.startPolling()
                }
        }
    }
}
