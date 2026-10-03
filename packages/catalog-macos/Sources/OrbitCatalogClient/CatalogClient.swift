import Foundation

final class NoRedirect: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        // A loopback response must never redirect private query/evidence bodies off-device.
        completionHandler(nil)
    }
}

public enum CatalogClientError: Error, Sendable {
    case loopbackURLRequired
    case invalidResponse
    case http(Int, String)
    case unsupportedContract(String)
    case timeout
}

/// Async boundary for A7 recommendations, A8 library and data-source settings.
/// The Python worker owns SQLite; this client never opens a concurrent writer.
public actor CatalogClient {
    private let baseURL: URL
    private let session: URLSession

    public init(baseURL: URL = URL(string: "http://127.0.0.1:8766")!, session: URLSession = .shared) throws {
        guard baseURL.scheme == "http", let host = baseURL.host,
              ["127.0.0.1", "localhost", "::1", "[::1]"].contains(host),
              baseURL.user == nil, baseURL.password == nil else {
            throw CatalogClientError.loopbackURLRequired
        }
        self.baseURL = baseURL
        self.session = session
    }

    public func search(_ request: MatchRequest) async throws -> MatchResponse {
        let response: MatchResponse = try await send("search", method: "POST", body: JSONEncoder().encode(request))
        guard response.contract == "catalog-match-v1" else {
            throw CatalogClientError.unsupportedContract(response.contract)
        }
        return response
    }

    public func detail(itemID: String) async throws -> CatalogDetail {
        try await send("items/detail", query: [URLQueryItem(name: "item_id", value: itemID)])
    }

    public func status() async throws -> JSONValue { try await send("status") }
    public func sources() async throws -> [JSONValue] { try await send("sources") }

    /// Call on launch/resume or from the App's refresh scheduler; server enforces next_due_at.
    public func sync(sourceIDs: [String] = [], force: Bool = false, maxPages: Int = 10000) async throws -> CatalogJob {
        let body: JSONValue = .object(["source_ids": .array(sourceIDs.map(JSONValue.string)),
                                     "force": .bool(force), "max_pages": .number(Double(maxPages))])
        return try await send("sync", method: "POST", body: JSONEncoder().encode(body))
    }

    public func indexPendingChunks(maxChunks: Int = 256) async throws -> CatalogJob {
        let body: JSONValue = .object(["max_chunks": .number(Double(maxChunks))])
        return try await send("embeddings", method: "POST", body: JSONEncoder().encode(body))
    }

    public func job(_ id: String) async throws -> CatalogJob { try await send("jobs/" + id) }

    public func cancel(jobID: String) async throws {
        let _: JSONValue = try await send("jobs/" + jobID + "/cancel", method: "POST")
    }

    public func setSource(_ id: String, enabled: Bool) async throws {
        let body: JSONValue = .object(["enabled": .bool(enabled)])
        let _: JSONValue = try await send("sources/" + id, method: "PUT", body: JSONEncoder().encode(body))
    }

    /// Task cancellation also cancels this wait; use cancel(jobID:) to pause the worker itself.
    public func waitForJob(_ id: String, timeout: Duration = .seconds(600)) async throws -> CatalogJob {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while clock.now < deadline {
            try Task.checkCancellation()
            let state = try await job(id)
            if state.isFinished { return state }
            try await Task.sleep(for: .milliseconds(500))
        }
        throw CatalogClientError.timeout
    }

    private func send<T: Decodable>(_ route: String, method: String = "GET", body: Data? = nil,
                                     query: [URLQueryItem] = []) async throws -> T {
        let url = baseURL.appendingPathComponent("v1/catalog").appendingPathComponent(route)
        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            throw CatalogClientError.invalidResponse
        }
        components.queryItems = query.isEmpty ? nil : query
        guard let endpoint = components.url else { throw CatalogClientError.invalidResponse }
        var request = URLRequest(url: endpoint)
        request.httpMethod = method
        request.httpBody = body
        request.timeoutInterval = 60
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        let (data, response) = try await session.data(for: request, delegate: NoRedirect())
        guard let http = response as? HTTPURLResponse else { throw CatalogClientError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            throw CatalogClientError.http(http.statusCode, String(decoding: data.prefix(1000), as: UTF8.self))
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
