import SwiftUI
import UIKit

struct PolishEditorView: View {
    let api: APIClient
    let token: String
    let date: String
    let articleID: Int
    let articleURL: String
    let onUnauthorized: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var subtitle = ""
    @State private var summary = ""
    @State private var bodyText = ""
    @State private var baseline: [String] = []
    @State private var revision: String?
    @State private var serverCopyExists = false
    @State private var loaded = false
    @State private var loading = false
    @State private var saving = false
    @State private var conflict = false
    @State private var errorMessage: String?
    @State private var statusMessage: String?
    @State private var showsConfirmation = false
    @State private var pendingAction = EditorAction.close

    private var fields: [String] { [title, subtitle, summary, bodyText] }
    private var dirty: Bool { loaded && fields != baseline }
    private var busy: Bool { loading || saving }
    private var shareText: String {
        (fields.filter { !$0.isEmpty } + [articleURL]).joined(separator: "\n\n")
    }

    var body: some View {
        NavigationStack {
            Form {
                introduction
                if loaded {
                    titleSection
                    summarySection
                    bodySection
                    exportSection
                }
                feedbackSection
            }
            .navigationTitle("润色译文")
            .navigationBarTitleDisplayMode(.inline)
            .tint(.red)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("关闭") { request(.close) }.disabled(busy)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") { Task { await save() } }
                        .disabled(!loaded || busy || conflict || (!dirty && serverCopyExists))
                }
            }
            .interactiveDismissDisabled(dirty || busy)
            .task { if !loaded { await load() } }
            .confirmationDialog(
                pendingAction == .close ? "放弃未保存的修改？" : "用服务器内容替换当前编辑？",
                isPresented: $showsConfirmation,
                titleVisibility: .visible
            ) {
                Button(pendingAction == .close ? "放弃修改并关闭" : "放弃修改并重新加载", role: .destructive) {
                    if pendingAction == .close { dismiss() }
                    else { Task { await load() } }
                }
                Button("继续编辑", role: .cancel) {}
            } message: {
                Text("当前未保存的文字会丢失。需要保留时，请先取消并使用“分享当前文本”或“复制当前文本”。")
            }
        }
    }

    private var introduction: some View {
        Section {
            Label("\(date) · 文章 #\(articleID)", systemImage: "square.and.pencil")
                .font(.subheadline.weight(.semibold))
            Text("保存后写入服务器的润色副本，供网站读取。编辑不会自动保存，请完成后点击右上角“保存”。")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }

    private var titleSection: some View {
        Section("标题") {
            TextField("标题", text: $title, axis: .vertical)
                .font(.headline)
                .accessibilityLabel("译文标题")
            TextField("副标题（选填）", text: $subtitle, axis: .vertical)
                .accessibilityLabel("译文副标题")
        }
        .disabled(busy)
    }

    private var summarySection: some View {
        Section("摘要") {
            TextField("摘要（选填）", text: $summary, axis: .vertical)
                .lineLimit(3...10)
                .accessibilityLabel("译文摘要")
        }
        .disabled(busy)
    }

    private var bodySection: some View {
        Section {
            TextEditor(text: $bodyText)
                .frame(minHeight: 320)
                .accessibilityLabel("译文正文")
                .disabled(busy)
        } header: {
            Text("正文")
        } footer: {
            Text(dirty ? "有未保存的修改。" : (serverCopyExists ? "当前内容与已加载的服务器副本一致。" : "当前内容尚未保存为润色副本。"))
        }
    }

    private var exportSection: some View {
        Section {
            ShareLink(item: shareText) {
                Label("分享当前文本", systemImage: "square.and.arrow.up")
            }
            Button {
                UIPasteboard.general.string = shareText
                statusMessage = "当前编辑文本已复制。"
            } label: {
                Label("复制当前文本", systemImage: "doc.on.doc")
            }
            Button {
                request(.reload)
            } label: {
                Label("重新加载服务器内容", systemImage: "arrow.clockwise")
            }
            .disabled(busy)
        } footer: {
            Text("如其他设备已修改同一副本，保存会停止并保留这里的文字。可先导出，再决定是否重新加载。")
        }
    }

    @ViewBuilder private var feedbackSection: some View {
        if busy {
            Section { ProgressView(saving ? "正在保存润色副本…" : "正在读取服务器内容…") }
        }
        if conflict {
            Section {
                Label("服务器副本已被其他操作更新", systemImage: "exclamationmark.triangle.fill")
                    .font(.headline)
                    .foregroundStyle(.orange)
                Text("你的编辑仍在此处，尚未覆盖服务器内容。请先分享或复制需要保留的文字，再重新加载最新版本并合并修改。")
                    .font(.subheadline)
            }
        }
        if let errorMessage {
            Section {
                Label(errorMessage, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.red)
                if !loaded {
                    Button("重新加载") { Task { await load() } }.disabled(busy)
                }
            }
        }
        if let statusMessage {
            Section {
                Label(statusMessage, systemImage: "checkmark.circle")
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func request(_ action: EditorAction) {
        guard !busy else { return }
        pendingAction = action
        if dirty || (action == .reload && conflict) {
            showsConfirmation = true
        } else if action == .close {
            dismiss()
        } else {
            Task { await load() }
        }
    }

    @MainActor private func load() async {
        guard !busy else { return }
        loading = true
        defer { loading = false }
        do {
            let response = try await api.polish(date: date, id: articleID, token: token)
            try Task.checkCancellation()
            apply(response)
            conflict = false
            errorMessage = nil
            statusMessage = nil
        } catch APIError.unauthorized {
            onUnauthorized()
        } catch is CancellationError {
        } catch {
            if !Task.isCancelled { errorMessage = error.localizedDescription }
        }
    }

    @MainActor private func save() async {
        guard loaded && !busy && !conflict else { return }
        saving = true
        statusMessage = nil
        defer { saving = false }
        do {
            let draft = PolishDraft(title: title, subtitle: subtitle, summary: summary,
                                    body: bodyText, updatedAt: nil)
            let response = try await api.savePolish(date: date, id: articleID, url: articleURL,
                                                     revision: revision, draft: draft, token: token)
            apply(response)
            errorMessage = nil
            statusMessage = "已保存到服务器润色副本，可在网站读取。"
        } catch APIError.unauthorized {
            onUnauthorized()
        } catch APIError.conflict(let message) {
            conflict = true
            errorMessage = message
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor private func apply(_ response: PolishResponse) {
        title = response.draft.title
        subtitle = response.draft.subtitle
        summary = response.draft.summary
        bodyText = response.draft.body
        baseline = fields
        revision = response.revision
        serverCopyExists = response.exists
        loaded = true
    }
}

private enum EditorAction {
    case close
    case reload
}
