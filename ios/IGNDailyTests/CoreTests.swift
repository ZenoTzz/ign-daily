import XCTest
@testable import IGNDaily

final class CoreTests: XCTestCase {
    func testArticleSnakeCaseAndRepeatedParagraphs() throws {
        let json = #"{"id":3,"url":"https://www.ign.com/articles/sample","cn_title":"标题","translation_status":"needs_review","paragraphs":[{"en":"Repeat","cn":"重复"},{"en":"Repeat","cn":"重复"},"纯中文"]}"#
        let article = try JSONDecoder().decode(Article.self, from: Data(json.utf8))
        XCTAssertEqual(article.title, "标题")
        XCTAssertEqual(article.statusLabel, "待复核")
        XCTAssertEqual(article.stableID, article.url)
        XCTAssertEqual(Set(article.paragraphs!.map(\.id)).count, 3)
        XCTAssertTrue(article.shareText.contains("纯中文"))
    }
    func testJobFailureObjectsAndMissingOptionalCollections() throws {
        let json = #"{"id":"job1","status":"failed","ids":[3],"errors":[{"id":3,"reason":"段落不完整"},"请求失败"]}"#
        let job = try JSONDecoder().decode(Job.self, from: Data(json.utf8))
        XCTAssertEqual(job.errors, ["#3 段落不完整", "请求失败"])
        XCTAssertTrue(job.results.isEmpty)
        XCTAssertNil(job.progress)
    }
    func testSourceObjectAndStringImages() throws {
        let json = #"{"paragraphs_en":["A"],"body_en":"A","images":["https://example.com/1.jpg",{"url":"https://example.com/2.jpg"},{"src":"https://example.com/3.jpg"}]}"#
        let source = try JSONDecoder().decode(SourceArticle.self, from: Data(json.utf8))
        XCTAssertEqual(source.paragraphsEN, ["A"])
        XCTAssertEqual(source.images.count, 3)
    }
    func testUnauthorizedIsExplicit() async throws {
        let api = APIClient(session: testSession())
        do {
            _ = try await api.me(token: "unit-test-only")
            XCTFail("Expected unauthorized")
        } catch APIError.unauthorized { } catch { XCTFail("Unexpected error: \(error)") }
    }
    func testConflictingWriteIsNotRetried() async throws {
        let api = APIClient(session: testSession())
        let before = CoreTestURLProtocol.writeCount
        do {
            _ = try await api.requestTranslation(date: "2026-09-06", ids: [3], token: "unit-test-only")
            XCTFail("Expected conflict")
        } catch APIError.conflict(let message) { XCTAssertEqual(message, "changed") }
        catch { XCTFail("Unexpected error: \(error)") }
        XCTAssertEqual(CoreTestURLProtocol.writeCount - before, 1)
    }
    func testTranslationIncludesExpectedArticleURLsWithoutRetryingConflict() async throws {
        let api = APIClient(session: testSession())
        let before = CoreTestURLProtocol.writeCount
        do {
            _ = try await api.requestTranslation(date: "2026-09-07", ids: [3],
                                                 expectedURLs: ["3": "https://www.ign.com/articles/stable-identity"],
                                                 token: "unit-test-only")
            XCTFail("Expected conflict")
        } catch APIError.conflict(let message) { XCTAssertEqual(message, "changed") }
        catch { XCTFail("Unexpected error: \(error)") }
        XCTAssertEqual(CoreTestURLProtocol.writeCount - before, 1)
    }
    func testPolishCreationEncodesNullAndDoesNotRetryConflict() async throws {
        let api = APIClient(session: testSession())
        let before = CoreTestURLProtocol.writeCount
        do {
            _ = try await api.savePolish(date: "2026-09-06", id: 3, url: "https://www.ign.com/articles/sample",
                                         revision: nil, draft: PolishDraft(title: "修改标题", body: "修改正文"), token: "unit-test-only")
            XCTFail("Expected conflict")
        } catch APIError.conflict(let message) { XCTAssertEqual(message, "changed") }
        catch { XCTFail("Unexpected error: \(error)") }
        XCTAssertEqual(CoreTestURLProtocol.writeCount - before, 1)
    }
    #if DEBUG
    func testDemoPolishSaveAndStaleRevisionPreservesNewerDraft() async throws {
        let api = DemoSupport.makeAPI()
        let initial = try await api.polish(date: DemoSupport.date, id: 4, token: DemoSupport.token)
        let draft = PolishDraft(title: "本地修改", subtitle: "副标题", summary: "摘要", body: "正文内容")
        let saved = try await api.savePolish(date: DemoSupport.date, id: 4, url: "https://www.ign.com/tech",
                                             revision: initial.revision, draft: draft, token: DemoSupport.token)
        XCTAssertTrue(saved.exists)
        XCTAssertNotNil(saved.revision)
        XCTAssertEqual(saved.draft.body, draft.body)
        do {
            _ = try await api.savePolish(date: DemoSupport.date, id: 4, url: "https://www.ign.com/tech",
                                         revision: initial.revision, draft: PolishDraft(body: "过时内容"), token: DemoSupport.token)
            XCTFail("Expected stale revision conflict")
        } catch APIError.conflict { } catch { XCTFail("Unexpected error: \(error)") }
        let loaded = try await api.polish(date: DemoSupport.date, id: 4, token: DemoSupport.token)
        XCTAssertEqual(loaded.revision, saved.revision)
        XCTAssertEqual(loaded.draft.body, draft.body)
    }
    #endif
    func testRejectsPathTraversalBeforeNetwork() async throws {
        let api = APIClient(session: testSession())
        do {
            _ = try await api.article(date: "../../private", id: 3, token: "unit-test-only")
            XCTFail("Expected invalid input")
        } catch APIError.invalidInput { } catch { XCTFail("Unexpected error: \(error)") }
    }
    private func testSession() -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [CoreTestURLProtocol.self]
        return URLSession(configuration: config)
    }
}
private final class CoreTestURLProtocol: URLProtocol {
    private static let counterLock = NSLock()
    private static var writes = 0
    static var writeCount: Int {
        counterLock.lock(); defer { counterLock.unlock() }
        return writes
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        XCTAssertEqual(request.url?.scheme, "https")
        XCTAssertEqual(request.url?.host, "igndaily.site")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer unit-test-only")
        let write = request.httpMethod == "POST" || request.httpMethod == "PUT"
        if write {
            Self.counterLock.lock(); Self.writes += 1; Self.counterLock.unlock()
            // URLSession exposes bodies through a stream when delivering to URLProtocol.
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
            let body = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            if request.httpMethod == "PUT" {
                XCTAssertTrue(body?["expected_revision"] is NSNull)
                XCTAssertEqual(body?["title"] as? String, "修改标题")
                XCTAssertEqual(body?["body"] as? String, "修改正文")
                XCTAssertEqual(body?["url"] as? String, "https://www.ign.com/articles/sample")
            } else {
                XCTAssertNil(body?["trigger_workflow"], "Server configuration chooses the translation owner")
                XCTAssertEqual(body?["ids"] as? [Int], [3])
                if body?["date"] as? String == "2026-09-07" {
                    XCTAssertEqual(body?["expected_urls"] as? [String: String], ["3": "https://www.ign.com/articles/stable-identity"])
                } else {
                    XCTAssertNil(body?["expected_urls"])
                }
            }
        }
        let status = write ? 409 : 401
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(#"{"detail":"changed"}"#.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { }
}
