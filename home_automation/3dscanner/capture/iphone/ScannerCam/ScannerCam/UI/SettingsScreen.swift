import SwiftUI
import UIKit

struct SettingsScreen: View {
    @State private var token = KeychainTokenStore.loadOrCreateToken()
    @State private var justCopied = false

    var body: some View {
        Form {
            Section("API") {
                LabeledContent("Port", value: "8765")
                Text(token)
                    .font(.system(.footnote, design: .monospaced))
                    .textSelection(.enabled)
                Button(justCopied ? "Copied" : "Copy Token") {
                    UIPasteboard.general.string = token
                    justCopied = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                        justCopied = false
                    }
                }
                Button("Regenerate Token") {
                    token = KeychainTokenStore.regenerate()
                }
            }

            // TODO: image orientation, JPEG quality mode, lens selection,
            // keep-screen-awake toggle, delete-all-projects action
            // (docs/scannercam_spec.md §10.3-10.4).
        }
        .navigationTitle("Settings")
    }
}

#Preview {
    NavigationStack { SettingsScreen() }
}
