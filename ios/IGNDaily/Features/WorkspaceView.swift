import SwiftUI

struct WorkspaceView: View {
    let api: APIClient
    let token: String
    let onUnauthorized: () -> Void
    let showJobs: () -> Void
    @State private var dates: [String] = []
    @State private var date = ""
    @State private var articles: [Article] = []
    @State private var selected: Set<String> = []
    @State private var query = ""
    @State private var filter = "all"
    @State private var loading = false
    @State private var submitting = false
    @State private var error: String?
    @State private var confirmSubmission = false
    @State private var submitted = false

    private var visible: [Article] {
        articles.filter {
            (filter == "all" || (filter == "none" ? ($0.translationStatus ?? "none") == "none" : $0.translationStatus == filter)) &&
            (query.isEmpty || "\($0.title) \($0.enTitle ?? "") \($0.summary ?? "")".localizedCaseInsensitiveContains(query))
        }
    }
    private var doneCount: Int { articles.filter { $0.translationStatus == "done" }.count }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    header
                        .listRowInsets(EdgeInsets(top: 8, leading: 0, bottom: 8, trailing: 0))
                        .listRowBackground(Color.clear)
                }
                if let error {
                    Section { RetryPanel(message: error) { Task { await bootstrap() } } }
                }
                Section {
                    if loading && articles.isEmpty {
                        ProgressView("正在读取文章…").frame(maxWidth: .infinity).padding()
                    } else if visible.isEmpty {
                        ContentUnavailableView(query.isEmpty ? "没有符合条件的文章" : "未找到文章", systemImage: "newspaper", description: Text("切换日期或筛选条件，也可以下拉刷新。"))
                    } else {
                        ForEach(visible, id: \.stableID) { article in
                            articleRow(article)
                        }
                    }
                } header: {
                    HStack {
                        Text("文章队列 · \(visible.count)")
                        Spacer()
                        Button(selected.isEmpty ? "全选待翻译" : "取消选择") {
                            if selected.isEmpty { selected = Set(visible.filter(eligible).prefix(100).map(\.stableID)) }
                            else { selected.removeAll() }
                        }.textCase(nil).disabled(submitting)
                    }
                }
            }
            .navigationTitle("工作台")
            .searchable(text: $query, prompt: "搜索中英文标题")
            .refreshable { await bootstrap() }
            .task { if dates.isEmpty { await bootstrap() } }
            .task(id: date) { if !date.isEmpty { await load(date: date) } }
            .onChange(of: date) { _, _ in selected.removeAll(); articles.removeAll() }
            .safeAreaInset(edge: .bottom) {
                if !selected.isEmpty { submissionBar }
            }
            .confirmationDialog("翻译选中的 \(selected.count) 篇文章？", isPresented: $confirmSubmission, titleVisibility: .visible) {
                Button("提交翻译") { Task { await submit() } }
            } message: { Text("将由服务器调用已配置的翻译服务，可能产生 API 费用。待复核文章只有在你重新提交后才会重试。") }
            .alert("翻译请求已提交", isPresented: $submitted) {
                Button("查看任务", action: showJobs)
                Button("继续选文", role: .cancel) {}
            } message: { Text("可以离开 App，稍后在任务页查看进度。") }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 20) {
            #if DEBUG
            if CommandLine.arguments.contains("--demo") {
                Label("本地演示 · 不会提交到生产服务器", systemImage: "play.rectangle")
                    .font(.caption).foregroundStyle(.secondary)
            }
            #endif
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("IGN DAILY / EDITOR'S DESK").font(.caption2.weight(.bold)).tracking(1.4).foregroundStyle(.secondary)
                    Text("发现值得翻译的故事").font(.title2.bold())
                }
                Spacer(minLength: 4)
                Image(systemName: "text.viewfinder").font(.title2).foregroundStyle(.red)
            }
            HStack(spacing: 24) {
                metric("全部文章", value: articles.count)
                metric("已完成", value: doneCount)
                Spacer()
                Menu {
                    Picker("新闻日期", selection: $date) {
                        ForEach(dates, id: \.self) { Text($0).tag($0) }
                    }
                } label: {
                    Label(date.isEmpty ? "选择日期" : date, systemImage: "calendar")
                        .font(.subheadline.weight(.medium))
                }.disabled(submitting || dates.isEmpty)
            }
            Picker("文章状态", selection: $filter) {
                Text("全部").tag("all")
                Text("待翻译").tag("none")
                Text("待复核").tag("needs_review")
                Text("已完成").tag("done")
            }.pickerStyle(.segmented)
        }.padding(4)
    }

    private func metric(_ title: String, value: Int) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value, format: .number).font(.title2.bold()).monospacedDigit()
            Text(title).font(.caption).foregroundStyle(.secondary)
        }
    }

    private func articleRow(_ article: Article) -> some View {
        HStack(alignment: .top, spacing: 12) {
            if eligible(article) {
                Button {
                    if selected.contains(article.stableID) { selected.remove(article.stableID) }
                    else if selected.count < 100 { selected.insert(article.stableID) }
                } label: {
                    Image(systemName: selected.contains(article.stableID) ? "checkmark.circle.fill" : "circle")
                        .font(.title3).frame(width: 28, height: 44)
                        .foregroundStyle(selected.contains(article.stableID) ? Color.red : Color.secondary.opacity(0.5))
                }.buttonStyle(.borderless).disabled(submitting)
                    .accessibilityLabel("选择：\(article.title)")
                    .accessibilityIdentifier("select.\(article.id)")
            }
            NavigationLink {
                ArticleDetailView(api: api, token: token, date: date, articleID: article.id, onUnauthorized: onUnauthorized)
            } label: {
                VStack(alignment: .leading, spacing: 9) {
                    HStack {
                        Text(article.category ?? "新闻").font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        StatusBadge(status: article.translationStatus ?? "none")
                    }
                    Text(article.title).font(.headline).foregroundStyle(.primary).fixedSize(horizontal: false, vertical: true)
                    if let summary = article.summary, !summary.isEmpty {
                        Text(summary).font(.subheadline).foregroundStyle(.secondary).lineLimit(2)
                    }
                }.padding(.vertical, 8)
            }.accessibilityIdentifier("article.\(article.id)")
        }
    }

    private var submissionBar: some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                Text("已选 \(selected.count) 篇").font(.headline)
                Text("服务器后台执行").font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button {
                confirmSubmission = true
            } label: {
                HStack {
                    if submitting { ProgressView().tint(.white) }
                    Label(submitting ? "提交中" : "开始翻译", systemImage: "sparkles")
                }
            }.buttonStyle(.borderedProminent).controlSize(.large).disabled(submitting)
        }.padding().background(.regularMaterial)
    }

    private func eligible(_ article: Article) -> Bool {
        !["done", "requested", "running", "queued"].contains(article.translationStatus ?? "none")
    }

    @MainActor private func bootstrap() async {
        do {
            let response = try await api.dates(token: token)
            try Task.checkCancellation()
            dates = response.dates
            if date.isEmpty { date = response.latest ?? dates.first ?? NewsDay.current() }
            else { await load(date: date) }
        } catch is CancellationError {}
        catch APIError.unauthorized { onUnauthorized() }
        catch { self.error = error.localizedDescription }
    }

    @MainActor private func load(date requestedDate: String) async {
        loading = true
        error = nil
        defer { if date == requestedDate { loading = false } }
        do {
            let response = try await api.articles(date: requestedDate, token: token)
            try Task.checkCancellation()
            guard date == requestedDate else { return }
            articles = response.articles
            selected.formIntersection(Set(articles.filter(eligible).map(\.stableID)))
        } catch is CancellationError {}
        catch APIError.unauthorized { onUnauthorized() }
        catch { if date == requestedDate { self.error = error.localizedDescription } }
    }

    @MainActor private func submit() async {
        guard !submitting, !selected.isEmpty else { return }
        submitting = true
        error = nil
        let requestedDate = date
        let urls = selected
        defer { submitting = false }
        do {
            // Refresh IDs from stable URLs immediately before submission, never use display order.
            let current = try await api.articles(date: requestedDate, token: token)
            let chosen = current.articles.filter { urls.contains($0.stableID) }
            guard chosen.count == urls.count, chosen.allSatisfy(eligible) else {
                throw APIError.conflict("文章状态已改变，请刷新后重新选择。")
            }
            let expectedURLs = Dictionary(uniqueKeysWithValues: chosen.map { (String($0.id), $0.url) })
            _ = try await api.requestTranslation(date: requestedDate, ids: chosen.map(\.id), expectedURLs: expectedURLs, token: token)
            selected.removeAll()
            submitted = true
            await load(date: requestedDate)
        } catch APIError.unauthorized { onUnauthorized() }
        catch {
            self.error = error.localizedDescription + " 若提交时网络中断，请先在任务页确认是否已收到请求。"
        }
    }
}
