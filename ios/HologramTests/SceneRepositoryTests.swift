import XCTest
@testable import Hologram

final class SceneRepositoryTests: XCTestCase {
    @MainActor
    func testNotBuiltAndNetworkFailureLoadTheLabelledFixture() async throws {
        for scenario in SceneFailureProtocol.Scenario.allCases {
            SceneFailureProtocol.scenario = scenario
            SceneFailureProtocol.paths = []
            let configuration = URLSessionConfiguration.ephemeral
            configuration.protocolClasses = [SceneFailureProtocol.self]
            let session = URLSession(configuration: configuration)
            defer { session.invalidateAndCancel() }
            let repository = SceneRepository(apiURL: URL(string: "https://scene.example")!, session: session)
            let scene = try await ARSceneLoader.load(docID: "missing__doc", url: nil, repository: repository)
            XCTAssertTrue(scene.isFixture)
            XCTAssertEqual(scene.manifest?.doc_id, "fixture__ios")
            XCTAssertNotNil(scene.manifest?.items["window-001"])
            XCTAssertEqual(SceneFailureProtocol.paths, ["/api/docs/missing__doc/scene"],
                           "Unavailable or mismatched metadata must not trigger a USDZ download")
        }
    }
}

private final class SceneFailureProtocol: URLProtocol {
    enum Scenario: CaseIterable { case notBuilt, networkFailure, wrongDocument }
    static var scenario = Scenario.notBuilt
    static var paths: [String] = []

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.paths.append(request.url!.path)
        if Self.scenario == .networkFailure {
            client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet))
            return
        }
        let response = HTTPURLResponse(url: request.url!, statusCode: Self.scenario == .notBuilt ? 404 : 200,
                                       httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        let body = Self.scenario == .notBuilt ? #"{"status":"not_built"}"#
            : #"{"doc_id":"different__doc","items":{}}"#
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
