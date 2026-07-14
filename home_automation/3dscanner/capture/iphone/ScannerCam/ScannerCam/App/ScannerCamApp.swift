import SwiftUI

@main
struct ScannerCamApp: App {
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            CameraScreen()
                .environmentObject(appState)
                .onAppear {
                    appState.bootstrap()
                }
        }
    }
}
