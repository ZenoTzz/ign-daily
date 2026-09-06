import SwiftUI

struct JobsView: View {
    let api: APIClient
    let token: String
    let onUnauthorized: () -> Void

    @Environment(\.scenePhase) private var scenePhase
    @State private var jobs: [Job] = []
    @State private var loading = false
    @State private var loaded = false
    @State private var visible = false
    @State private var sessionExpired = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            List {
                overview
                if let errorMessage {
                    Section {
                        RetryPanel(message: errorMessage) { Task { await refresh() } }
                            .disabled(loading)
                    }
                }
                if loading && !loaded {
                    Section { ProgressView("正在读取服务器任务…") }
                } else if loaded && jobs.isEmpty && errorMessage == nil {
                    ContentUnavailableView("还没有翻译任务", systemImage: "tray",
                                           description: Text("在新闻页选择文章并提交翻译后，可以在这里查看进度和结果。"))
                        .listRowBackground(Color.clear)
                }
                ForEach(jobs) { job in
                    jobSection(job)
                }
            }
            .navigationTitle("任务")
            .tint(.red)
            .refreshable { await refresh() }
            .onAppear { visible = true }
            .onDisappear { visible = false }
            .task(id: JobsPollingIdentity(scenePhase: scenePhase, visible: visible)) {
                guard visible && scenePhase == .active else { return }
                await poll()
            }
        }
    }

    private var overview: some View {
        Section {
            Label("任务在服务器执行", systemImage: "server.rack")
                .font(.headline)
            Text("离开 App 不会中断翻译。重新打开此页会恢复服务器上的任务记录。")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        } footer: {
            Text("此页打开时每 5 秒刷新。待复核任务需要人工处理，不会自动重试。")
        }
    }

    private func jobSection(_ job: Job) -> some View {
        Section {
            VStack(alignment: .leading, spacing: 12) {
                ViewThatFits(in: .horizontal) {
                    HStack {
                        jobHeading(job)
                        Spacer(minLength: 10)
                        StatusBadge(status: job.status)
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        jobHeading(job)
                        StatusBadge(status: job.status)
                    }
                }
                if let progress = job.progress, progress.isFinite {
                    progressView(progress)
                }
                if let message = job.message, !message.isEmpty {
                    Text(message).font(.subheadline).foregroundStyle(.secondary)
                }
                if !job.ids.isEmpty {
                    Text("文章：" + job.ids.map { "#\($0)" }.joined(separator: "、"))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.vertical, 6)

            ForEach(job.results) { result in
                resultRow(result, date: job.date)
            }
            ForEach(Array(job.errors.enumerated()), id: \.offset) { entry in
                Label(entry.element, systemImage: "exclamationmark.triangle")
                    .font(.subheadline)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
            }
        } footer: {
            Text("任务编号：\(job.id)").font(.caption2).textSelection(.enabled)
        }
    }

    private func jobHeading(_ job: Job) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("\(job.ids.count) 篇文章的翻译任务").font(.headline)
            if let date = job.date, !date.isEmpty {
                Text(date).font(.subheadline).foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder private func resultRow(_ result: JobResult, date: String?) -> some View {
        if let date, !date.isEmpty {
            NavigationLink {
                ArticleDetailView(api: api, token: token, date: date,
                                  articleID: result.id, onUnauthorized: onUnauthorized)
            } label: {
                resultContent(result)
            }
            .accessibilityHint("打开文章和已有译文")
        } else {
            resultContent(result)
        }
    }

    private func resultContent(_ result: JobResult) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            ViewThatFits(in: .horizontal) {
                HStack {
                    Text("文章 #\(result.id)").font(.subheadline.weight(.semibold))
                    Spacer(minLength: 8)
                    if let status = result.status { StatusBadge(status: status) }
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text("文章 #\(result.id)").font(.subheadline.weight(.semibold))
                    if let status = result.status { StatusBadge(status: status) }
                }
            }
            if let message = result.message, !message.isEmpty {
                Text(message).font(.subheadline).foregroundStyle(.secondary)
            } else if let step = result.step, !step.isEmpty {
                Text(step).font(.subheadline).foregroundStyle(.secondary)
            }
            if let progress = result.progress, progress.isFinite {
                progressView(progress)
            }
            if let estimate = estimateText(result) {
                Label(estimate, systemImage: "clock")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 6)
    }

    private func progressView(_ progress: Double) -> some View {
        let value = min(100, max(0, progress))
        return ProgressView(value: value, total: 100) {
            Text("进度")
        } currentValueLabel: {
            Text("\(Int(value))%")
        }
        .font(.caption)
        .accessibilityValue("百分之 \(Int(value))")
    }

    private func estimateText(_ result: JobResult) -> String? {
        guard !["done", "completed", "failed", "error", "needs_review"].contains(result.status ?? ""),
              let minimum = result.etaMinSeconds, let maximum = result.etaMaxSeconds,
              minimum >= 0, maximum >= minimum, maximum > 0 else { return nil }
        let low = minimum / 60
        let high = max(1, Int((Double(maximum) / 60).rounded(.up)))
        return "预计还需 \(low)–\(high) 分钟（服务器估算）"
    }

    @MainActor private func poll() async {
        while !Task.isCancelled && visible && scenePhase == .active && !sessionExpired {
            await refresh()
            guard !sessionExpired else { return }
            do {
                try await Task.sleep(for: .seconds(5))
            } catch {
                return
            }
        }
    }

    @MainActor private func refresh() async {
        guard !loading && !sessionExpired && visible && scenePhase == .active else { return }
        loading = true
        defer { loading = false }
        do {
            let freshJobs = try await api.jobs(token: token)
            try Task.checkCancellation()
            jobs = freshJobs
            loaded = true
            errorMessage = nil
        } catch APIError.unauthorized {
            sessionExpired = true
            onUnauthorized()
        } catch is CancellationError {
        } catch {
            if !Task.isCancelled {
                errorMessage = error.localizedDescription
            }
        }
    }
}

private struct JobsPollingIdentity: Equatable {
    let scenePhase: ScenePhase
    let visible: Bool
}
