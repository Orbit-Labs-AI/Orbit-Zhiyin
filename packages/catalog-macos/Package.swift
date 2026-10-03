// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "OrbitCatalogClient",
    platforms: [.macOS(.v13)],
    products: [.library(name: "OrbitCatalogClient", targets: ["OrbitCatalogClient"])],
    targets: [
        .target(name: "OrbitCatalogClient"),
        .testTarget(name: "OrbitCatalogClientTests", dependencies: ["OrbitCatalogClient"])
    ]
)
