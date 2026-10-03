import Foundation

/// Extensible provider metadata without losing unknown manifest/score fields.
public enum JSONValue: Codable, Sendable, Equatable {
    case object([String: JSONValue]), array([JSONValue]), string(String), number(Double), bool(Bool), null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([JSONValue].self) { self = .array(value) }
        else { self = .object(try container.decode([String: JSONValue].self)) }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }
}

public struct Feature: Codable, Sendable, Equatable {
    public var feature: String
    public var value: String
    public var weight: Double
    public var origin: String
    public var evidence: String
    public init(_ feature: String, _ value: String, weight: Double = 1, origin: String = "extracted", evidence: String = "") {
        self.feature = feature; self.value = value; self.weight = weight
        self.origin = origin; self.evidence = evidence
    }
}

public struct MatchRequest: Encodable, Sendable {
    public var text: String
    public var features: [Feature] = []
    public var types: [String] = []
    public var agents: [String] = []
    public var sourceIDs: [String] = []
    public var excludedIDs: [String] = []
    public var language: String? = nil
    public var maxDifficulty: Int = 4
    public var purpose: String = "library"
    public var problemID: String? = nil
    public var problemType: String? = nil
    public var scene: String? = nil
    public var evidenceIDs: [String] = []
    public var profileEvidenceIDs: [String] = []
    public var limit: Int = 20
    public var perRoute: Int = 100
    public var modelID: String? = nil
    public init(text: String) { self.text = text }
    enum CodingKeys: String, CodingKey {
        case text, features, types, agents, language, purpose, scene, limit
        case sourceIDs = "source_ids", excludedIDs = "excluded_ids", maxDifficulty = "max_difficulty"
        case problemID = "problem_id", problemType = "problem_type", evidenceIDs = "evidence_ids"
        case profileEvidenceIDs = "profile_evidence_ids", perRoute = "per_route", modelID = "model_id"
    }
}

public struct MatchResponse: Decodable, Sendable {
    public let contract: String
    public let generation: Int?
    public let items: [CatalogMatch]
    public let gates: [String]
    public let routes: [String: Int]
    public let vector: JSONValue
    public let scoreMeaning: String
    public let effectStatus: String
    enum CodingKeys: String, CodingKey {
        case contract, generation, items, gates, routes, vector
        case scoreMeaning = "score_meaning", effectStatus = "effect_status"
    }
}

public struct CatalogMatch: Decodable, Sendable, Identifiable {
    public var id: String { itemID }
    public let itemID: String
    public let type: String
    public let name: String
    public let summary: String
    public let url: String
    public let agents: [String]
    public let license: String?
    public let difficulty: Int
    public let score: Double
    public let rank: Int
    public let scoreParts: JSONValue
    public let matchedFeatures: [Feature]
    public let passage: Passage?
    public let versionID: String
    public let contentHash: String
    public let evidenceIDs: [String]
    public let profileEvidenceIDs: [String]
    public let effectStatus: String
    enum CodingKeys: String, CodingKey {
        case type, name, summary, url, agents, license, difficulty, score, rank, passage
        case itemID = "item_id", versionID = "version_id", contentHash = "content_hash"
        case scoreParts = "score_parts", matchedFeatures = "matched_features"
        case evidenceIDs = "evidence_ids", profileEvidenceIDs = "profile_evidence_ids", effectStatus = "effect_status"
    }
}

public struct Passage: Decodable, Sendable {
    public let chunkID: String
    public let field: String
    public let heading: String
    public let start: Int
    public let text: String
    enum CodingKeys: String, CodingKey { case field, heading, start, text; case chunkID = "chunk_id" }
}

public struct CatalogDetail: Decodable, Sendable {
    public let resource: JSONValue
    public let versionID: String
    public let contentHash: String
    public let sources: [JSONValue]
    public let chunks: [Passage]
    enum CodingKeys: String, CodingKey {
        case resource, sources, chunks
        case versionID = "version_id", contentHash = "content_hash"
    }
}

public struct CatalogJob: Decodable, Sendable {
    public let jobID: String
    public let kind: String
    public let status: String
    public let result: JSONValue?
    public let error: String?
    public var isFinished: Bool { ["completed", "failed", "cancelled"].contains(status) }
    enum CodingKeys: String, CodingKey { case kind, status, result, error; case jobID = "job_id" }
}
