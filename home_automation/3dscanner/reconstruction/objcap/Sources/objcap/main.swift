// objcap — turn a folder of photos into a 3D model using Apple Object Capture
// (RealityKit PhotogrammetrySession). GPU-accelerated on Apple Silicon.
//
// Usage: objcap <imagesDir> <detail> <output...>
//        detail: preview | reduced | medium | full | raw
//        output: one or more paths; extension picks the format (.usdz / .obj).
//                Multiple outputs share a single reconstruction pass.
//
// Output is a textured mesh (USDZ or OBJ), NOT STL — convert separately
// (assimp / Meshlab). Photogrammetry meshes are near-watertight, but a
// turntable scan never sees the object's underside, so the base needs a
// repair pass before 3D printing.

import Foundation
import RealityKit

func fail(_ message: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(code)
}

@available(macOS 14.0, *)
func detail(from name: String) -> PhotogrammetrySession.Request.Detail {
    switch name.lowercased() {
    case "preview": return .preview
    case "reduced": return .reduced
    case "full": return .full
    case "raw": return .raw
    default: return .medium
    }
}

@available(macOS 14.0, *)
func run() {
    let args = CommandLine.arguments
    guard args.count >= 4 else {
        fail("usage: objcap <imagesDir> <detail> <output...>\n" +
             "       detail: preview|reduced|medium|full|raw", code: 2)
    }
    let inputURL = URL(fileURLWithPath: args[1], isDirectory: true)
    let requestedDetail = detail(from: args[2])
    let outputs = args[3...].map { URL(fileURLWithPath: $0) }

    var config = PhotogrammetrySession.Configuration()
    // Turntable capture: consecutive frames overlap, so sequential ordering
    // matches the data and speeds up matching.
    config.sampleOrdering = .sequential
    // Objects here are small/textured; bias toward finding more features.
    config.featureSensitivity = .high

    let session: PhotogrammetrySession
    do {
        session = try PhotogrammetrySession(input: inputURL, configuration: config)
    } catch {
        fail("failed to start session (need a folder of images + a supported GPU): \(error)")
    }

    let requests = outputs.map {
        PhotogrammetrySession.Request.modelFile(url: $0, detail: requestedDetail)
    }

    Task {
        do {
            for try await output in session.outputs {
                switch output {
                case .inputComplete:
                    print("input ingested — reconstructing (\(args[2]))…")
                case .requestProgress(_, let fraction):
                    print(String(format: "  progress: %3.0f%%", fraction * 100))
                case .requestComplete(_, let result):
                    if case .modelFile(let url) = result {
                        print("model written: \(url.path)")
                    }
                case .requestError(_, let error):
                    fail("request error: \(error)")
                case .processingComplete:
                    print("processing complete ✓")
                    exit(0)
                case .processingCancelled:
                    fail("processing cancelled")
                case .invalidSample(let id, let reason):
                    print("  invalid sample \(id): \(reason)")
                case .skippedSample(let id):
                    print("  skipped sample \(id)")
                case .automaticDownsampling:
                    print("  (automatic downsampling engaged)")
                case .requestProgressInfo:
                    break
                case .stitchingIncomplete:
                    print("  (stitching incomplete)")
                @unknown default:
                    break
                }
            }
        } catch {
            fail("output stream error: \(error)")
        }
    }

    do {
        try session.process(requests: requests)
    } catch {
        fail("failed to submit requests: \(error)")
    }
}

if #available(macOS 14.0, *) {
    run()
    RunLoop.main.run()
} else {
    fail("Object Capture requires macOS 14 or later.")
}
