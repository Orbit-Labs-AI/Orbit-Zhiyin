import Foundation
import XCTest
@testable import TandemCatalogClient

final class StubProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status, data) = try Self.handler!(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}

final class CatalogClientTests: XCTestCase {
    private func client() throws -> CatalogClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubProtocol.self]
        return try CatalogClient(session: URLSession(configuration: config))
    }

    func testRemoteURLsRejected() {
        XCTAssertThrowsError(try CatalogClient(baseURL: URL(string: "https://example.com")!))
        XCTAssertThrowsError(try CatalogClient(baseURL: URL(string: "http://user:secret@localhost")!))
    }

    func testRequestCarriesEvidenceAndFeatureContract() throws {
        var request = MatchRequest(text: "重复失败")
        request.problemID = "problem-1"
        request.profileEvidenceIDs = ["event-1"]
        request.features = [Feature("domain", "debugging")]
        let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as! [String: Any]
        XCTAssertEqual(object["problem_id"] as? String, "problem-1")
        XCTAssertEqual(object["profile_evidence_ids"] as? [String], ["event-1"])
        XCTAssertEqual(object["per_route"] as? Int, 100)
    }

    func testSearchDecodesCoverageAndRejectsUnknownContract() async throws {
        let response = #"{"contract":"catalog-match-v1","generation":1,"items":[],"gates":[],"routes":{"lexical":0},"vector":{"status":"partial","indexed_chunks":2},"score_meaning":"retrieval_relevance_not_effectiveness","effect_status":"unmeasured"}"#
        StubProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/v1/catalog/search")
            return (200, Data(response.utf8))
        }
        let client = try client()
        let result = try await client.search(MatchRequest(text: "调试"))
        XCTAssertEqual(result.effectStatus, "unmeasured")
        XCTAssertEqual(result.vector, .object(["status": .string("partial"), "indexed_chunks": .number(2)]))
        StubProtocol.handler = { _ in (200, Data(response.replacingOccurrences(of: "catalog-match-v1", with: "catalog-match-v2").utf8)) }
        do { _ = try await client.search(MatchRequest(text: "x")); XCTFail("expected contract failure") }
        catch CatalogClientError.unsupportedContract { }
    }

    func testDetailEscapesCanonicalIDsAndPropagatesHTTPFailure() async throws {
        let id = "skill:github.com:42:skills/a b/SKILL.md"
        StubProtocol.handler = { request in
            let query = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems
            XCTAssertEqual(query?.first?.value, id)
            return (404, Data(#"{"detail":"catalog_item_not_found"}"#.utf8))
        }
        do { _ = try await client().detail(itemID: id); XCTFail("expected HTTP failure") }
        catch CatalogClientError.http(let code, _) { XCTAssertEqual(code, 404) }
    }

    func testWaitReturnsFailedJob() async throws {
        StubProtocol.handler = { _ in (200, Data(#"{"job_id":"j1","kind":"sync","status":"failed","result":null,"error":"http_429"}"#.utf8)) }
        let result = try await client().waitForJob("j1")
        XCTAssertEqual(result.status, "failed")
        XCTAssertTrue(result.isFinished)
    }

    func testRedirectsAreRefusedBeforeSendingQueryElsewhere() {
        let delegate = NoRedirect()
        let session = URLSession(configuration: .ephemeral)
        let local = URL(string: "http://127.0.0.1:8766/v1/catalog/search")!
        let response = HTTPURLResponse(url: local, statusCode: 307, httpVersion: nil,
                                       headerFields: ["Location": "https://example.com"])!
        let task = session.dataTask(with: local)
        delegate.urlSession(session, task: task, willPerformHTTPRedirection: response,
                            newRequest: URLRequest(url: URL(string: "https://example.com")!)) { request in
            XCTAssertNil(request)
        }
        session.invalidateAndCancel()
    }
}
