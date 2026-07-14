import SwiftUI
import UIKit

struct SettingsScreen: View {
    @State private var token = KeychainTokenStore.loadOrCreateToken()
    @State private var draft = ""
    @State private var justCopied = false
    @State private var justSaved = false

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
                    draft = ""
                }
            }

            Section {
                TextField("New token", text: $draft)
                    .font(.system(.footnote, design: .monospaced))
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled(true)
                Button("Use today's date (JST)") {
                    draft = KeychainTokenStore.todayTokenJST()
                }
                Button(justSaved ? "Saved" : "Set Token") {
                    if let saved = KeychainTokenStore.setToken(draft) {
                        token = saved
                        draft = ""
                        justSaved = true
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                            justSaved = false
                        }
                    }
                }
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            } header: {
                Text("Set custom token")
            } footer: {
                Text("Takes effect immediately. A short, memorable value (e.g. "
                     + "today's date) is convenient on a private network but easy "
                     + "to guess — anyone who can reach the phone can use it.")
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
