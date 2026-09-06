#if DEBUG
import Foundation

/// Deterministic local fixtures. This transport never opens a network connection.
enum DemoSupport {
    static let token = "demo"
    static let username = "演示用户"
    static let date = "2026-09-06"
    static func makeAPI() -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil
        config.httpCookieStorage = nil
        config.protocolClasses = [DemoURLProtocol.self]
        return APIClient(session: URLSession(configuration: config))
    }
}
private final class DemoURLProtocol: URLProtocol {
    private static let polishLock = NSLock()
    private static var polishDocuments: [String: [String: Any]] = [:]
    private static var polishRevisions: [String: String] = [:]

    // Catch every request from this isolated session, including unexpected hosts.
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let route = request.url?.path ?? ""
        let date = DemoSupport.date
        let paragraphs: [[String: String]] = [
            ["en": "This sample article demonstrates a native reading experience. Background collection and translation remain on the server.", "cn": "这篇示例文章展示原生阅读体验。新闻采集与翻译任务仍由服务器执行，手机用于选文、查看进度和审阅结果。"],
            ["en": "Readers can compare the original paragraphs with their translations, then share the result.", "cn": "你可以逐段对照英文原文和中文译文，检查细节后分享内容。这里展示的是本地演示数据。"],
            ["en": "A review step helps preserve factual details and consistent terminology.", "cn": "复核环节用于检查事实细节，并让游戏名称、人名与专业术语保持一致。"]
        ]
        let articles: [[String: Any]] = [
            ["id": 1, "url": "https://www.ign.com/", "cn_title": "从选文到审阅，在 iPhone 上完成", "en_title": "Your editorial workflow, on iPhone", "summary": "查看新闻、提交全文翻译、逐段对照与分享。演示数据用于预览原生应用体验。", "category": "游戏新闻", "emoji": "🎮", "translation_status": "done"],
            ["id": 2, "url": "https://www.ign.com/games", "cn_title": "新一期游戏新闻，正在准备译文", "en_title": "A new edition of gaming news", "summary": "后台任务持续执行，离开应用也不会中断服务器上的翻译流程。", "category": "游戏新闻", "emoji": "🕹️", "translation_status": "requested"],
            ["id": 3, "url": "https://www.ign.com/movies", "cn_title": "值得关注的影视幕后故事", "en_title": "Behind the scenes of a film", "summary": "选中感兴趣的内容，提交到服务器的翻译队列。", "category": "影视资讯", "emoji": "🎬", "translation_status": "none"],
            ["id": 4, "url": "https://www.ign.com/tech", "cn_title": "这篇译文需要你的复核", "en_title": "An article awaiting editorial review", "summary": "质检标记帮助你及时发现需要人工确认的段落。", "category": "行业动态", "emoji": "💡", "translation_status": "needs_review", "translation_error": "演示：一个专有名词需要确认译名。"]
        ]
        var result: [String: Any] = ["detail": "Demo route not found"]
        var status = 200
        guard request.url?.host == "igndaily.site", request.url?.scheme == "https" else {
            finish(["detail": "Demo transport blocked an unexpected origin"], status: 404)
            return
        }
        if route.hasPrefix("/api/articles/\(date)/"), route.hasSuffix("/polish") {
            let parts = route.split(separator: "/")
            guard parts.count == 5, let id = Int(parts[3]), let article = articles.first(where: { $0["id"] as? Int == id }) else {
                finish(["detail": "Demo article not found"], status: 404); return
            }
            let initial: [String: Any] = ["title": article["cn_title"] ?? "", "subtitle": "",
                                          "summary": article["summary"] ?? "",
                                          "body": paragraphs.map { $0["cn"]! }.joined(separator: "\n\n")]
            if request.httpMethod == "GET" {
                Self.polishLock.lock()
                let document = Self.polishDocuments[route]
                let revision = Self.polishRevisions[route]
                Self.polishLock.unlock()
                finish(["ok": true, "exists": document != nil, "revision": revision.map { $0 as Any } ?? NSNull(), "draft": document ?? initial], status: 200)
                return
            }
            if request.httpMethod == "PUT" {
                guard let body = requestBody(), body.keys.contains("expected_revision"),
                      body["url"] as? String == article["url"] as? String,
                      ["title", "subtitle", "summary", "body"].allSatisfy({ body[$0] is String }) else {
                    finish(["detail": "Invalid demo draft request"], status: 400); return
                }
                Self.polishLock.lock()
                guard body["expected_revision"] as? String == Self.polishRevisions[route] else {
                    Self.polishLock.unlock()
                    finish(["detail": "Draft changed; reload before saving"], status: 409); return
                }
                let revision = UUID().uuidString
                var draft = body.filter { ["title", "subtitle", "summary", "body"].contains($0.key) }
                draft["updated_at"] = ISO8601DateFormatter().string(from: Date())
                Self.polishDocuments[route] = draft
                Self.polishRevisions[route] = revision
                Self.polishLock.unlock()
                finish(["ok": true, "exists": true, "revision": revision, "draft": draft], status: 200)
                return
            }
            finish(["detail": "Demo method not allowed"], status: 405); return
        }
        switch (request.httpMethod ?? "GET", route) {
        case ("POST", "/api/auth/login"):
            result = ["ok": true, "token": DemoSupport.token, "user": ["username": DemoSupport.username]]
        case ("GET", "/api/auth/me"):
            result = ["ok": true, "user": ["username": DemoSupport.username]]
        case ("POST", "/api/auth/logout"):
            result = ["ok": true]
        case ("GET", "/api/dates"):
            result = ["dates": [date], "latest": date]
        case ("GET", "/api/articles"):
            result = ["date": date, "articles": articles]
        case ("GET", _) where route.hasPrefix("/api/articles/\(date)/"):
            if let id = Int(route.split(separator: "/").last ?? ""), var article = articles.first(where: { $0["id"] as? Int == id }) {
                if id == 1 {
                    article["paragraphs"] = paragraphs
                    article["subtitle"] = "原生阅读 · 本地演示"
                    article["opus_summary"] = "用熟悉的 iPhone 操作方式，管理你的新闻翻译工作。"
                }
                result = article
            } else { status = 404 }
        case ("GET", _) where route.hasPrefix("/api/files/data/\(date)/sources/"):
            result = file(["paragraphs_en": paragraphs.map { $0["en"]! }, "body_en": paragraphs.map { $0["en"]! }.joined(separator: "\n"), "images": []])
        case ("GET", "/api/jobs"):
            result = ["jobs": [
                ["id": "demo-running", "date": date, "ids": [2], "status": "running", "message": "正在翻译正文", "progress": 58, "results": [["id": 2, "status": "running", "step": "translating", "message": "正文翻译中", "progress": 58, "eta_min_seconds": 60, "eta_max_seconds": 180]], "errors": []],
                ["id": "demo-done", "date": date, "ids": [1], "status": "done", "message": "翻译与质量检查已完成", "progress": 100, "results": [["id": 1, "status": "done", "progress": 100]], "errors": []]
            ]]
        case ("GET", "/api/files/data/dict.json"):
            result = file(["games": ["The Legend of Zelda": ["cn": "塞尔达传说", "note": "系列统一译名"], "Final Fantasy": ["cn": "最终幻想"]], "companies": ["Nintendo": ["cn": "任天堂"]], "terms": ["frame rate": ["cn": "帧率", "note": "技术术语"]]])
        case ("GET", "/api/dict/candidates"):
            result = ["candidates": [["id": "demo-term", "en": "ray tracing", "cn": "光线追踪", "category": "terms", "status": "pending", "note": "演示候选词", "has_conflict": false]]]
        case ("POST", "/api/translations/request"):
            result = ["ok": true, "job_id": "demo-running", "job_ids": ["demo-running"]]
        case ("POST", _) where route == "/api/dict/candidates" || route.hasPrefix("/api/dict/candidates/"):
            result = ["ok": true]
        default: status = 404
        }
        finish(result, status: status)
    }
    private func requestBody() -> [String: Any]? {
        var data = request.httpBody ?? Data()
        if let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var bytes = [UInt8](repeating: 0, count: 1024)
            while stream.hasBytesAvailable {
                let count = stream.read(&bytes, maxLength: bytes.count)
                if count <= 0 { break }
                data.append(contentsOf: bytes.prefix(count))
            }
        }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }
    private func file(_ content: [String: Any]) -> [String: Any] {
        let data = try! JSONSerialization.data(withJSONObject: content)
        return ["ok": true, "content": String(decoding: data, as: UTF8.self), "sha": "demo"]
    }
    private func finish(_ result: [String: Any], status: Int) {
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: try! JSONSerialization.data(withJSONObject: result))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { }
}
#endif
