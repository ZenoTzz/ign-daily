import Foundation

struct Article: Codable, Identifiable, Hashable {
    var id: Int
    var url: String
    var cnTitle: String? = nil
    var enTitle: String? = nil
    var summary: String? = nil
    var category: String? = nil
    var emoji: String? = nil
    var translationStatus: String? = nil
    var translationError: String? = nil
    var coverImage: String? = nil
    var paragraphs: [Paragraph]? = nil
    var opusSummary: String? = nil
    var bodyCN: String? = nil
    var subtitle: String? = nil
    var title: String { [cnTitle, enTitle].compactMap { $0 }.first { !$0.isEmpty } ?? "文章 #\(id)" }
    var stableID: String { url.isEmpty ? String(id) : url }
    var statusLabel: String { statusText(translationStatus ?? "none") }
    var shareText: String {
        let body = paragraphs?.map(\.cn).filter { !$0.isEmpty }.joined(separator: "\n\n")
        return [title, subtitle, opusSummary ?? summary, body?.isEmpty == false ? body : bodyCN, url]
            .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: "\n\n")
    }
    enum CodingKeys: String, CodingKey {
        case id, url, summary, category, emoji, paragraphs, subtitle
        case cnTitle = "cn_title", enTitle = "en_title", translationStatus = "translation_status"
        case translationError = "translation_error", coverImage = "cover_image", opusSummary = "opus_summary", bodyCN = "body_cn"
    }
}

struct Paragraph: Codable, Identifiable, Hashable {
    var en: String
    var cn: String
    var id: String
    init(en: String, cn: String, id: String = UUID().uuidString) { self.en = en; self.cn = cn; self.id = id }
    enum CodingKeys: String, CodingKey { case en, cn }
    init(from decoder: Decoder) throws {
        if let text = try? decoder.singleValueContainer().decode(String.self) {
            en = ""; cn = text
        } else {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            en = try c.decodeIfPresent(String.self, forKey: .en) ?? ""
            cn = try c.decodeIfPresent(String.self, forKey: .cn) ?? ""
        }
        // Array index remains unique even when the source repeats a paragraph.
        id = decoder.codingPath.map(\.stringValue).joined(separator: "/")
    }
}
struct ArticleIndex: Codable { var date: String; var articles: [Article] }
struct DatesResponse: Codable { var dates: [String]; var latest: String? }
struct User: Codable { var username: String }
struct LoginResponse: Codable { var token: String; var user: User }
struct MeResponse: Codable { var user: User }

struct Job: Codable, Identifiable {
    var id: String
    var status: String
    var date: String?
    var ids: [Int]
    var message: String?
    var progress: Double?
    var results: [JobResult]
    var errors: [String]
    var statusLabel: String { statusText(status) }
    enum CodingKeys: String, CodingKey { case id, status, date, ids, message, progress, results, errors }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        status = try c.decode(String.self, forKey: .status)
        date = try c.decodeIfPresent(String.self, forKey: .date)
        ids = try c.decodeIfPresent([Int].self, forKey: .ids) ?? []
        message = try c.decodeIfPresent(String.self, forKey: .message)
        progress = try c.decodeIfPresent(Double.self, forKey: .progress)
        results = try c.decodeIfPresent([JobResult].self, forKey: .results) ?? []
        errors = try c.decodeIfPresent([JobFailure].self, forKey: .errors)?.map(\.text) ?? []
    }
}
private struct JobFailure: Decodable {
    var text: String
    enum CodingKeys: String, CodingKey { case id, reason, message }
    init(from decoder: Decoder) throws {
        if let value = try? decoder.singleValueContainer().decode(String.self) { text = value; return }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let id = try c.decodeIfPresent(Int.self, forKey: .id)
        let message = try c.decodeIfPresent(String.self, forKey: .reason) ?? c.decodeIfPresent(String.self, forKey: .message) ?? "翻译失败"
        text = (id.map { "#\($0) " } ?? "") + message
    }
}
struct JobResult: Codable, Identifiable {
    var id: Int
    var status: String?
    var step: String?
    var message: String?
    var progress: Double?
    var etaMinSeconds: Int?
    var etaMaxSeconds: Int?
    enum CodingKeys: String, CodingKey {
        case id, status, step, message, progress
        case etaMinSeconds = "eta_min_seconds", etaMaxSeconds = "eta_max_seconds"
    }
}
struct JobsResponse: Codable { var jobs: [Job] }
struct TranslationResponse: Codable {
    var jobID: String?
    var jobIDs: [String]
    enum CodingKeys: String, CodingKey { case jobID = "job_id", jobIDs = "job_ids" }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        jobID = try c.decodeIfPresent(String.self, forKey: .jobID)
        jobIDs = try c.decodeIfPresent([String].self, forKey: .jobIDs) ?? jobID.map { [$0] } ?? []
    }
}
struct DictionaryTerm: Identifiable, Hashable {
    var en: String
    var cn: String
    var category: String
    var note: String
    var id: String { category + ":" + en }
}
struct Candidate: Codable, Identifiable {
    var id: String
    var en: String
    var cn: String
    var category: String
    var status: String
    var note: String?
    var hasConflict: Bool?
    enum CodingKeys: String, CodingKey {
        case id, en, cn, category, status, note
        case hasConflict = "has_conflict"
    }
}
struct CandidatesResponse: Codable { var candidates: [Candidate] }
struct SourceArticle: Codable {
    var paragraphsEN: [String]
    var bodyEN: String?
    var images: [String]
    var coverImage: String?
    enum CodingKeys: String, CodingKey {
        case paragraphsEN = "paragraphs_en", bodyEN = "body_en", images, coverImage = "cover_image"
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        paragraphsEN = try c.decodeIfPresent([String].self, forKey: .paragraphsEN) ?? []
        bodyEN = try c.decodeIfPresent(String.self, forKey: .bodyEN)
        coverImage = try c.decodeIfPresent(String.self, forKey: .coverImage)
        images = try c.decodeIfPresent([SourceImage].self, forKey: .images)?.map(\.url) ?? []
    }
}
private struct SourceImage: Decodable {
    var url: String
    enum CodingKeys: String, CodingKey { case url, src }
    init(from decoder: Decoder) throws {
        if let value = try? decoder.singleValueContainer().decode(String.self) { url = value; return }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        url = try c.decodeIfPresent(String.self, forKey: .url) ?? c.decode(String.self, forKey: .src)
    }
}
private func statusText(_ status: String) -> String {
    switch status {
    case "done", "completed": return "已完成"
    case "queued", "requested", "pending": return "排队中"
    case "running", "translating": return "处理中"
    case "needs_review": return "待复核"
    case "failed", "error": return "失败"
    case "none": return "未翻译"
    default: return status
    }
}

struct PolishDraft: Codable, Equatable {
    var title: String = ""
    var subtitle: String = ""
    var summary: String = ""
    var body: String = ""
    var updatedAt: String? = nil
    enum CodingKeys: String, CodingKey {
        case title, subtitle, summary, body
        case updatedAt = "updated_at"
    }
}
struct PolishResponse: Codable {
    var exists: Bool
    var revision: String?
    var draft: PolishDraft
}
