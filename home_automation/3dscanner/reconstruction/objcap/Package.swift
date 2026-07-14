// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "objcap",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "objcap", path: "Sources/objcap")
    ]
)
