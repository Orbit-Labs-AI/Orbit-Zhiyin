// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "TandemCatalogClient",
    platforms: [.macOS(.v13)],
    products: [.library(name: "TandemCatalogClient", targets: ["TandemCatalogClient"])],
    targets: [
        .target(name: "TandemCatalogClient"),
        .testTarget(name: "TandemCatalogClientTests", dependencies: ["TandemCatalogClient"])
    ]
)
