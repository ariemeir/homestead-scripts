import SwiftUI

struct SettingsView: View {
    @ObservedObject var settings: AppSettings
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    TextField("https://kuma.example.ts.net", text: $settings.serverURL)
                        .textInputAutocapitalization(.never).keyboardType(.URL).autocorrectionDisabled()
                    SecureField("API token", text: $settings.apiToken)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                }
                Section { Text("The URL is your Tailscale Funnel address. The token must match SIGNAL_API_TOKEN on kuma.").font(.footnote).foregroundStyle(.secondary) }
            }
            .navigationTitle("Connection")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}
