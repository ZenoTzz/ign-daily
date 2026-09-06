import SwiftUI

struct ArticleDetailView: View {
    let api: APIClient
    let token: String
    let date: String
    let articleID: Int
    let onUnauthorized: () -> Void
    @State private var article: Article?
    @State private var source: SourceArticle?
    @State private var loading = true
    @State private var error: String?
    @State private var sourceError: String?
    @State private var mode = "cn"
    @State private var editing = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                if loading && article == nil {
                    ProgressView("正在读取文章…").frame(maxWidth: .infinity).padding(.top, 60)
                }
                if let error { RetryPanel(message: error) { Task { await load() } } }
                if let article {
                    articleHeader(article)
                    Picker("阅读模式", selection: $mode) {
                        Text("中文").tag("cn")
                        Text("对照").tag("both")
                        Text("原文").tag("en")
                    }.pickerStyle(.segmented).accessibilityIdentifier("article.mode")
                    if let sourceError, mode != "cn" {
                        RetryPanel(message: "原文缓存未能读取：\(sourceError)") { Task { await load() } }
                    }
                    articleBody(article)
                    if let images = source?.images, !images.isEmpty {
                        VStack(alignment: .leading, spacing: 16) {
                            Text("原文配图").font(.headline)
                            ForEach(Array(images.enumerated()), id: \.offset) { _, url in
                                if let imageURL = safeWebURL(url) {
                                    AsyncImage(url: imageURL) { phase in
                                        switch phase {
                                        case .success(let image): image.resizable().scaledToFit()
                                        case .failure: Label("图片暂时无法加载", systemImage: "photo").foregroundStyle(.secondary).padding()
                                        default: ProgressView().frame(maxWidth: .infinity).frame(height: 120)
                                        }
                                    }.clipShape(RoundedRectangle(cornerRadius: 14))
                                }
                            }
                        }
                    }
                    Divider()
                    if let url = safeWebURL(article.url) {
                        Link(destination: url) { Label("在 IGN 阅读原文", systemImage: "arrow.up.right.square") }
                    }
                }
            }.padding(22)
        }
        .navigationTitle("文章")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if let article {
                Button { editing = true } label: { Image(systemName: "square.and.pencil") }
                    .accessibilityLabel("编辑润色稿")
                    .accessibilityIdentifier("article.edit")
                    .disabled((article.paragraphs?.isEmpty ?? true) && (article.bodyCN?.isEmpty ?? true))
                ShareLink(item: article.shareText) { Image(systemName: "square.and.arrow.up") }
                    .accessibilityLabel("分享文章")
            }
        }
        .refreshable { await load() }
        .task { await load() }
        .sheet(isPresented: $editing) {
            if let article {
                PolishEditorView(api: api, token: token, date: date, articleID: articleID, articleURL: article.url, onUnauthorized: onUnauthorized)
            }
        }
        .textSelection(.enabled)
    }

    private func articleHeader(_ article: Article) -> some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack {
                Text(date).font(.caption).foregroundStyle(.secondary)
                Spacer()
                if let status = article.translationStatus { StatusBadge(status: status) }
            }
            Text(article.title).font(.title.bold()).fixedSize(horizontal: false, vertical: true)
            if let subtitle = article.subtitle, !subtitle.isEmpty { Text(subtitle).font(.title3).foregroundStyle(.secondary) }
            if let summary = article.opusSummary ?? article.summary, !summary.isEmpty {
                Text(summary).font(.callout).lineSpacing(5)
                    .padding(18).frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.red.opacity(0.06), in: RoundedRectangle(cornerRadius: 16))
            }
            if let reason = article.translationError, !reason.isEmpty {
                Label(reason, systemImage: "exclamationmark.bubble").font(.callout).foregroundStyle(.orange)
            }
        }
    }

    @ViewBuilder private func articleBody(_ article: Article) -> some View {
        if let paragraphs = article.paragraphs, !paragraphs.isEmpty {
            LazyVStack(alignment: .leading, spacing: 25) {
                ForEach(Array(paragraphs.enumerated()), id: \.offset) { index, paragraph in
                    VStack(alignment: .leading, spacing: 12) {
                        if mode != "cn" {
                            let english = paragraph.en.isEmpty ? source?.paragraphsEN[safe: index] ?? "" : paragraph.en
                            if !english.isEmpty { Text(english).font(.body).foregroundStyle(mode == "both" ? .secondary : .primary).lineSpacing(6) }
                        }
                        if mode != "en" { Text(paragraph.cn).font(.body).lineSpacing(8) }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        } else if mode == "en", let source {
            Text(source.paragraphsEN.isEmpty ? source.bodyEN ?? "" : source.paragraphsEN.joined(separator: "\n\n"))
                .font(.body).lineSpacing(7)
        } else if let body = article.bodyCN, !body.isEmpty {
            Text(body).font(.body).lineSpacing(8)
            if mode == "both", let source { Text(source.bodyEN ?? source.paragraphsEN.joined(separator: "\n\n")).foregroundStyle(.secondary).lineSpacing(6) }
        } else {
            ContentUnavailableView("全文译文尚未生成", systemImage: "text.page", description: Text("可以在工作台选择这篇文章并提交翻译。原文缓存可在“原文”中查看。"))
        }
    }

    @MainActor private func load() async {
        loading = true
        error = nil
        sourceError = nil
        defer { loading = false }
        do {
            article = try await api.article(date: date, id: articleID, token: token)
        } catch is CancellationError { return }
        catch APIError.unauthorized { onUnauthorized(); return }
        catch { self.error = error.localizedDescription; return }
        do { source = try await api.source(date: date, id: articleID, token: token) }
        catch is CancellationError {}
        catch APIError.unauthorized { onUnauthorized() }
        catch { sourceError = error.localizedDescription }
    }

    private func safeWebURL(_ value: String) -> URL? {
        guard let url = URL(string: value), ["https", "http"].contains(url.scheme?.lowercased() ?? "") else { return nil }
        return url
    }
}

private extension Array {
    subscript(safe index: Int) -> Element? { indices.contains(index) ? self[index] : nil }
}
