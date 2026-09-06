import Foundation

enum APIError: LocalizedError {
    case unauthorized
    case conflict(String)
    case http(Int, String)
    case invalidResponse
    case invalidInput
    var errorDescription: String? {
        switch self {
        case .unauthorized: return "登录已失效，或用户名与密码不正确，请重新登录。"
        case .conflict(let message): return "内容发生冲突：\(message)"
        case .http(let code, let message): return "请求失败（\(code)）：\(message)"
        case .invalidResponse: return "服务器返回了无法识别的数据。"
        case .invalidInput: return "请求参数不正确。"
        }
    }
}

/// No shared cookies, private response cache, credentials, or automatic write retries.
final class APIClient: @unchecked Sendable {
    private let session: URLSession
    private let redirectGuard: SameOriginRedirectGuard?
    init(session: URLSession? = nil) {
        if let session { self.session = session; redirectGuard = nil }
        else {
            let config = URLSessionConfiguration.ephemeral
            config.urlCache = nil
            config.requestCachePolicy = .reloadIgnoringLocalCacheData
            config.httpShouldSetCookies = false
            config.httpCookieStorage = nil
            config.urlCredentialStorage = nil
            config.timeoutIntervalForRequest = 30
            config.timeoutIntervalForResource = 90
            let guardDelegate = SameOriginRedirectGuard()
            redirectGuard = guardDelegate
            self.session = URLSession(configuration: config, delegate: guardDelegate, delegateQueue: nil)
        }
    }
    func login(username: String, password: String) async throws -> LoginResponse {
        try await request(["auth", "login"], method: "POST", body: ["username": username, "password": password])
    }
    func me(token: String) async throws -> User {
        let response: MeResponse = try await request(["auth", "me"], token: token)
        return response.user
    }
    func logout(token: String) async throws { try await write(["auth", "logout"], token: token) }
    func dates(token: String) async throws -> DatesResponse { try await request(["dates"], token: token) }
    func articles(date: String, token: String) async throws -> ArticleIndex {
        try validate(date: date)
        return try await request(["articles"], query: [URLQueryItem(name: "date", value: date)], token: token)
    }
    func article(date: String, id: Int, token: String) async throws -> Article {
        try validate(date: date, id: id)
        return try await request(["articles", date, String(id)], token: token)
    }
    func source(date: String, id: Int, token: String) async throws -> SourceArticle {
        try validate(date: date, id: id)
        let file: FileEnvelope = try await request(["files", "data", date, "sources", String(format: "%02d.json", id)], token: token)
        return try JSONDecoder().decode(SourceArticle.self, from: Data(file.content.utf8))
    }
    func polish(date: String, id: Int, token: String) async throws -> PolishResponse {
        try validate(date: date, id: id)
        return try await request(["articles", date, String(id), "polish"], token: token)
    }
    func savePolish(date: String, id: Int, url: String, revision: String?, draft: PolishDraft, token: String) async throws -> PolishResponse {
        try validate(date: date, id: id)
        // An explicit JSON null means create only if no draft currently exists.
        let expectedRevision: Any = revision.map { $0 as Any } ?? NSNull()
        return try await request(["articles", date, String(id), "polish"], method: "PUT", token: token,
                                 body: ["url": url, "expected_revision": expectedRevision,
                                        "title": draft.title, "subtitle": draft.subtitle,
                                        "summary": draft.summary, "body": draft.body])
    }
    func jobs(token: String) async throws -> [Job] {
        let response: JobsResponse = try await request(["jobs"], query: [URLQueryItem(name: "limit", value: "30")], token: token)
        return response.jobs
    }
    func requestTranslation(date: String, ids: [Int], expectedURLs: [String: String]? = nil, token: String) async throws -> TranslationResponse {
        try validate(date: date)
        guard !ids.isEmpty, ids.count <= 100, ids.allSatisfy({ $0 > 0 }) else { throw APIError.invalidInput }
        var body: [String: Any] = ["date": date, "ids": ids]
        if let expectedURLs { body["expected_urls"] = expectedURLs }
        return try await request(["translations", "request"], method: "POST", token: token, body: body)
    }
    func dictionary(token: String) async throws -> [DictionaryTerm] {
        let file: FileEnvelope = try await request(["files", "data", "dict.json"], token: token)
        guard let dictionary = try JSONSerialization.jsonObject(with: Data(file.content.utf8)) as? [String: Any] else { throw APIError.invalidResponse }
        var terms: [DictionaryTerm] = []
        for category in ["games", "movies_tv", "companies", "people", "media", "terms"] {
            guard let raw = dictionary[category] else { continue }
            guard let entries = raw as? [String: Any] else { throw APIError.invalidResponse }
            for (en, value) in entries {
                if let cn = value as? String { terms.append(DictionaryTerm(en: en, cn: cn, category: category, note: "")) }
                else if let entry = value as? [String: Any], let cn = entry["cn"] as? String {
                    terms.append(DictionaryTerm(en: en, cn: cn, category: category, note: entry["note"] as? String ?? ""))
                } else { throw APIError.invalidResponse }
            }
        }
        return terms.sorted { $0.en.localizedCaseInsensitiveCompare($1.en) == .orderedAscending }
    }
    func candidates(token: String) async throws -> [Candidate] {
        let response: CandidatesResponse = try await request(["dict", "candidates"], token: token)
        return response.candidates
    }
    func submitCandidate(en: String, cn: String, category: String, note: String, token: String) async throws {
        try await write(["dict", "candidates"], token: token, body: ["en": en, "cn": cn, "category": category, "note": note])
    }
    func approveCandidate(id: String, token: String) async throws { try await write(["dict", "candidates", id, "approve"], token: token) }
    func rejectCandidate(id: String, token: String) async throws { try await write(["dict", "candidates", id, "reject"], token: token) }
    private func validate(date: String, id: Int? = nil) throws {
        guard date.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil, id.map({ $0 > 0 }) ?? true else { throw APIError.invalidInput }
    }
    private func write(_ path: [String], token: String, body: [String: Any] = [:]) async throws {
        let _: Acknowledgement = try await request(path, method: "POST", token: token, body: body)
    }
    private func request<T: Decodable>(_ path: [String], query: [URLQueryItem] = [], method: String = "GET", token: String? = nil, body: [String: Any]? = nil) async throws -> T {
        var components = URLComponents(string: "https://igndaily.site/api")!
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))
        guard path.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else { throw APIError.invalidInput }
        components.percentEncodedPath += "/" + path.map { $0.addingPercentEncoding(withAllowedCharacters: allowed)! }.joined(separator: "/")
        components.queryItems = query.isEmpty ? nil : query
        guard let url = components.url else { throw APIError.invalidInput }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        try Task.checkCancellation()
        let (data, response) = try await session.data(for: request)
        try Task.checkCancellation()
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            if http.statusCode == 401 { throw APIError.unauthorized }
            let error = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            let message = error?["detail"] as? String ?? error?["message"] as? String ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            if http.statusCode == 409 { throw APIError.conflict(message) }
            throw APIError.http(http.statusCode, message)
        }
        if let envelope = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], envelope["ok"] as? Bool == false {
            throw APIError.http(http.statusCode, envelope["message"] as? String ?? "服务器未完成请求")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
private struct FileEnvelope: Decodable { var content: String }
private struct Acknowledgement: Decodable { var ok: Bool }
private final class SameOriginRedirectGuard: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        // Reject redirects so auth cannot leave the fixed API origin and writes cannot be replayed.
        completionHandler(nil)
    }
}
