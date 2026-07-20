import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: SignalViewModel
    var body: some View {
        NavigationStack {
            VStack(spacing: 18) {
                VStack(spacing: 5) {
                    Text("Send Arie a signal").font(.headline)
                    Text("Tap once. The office light updates immediately.").font(.subheadline).foregroundStyle(.secondary)
                }
                ForEach(SignalColor.allCases) { signal in
                    Button { Task { await model.send(signal) } } label: {
                        HStack(spacing: 18) {
                            Image(systemName: signal.symbol).font(.system(size: 34, weight: .bold))
                            VStack(alignment: .leading, spacing: 3) {
                                Text(signal.rawValue.capitalized).font(.title2.bold())
                                Text(signal.label).font(.subheadline).opacity(0.9)
                            }
                            Spacer()
                        }
                        .foregroundStyle(signal == .yellow ? .black : .white)
                        .padding(.horizontal, 22)
                        .frame(maxWidth: .infinity, minHeight: 88)
                        .background(signal.color.gradient)
                        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                        .shadow(radius: 3, y: 2)
                        .opacity(signal.isAvailable ? 1 : 0.35)
                    }.buttonStyle(.plain).disabled(model.isLoading || !signal.isAvailable)
                }
                VStack(spacing: 8) {
                    if let error = model.errorMessage {
                        Label(error, systemImage: "wifi.exclamationmark").foregroundStyle(.red).font(.footnote)
                    } else if let status = model.status, let color = status.color {
                        HStack {
                            Circle().fill(color.color).frame(width: 14, height: 14)
                            Text(color.rawValue.capitalized + " sent").font(.headline)
                            Spacer()
                            if status.acknowledged {
                                Label("Seen", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                            } else { Text("Waiting").foregroundStyle(.secondary) }
                        }
                    } else {
                        Text(model.settings.isConfigured ? "No active signal" : "Tap the gear to connect the app").foregroundStyle(.secondary)
                    }
                }
                .padding().frame(maxWidth: .infinity)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18))

                Button("Clear signal", role: .destructive) { Task { await model.clear() } }
                    .buttonStyle(.bordered)
                    .disabled(model.isLoading || model.status?.color == nil)
                Spacer(minLength: 0)
            }
            .padding().navigationTitle("Office Signal")
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button { model.showSettings = true } label: { Image(systemName: "gearshape") } } }
            .sheet(isPresented: $model.showSettings) { SettingsView(settings: model.settings) }
            .overlay { if model.isLoading { ProgressView().controlSize(.large).padding().background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16)) } }
        }
    }
}
