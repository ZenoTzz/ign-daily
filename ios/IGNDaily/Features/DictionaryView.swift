import SwiftUI

struct DictionaryView: View {
    let api: APIClient
    let token: String
    let onUnauthorized: () -> Void

    @State private var terms: [DictionaryTerm] = []
    @State private var candidates: [Candidate] = []
    @State private var query = ""
    @State private var category = "all"
    @State private var showsCandidates = false
    @State private var loading = false
    @State private var loaded = false
    @State private var busy = false
    @State private var errorMessage: String?
    @State private var notice: String?
    @State private var showsForm = false
    @State private var showsConfirmation = false
    @State private var review: DictionaryReview?

    private var visibleTerms: [DictionaryTerm] {
        terms.filter { matches(en: $0.en, cn: $0.cn, category: $0.category) }
            .sorted { $0.en.localizedStandardCompare($1.en) == .orderedAscending }
    }

    private var visibleCandidates: [Candidate] {
        candidates.filter {
            $0.status == "pending" && matches(en: $0.en, cn: $0.cn, category: $0.category)
        }
    }

    var body: some View {
        List {
            controls
            statusSection
            if showsCandidates {
                candidateSection
            } else {
                termSection
            }
        }
        .navigationTitle("词库")
        .tint(.red)
        .searchable(text: $query, prompt: "搜索英文或中文")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button("添加候选词", systemImage: "plus") { showsForm = true }
                    .disabled(busy)
            }
        }
        .task { if !loaded { await load() } }
        .refreshable { await load() }
        .sheet(isPresented: $showsForm) {
            DictionaryCandidateForm(api: api, token: token, onUnauthorized: onUnauthorized) {
                showsCandidates = true
                notice = "候选词已提交，审核通过后会写入正式词库。"
                await load()
            }
        }
        .confirmationDialog(
            review?.approve == true ? "批准这个候选词？" : "驳回这个候选词？",
            isPresented: $showsConfirmation,
            titleVisibility: .visible,
            presenting: review
        ) { request in
            Button(request.approve ? "确认批准并更新词库" : "确认驳回", role: request.approve ? nil : .destructive) {
                Task { await applyReview(request) }
            }
            Button("取消", role: .cancel) {}
        } message: { request in
            Text(request.approve
                 ? "将“\(request.candidate.en)”译为“\(request.candidate.cn)”。批准会更新正式词库；同名旧词条可能被替换或移动到所选分类，请确认译名和分类正确。"
                 : "“\(request.candidate.en)”将从待审核列表移除，正式词库不受影响。")
        }
    }

    private var controls: some View {
        Section {
            Picker("词库范围", selection: $showsCandidates) {
                Text("正式词库").tag(false)
                Text("待审核").tag(true)
            }
            .pickerStyle(.segmented)
            Picker("分类", selection: $category) {
                Text("全部分类").tag("all")
                ForEach(DictionaryCategory.all) { item in
                    Text(item.title).tag(item.id)
                }
            }
        } footer: {
            Text(showsCandidates ? "新译名先进入候选列表，审核通过后才用于正式翻译。" : "采集与翻译任务共享的正式译名。新增和修改译名请提交候选词。")
        }
    }

    @ViewBuilder private var statusSection: some View {
        if loading || busy {
            Section {
                HStack(spacing: 10) {
                    ProgressView()
                    Text(busy ? "正在提交审核结果…" : "正在更新词库…")
                        .foregroundStyle(.secondary)
                }
                .accessibilityElement(children: .combine)
            }
        }
        if let errorMessage {
            Section {
                Label(errorMessage, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.red)
                Button("重新加载") { Task { await load() } }
                    .disabled(loading || busy)
            }
        }
        if let notice {
            Section {
                Label(notice, systemImage: "checkmark.circle")
                    .foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder private var termSection: some View {
        if !visibleTerms.isEmpty {
            Section("\(visibleTerms.count) 个词条") {
                ForEach(visibleTerms) { term in
                    DictionaryEntryRow(en: term.en, cn: term.cn, category: term.category, note: term.note)
                }
            }
        } else if loaded && !loading && errorMessage == nil {
            emptyState
        }
    }

    @ViewBuilder private var candidateSection: some View {
        if !visibleCandidates.isEmpty {
            Section("\(visibleCandidates.count) 个待审核候选") {
                ForEach(visibleCandidates) { candidate in
                    VStack(alignment: .leading, spacing: 14) {
                        DictionaryEntryRow(en: candidate.en, cn: candidate.cn,
                                           category: candidate.category, note: candidate.note ?? "")
                        if candidate.hasConflict == true {
                            Label("与现有词条冲突，请核对后再批准", systemImage: "exclamationmark.triangle.fill")
                                .font(.subheadline)
                                .foregroundStyle(.orange)
                        }
                        ViewThatFits(in: .horizontal) {
                            HStack(spacing: 12) { reviewButtons(candidate) }
                            VStack(alignment: .leading, spacing: 10) { reviewButtons(candidate) }
                        }
                        .disabled(busy || loading)
                    }
                    .padding(.vertical, 6)
                }
            }
        } else if loaded && !loading && errorMessage == nil {
            emptyState
        }
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label(query.isEmpty && category == "all"
                  ? (showsCandidates ? "没有待审核候选" : "词库尚无词条")
                  : "没有匹配的词条", systemImage: "character.book.closed")
        } description: {
            Text(query.isEmpty && category == "all"
                 ? "点击右上角加号，提交一个新译名。"
                 : "试试其他关键词，或选择全部分类。")
        }
        .listRowBackground(Color.clear)
    }

    @ViewBuilder private func reviewButtons(_ candidate: Candidate) -> some View {
        Button {
            review = DictionaryReview(candidate: candidate, approve: true)
            showsConfirmation = true
        } label: {
            Label("批准", systemImage: "checkmark")
                .frame(minHeight: 32)
        }
        .buttonStyle(.borderedProminent)
        .accessibilityLabel("批准 \(candidate.en)")
        Button(role: .destructive) {
            review = DictionaryReview(candidate: candidate, approve: false)
            showsConfirmation = true
        } label: {
            Label("驳回", systemImage: "xmark")
                .frame(minHeight: 32)
        }
        .buttonStyle(.bordered)
        .accessibilityLabel("驳回 \(candidate.en)")
    }

    private func matches(en: String, cn: String, category value: String) -> Bool {
        let search = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return (category == "all" || category == value)
            && (search.isEmpty || en.localizedStandardContains(search) || cn.localizedStandardContains(search))
    }

    @MainActor private func load() async {
        guard !loading else { return }
        loading = true
        defer { loading = false }
        do {
            async let newTerms = api.dictionary(token: token)
            async let newCandidates = api.candidates(token: token)
            let result = try await (newTerms, newCandidates)
            terms = result.0
            candidates = result.1
            loaded = true
            errorMessage = nil
        } catch APIError.unauthorized {
            onUnauthorized()
        } catch is CancellationError {
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor private func applyReview(_ request: DictionaryReview) async {
        guard !busy else { return }
        busy = true
        notice = nil
        defer { busy = false }
        do {
            if request.approve {
                try await api.approveCandidate(id: request.candidate.id, token: token)
            } else {
                try await api.rejectCandidate(id: request.candidate.id, token: token)
            }
            candidates.removeAll { $0.id == request.candidate.id }
            notice = request.approve ? "候选词已批准，正式词库已更新。" : "候选词已驳回。"
            errorMessage = nil
            await load()
        } catch APIError.unauthorized {
            onUnauthorized()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct DictionaryReview {
    let candidate: Candidate
    let approve: Bool
}

private struct DictionaryCategory: Identifiable {
    let id: String
    let title: String

    static let all: [Self] = [
        .init(id: "games", title: "游戏"), .init(id: "movies_tv", title: "影视"),
        .init(id: "companies", title: "公司"), .init(id: "people", title: "人物"),
        .init(id: "media", title: "媒体"), .init(id: "terms", title: "术语")
    ]

    static func title(for id: String) -> String {
        all.first { $0.id == id }?.title ?? id
    }
}

private struct DictionaryEntryRow: View {
    let en: String
    let cn: String
    let category: String
    let note: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(en).font(.headline).textSelection(.enabled)
            Text(cn).font(.body).textSelection(.enabled)
            Text(DictionaryCategory.title(for: category))
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
            if !note.isEmpty {
                Text(note).font(.subheadline).foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
    }
}

private struct DictionaryCandidateForm: View {
    let api: APIClient
    let token: String
    let onUnauthorized: () -> Void
    let onSubmitted: () async -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var en = ""
    @State private var cn = ""
    @State private var category = "games"
    @State private var note = ""
    @State private var saving = false
    @State private var errorMessage: String?

    private var valid: Bool {
        !en.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !cn.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("译名") {
                    TextField("英文原名（必填）", text: $en, axis: .vertical)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField("中文译名（必填）", text: $cn, axis: .vertical)
                    Picker("分类", selection: $category) {
                        ForEach(DictionaryCategory.all) { item in
                            Text(item.title).tag(item.id)
                        }
                    }
                }
                .disabled(saving)
                Section {
                    TextField("译名来源或使用说明（选填）", text: $note, axis: .vertical)
                        .lineLimit(3...7)
                        .disabled(saving)
                } header: {
                    Text("备注")
                } footer: {
                    Text("提交只会新增候选，审核通过后才更新正式词库。若已有同名词条，请在备注中说明修改原因。")
                }
                if let errorMessage {
                    Section {
                        Label(errorMessage, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.red)
                    }
                }
                if saving {
                    Section { ProgressView("正在提交候选词…") }
                }
            }
            .navigationTitle("添加候选词")
            .navigationBarTitleDisplayMode(.inline)
            .tint(.red)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }.disabled(saving)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("提交") { Task { await submit() } }
                        .disabled(!valid || saving)
                }
            }
            .interactiveDismissDisabled(saving)
        }
    }

    @MainActor private func submit() async {
        guard valid && !saving else { return }
        saving = true
        defer { saving = false }
        do {
            try await api.submitCandidate(
                en: en.trimmingCharacters(in: .whitespacesAndNewlines),
                cn: cn.trimmingCharacters(in: .whitespacesAndNewlines),
                category: category,
                note: note.trimmingCharacters(in: .whitespacesAndNewlines), token: token
            )
            dismiss()
            await onSubmitted()
        } catch APIError.unauthorized {
            dismiss()
            onUnauthorized()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
