// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "NoiseKit",
    platforms: [.iOS(.v18), .macOS(.v14)],
    products: [
        .library(name: "NoiseKit", targets: ["NoiseKit"]),
    ],
    targets: [
        .target(name: "NoiseKit", resources: [.copy("Samples")], swiftSettings: [.swiftLanguageMode(.v5)]),
        .testTarget(
            name: "NoiseKitTests",
            dependencies: ["NoiseKit"],
            resources: [.copy("Fixtures")],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
