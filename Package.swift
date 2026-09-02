// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ChurchToolsProPresenterBridge",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(
            name: "ChurchToolsProPresenterBridge",
            targets: ["ChurchToolsProPresenterBridge"]
        )
    ],
    targets: [
        .executableTarget(
            name: "ChurchToolsProPresenterBridge"
        )
    ]
)
