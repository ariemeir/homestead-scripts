import Combine
import SwiftUI

struct CameraScreen: View {
    @EnvironmentObject private var appState: AppState

    @State private var status: CameraStatusSnapshot?
    @State private var exposureBias: Float = 0
    @State private var lensPosition: Float = 0.5
    @State private var manualFocusEnabled = false
    @State private var testCaptureImage: UIImage?
    @State private var testCaptureCaption: String?
    @State private var isCapturingTest = false
    @State private var projectCount = 0
    @State private var imageCount = 0
    @State private var didSeedControls = false

    private let statusTimer = Timer.publish(every: 0.5, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    CameraPreview(session: appState.cameraController.captureSession) { devicePoint in
                        appState.cameraController.focusAndExpose(at: devicePoint) { _ in
                            DispatchQueue.main.async { refreshStatus() }
                        }
                    }
                    .aspectRatio(4.0 / 3.0, contentMode: .fit)
                    .background(Color.black)
                    .clipShape(RoundedRectangle(cornerRadius: 8))

                    statusSection
                    lockControlsSection
                    exposureBiasSection
                    manualFocusSection
                    testCaptureSection
                    networkFooter
                }
                .padding()
            }
            .navigationTitle("ScannerCam")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    NavigationLink("Projects") { ProjectsScreen() }
                }
                ToolbarItem(placement: .navigationBarLeading) {
                    NavigationLink("Settings") { SettingsScreen() }
                }
            }
            .onAppear {
                refreshStatus()
                seedControlsIfNeeded()
            }
            .onReceive(statusTimer) { _ in
                refreshStatus()
                seedControlsIfNeeded()
            }
        }
    }

    // MARK: - Status

    private var statusSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Wide 1×")
                    .fontWeight(.medium)
                Spacer()
                if let status {
                    Text("\(status.photoWidth) × \(status.photoHeight)")
                        .foregroundStyle(.secondary)
                }
            }
            lockRow("Focus", mode: status?.focusMode, adjusting: status?.focusAdjusting ?? false)
            lockRow("Exposure", mode: status?.exposureMode, adjusting: status?.exposureAdjusting ?? false)
            lockRow("White balance", mode: status?.whiteBalanceMode, adjusting: status?.whiteBalanceAdjusting ?? false)
        }
        .font(.subheadline)
    }

    private func lockRow(_ label: String, mode: String?, adjusting: Bool) -> some View {
        let locked = mode == "locked"
        return HStack {
            Text(label)
            Spacer()
            Text(adjusting ? "ADJUSTING…" : (locked ? "LOCKED" : "AUTO"))
                .foregroundStyle(locked ? .green : .secondary)
                .fontWeight(locked ? .semibold : .regular)
        }
    }

    // MARK: - Lock controls

    private var lockControlsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                Button("Lock All") { lockAll() }
                    .buttonStyle(.borderedProminent)
                Button("Unlock All") { unlockAll() }
                    .buttonStyle(.bordered)
            }
            HStack(spacing: 8) {
                Button("Lock Focus") {
                    appState.cameraController.lockFocus { _ in DispatchQueue.main.async { refreshStatus() } }
                }
                Button("Lock Exposure") {
                    appState.cameraController.lockExposure { _ in DispatchQueue.main.async { refreshStatus() } }
                }
                Button("Lock WB") {
                    appState.cameraController.lockWhiteBalance { _ in DispatchQueue.main.async { refreshStatus() } }
                }
            }
            .buttonStyle(.bordered)
            .font(.footnote)
        }
    }

    private func lockAll() {
        let controller = appState.cameraController
        controller.lockFocus { _ in
            controller.lockExposure { _ in
                controller.lockWhiteBalance { _ in
                    DispatchQueue.main.async { refreshStatus() }
                }
            }
        }
    }

    private func unlockAll() {
        manualFocusEnabled = false
        appState.cameraController.unlockAll { _ in
            DispatchQueue.main.async { refreshStatus() }
        }
    }

    // MARK: - Exposure compensation

    private var exposureBiasSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("Exposure Compensation")
                Spacer()
                Text(String(format: "%+.1f EV", exposureBias))
                    .foregroundStyle(.secondary)
            }
            .font(.subheadline)
            Slider(value: $exposureBias, in: appState.cameraController.exposureBiasRange) { editing in
                if !editing {
                    appState.cameraController.setExposureBias(exposureBias) { _ in
                        DispatchQueue.main.async { refreshStatus() }
                    }
                }
            }
        }
    }

    // MARK: - Manual focus

    private var manualFocusSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            Toggle("Manual Focus", isOn: $manualFocusEnabled)
                .font(.subheadline)
                .onChange(of: manualFocusEnabled) { _, enabled in
                    if enabled {
                        appState.cameraController.setFocusLensPosition(lensPosition) { _ in
                            DispatchQueue.main.async { refreshStatus() }
                        }
                    } else {
                        appState.cameraController.unlockFocus { _ in
                            DispatchQueue.main.async { refreshStatus() }
                        }
                    }
                }

            if manualFocusEnabled {
                HStack {
                    Text("Lens Position")
                    Spacer()
                    Text(String(format: "%.2f", lensPosition))
                        .foregroundStyle(.secondary)
                }
                .font(.subheadline)
                Slider(value: $lensPosition, in: 0...1) { editing in
                    if !editing {
                        appState.cameraController.setFocusLensPosition(lensPosition) { _ in
                            DispatchQueue.main.async { refreshStatus() }
                        }
                    }
                }
            }
        }
    }

    // MARK: - Test capture

    private var testCaptureSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button {
                performTestCapture()
            } label: {
                HStack {
                    if isCapturingTest {
                        ProgressView().tint(.white)
                    }
                    Text("Test Capture")
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(isCapturingTest || !(status?.sessionRunning ?? false))

            if let testCaptureImage {
                Image(uiImage: testCaptureImage)
                    .resizable()
                    .scaledToFit()
                    .frame(maxHeight: 160)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }
            if let testCaptureCaption {
                Text(testCaptureCaption)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func performTestCapture() {
        isCapturingTest = true
        appState.cameraController.capturePhoto { result in
            DispatchQueue.main.async {
                isCapturingTest = false
                switch result {
                case .success(let photo):
                    testCaptureImage = UIImage(data: photo.data)
                    let size = ByteCountFormatter.string(fromByteCount: Int64(photo.data.count), countStyle: .file)
                    testCaptureCaption = "\(photo.width) × \(photo.height) · \(size) — not saved to any project"
                case .failure(let error):
                    testCaptureCaption = "Capture failed: \(String(describing: error))"
                }
            }
        }
    }

    // MARK: - Footer

    private var networkFooter: some View {
        VStack(alignment: .leading, spacing: 4) {
            Divider()
            HStack {
                Circle()
                    .fill(appState.serverRunning ? .green : .red)
                    .frame(width: 8, height: 8)
                Text(appState.serverRunning ? "API: Running" : "API: Stopped")
            }
            if let ip = NetworkInfo.wifiIPv4Address() {
                Text("\(ip):8765")
                    .font(.system(.footnote, design: .monospaced))
            } else {
                Text("Not connected to Wi-Fi")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            Text("Projects: \(projectCount)   Images: \(imageCount)")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .font(.subheadline)
    }

    // MARK: - Helpers

    private func refreshStatus() {
        status = appState.cameraController.statusSnapshot()
        let totals = StorageSummary.current()
        projectCount = totals.projectCount
        imageCount = totals.imageCount
    }

    /// Seeds the exposure/focus slider starting positions from the camera's
    /// actual current values, once, so they don't jump when first shown.
    private func seedControlsIfNeeded() {
        guard !didSeedControls, let status else { return }
        exposureBias = status.exposureTargetBias
        lensPosition = status.focusLensPosition
        didSeedControls = true
    }
}

#Preview {
    CameraScreen().environmentObject(AppState())
}
