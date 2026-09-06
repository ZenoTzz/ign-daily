import SwiftUI
import Observation

@main
struct IGNDailyApp: App {
    @State private var session = AppSession()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(session)
                .tint(.red)
                .task { await session.restore() }
        }
    }
}

@MainActor @Observable
final class AppSession {
    let api: APIClient
    var token: String?
    var username = ""
    var isRestoring = true
    var restoreError: String?

    init() {
        #if DEBUG
        api = CommandLine.arguments.contains("--demo") ? DemoSupport.makeAPI() : APIClient()
        #else
        api = APIClient()
        #endif
    }

    func restore() async {
        isRestoring = true
        restoreError = nil
        defer { isRestoring = false }
        #if DEBUG
        if CommandLine.arguments.contains("--demo") {
            token = DemoSupport.token
            username = DemoSupport.username
            return
        }
        #endif
        do {
            guard let saved = try KeychainStore.loadToken() else { return }
            let user = try await api.me(token: saved)
            username = user.username
            token = saved
        } catch APIError.unauthorized {
            expire()
        } catch {
            restoreError = error.localizedDescription
        }
    }

    func login(username: String, password: String) async throws {
        let result = try await api.login(username: username, password: password)
        try KeychainStore.saveToken(result.token)
        self.username = result.user.username
        token = result.token
        restoreError = nil
    }

    func logout() async {
        let previous = token
        expire()
        if let previous { try? await api.logout(token: previous) }
    }

    func expire() {
        token = nil
        username = ""
        #if DEBUG
        if CommandLine.arguments.contains("--demo") { return }
        #endif
        do { try KeychainStore.deleteToken() }
        catch { restoreError = "本机凭据清理失败：\(error.localizedDescription)" }
    }
}

struct RootView: View {
    @Environment(AppSession.self) private var session
    @State private var tab = 0

    var body: some View {
        Group {
            if session.isRestoring {
                ProgressView("正在连接工作台…")
            } else if let token = session.token {
                TabView(selection: $tab) {
                    WorkspaceView(api: session.api, token: token, onUnauthorized: session.expire, showJobs: { tab = 1 })
                        .tabItem { Label("工作台", systemImage: "square.grid.2x2") }.tag(0)
                    JobsView(api: session.api, token: token, onUnauthorized: session.expire)
                        .tabItem { Label("任务", systemImage: "arrow.triangle.2.circlepath") }.tag(1)
                    DictionaryView(api: session.api, token: token, onUnauthorized: session.expire)
                        .tabItem { Label("词库", systemImage: "character.book.closed") }.tag(2)
                    AccountView()
                        .tabItem { Label("我的", systemImage: "person.crop.circle") }.tag(3)
                }
                .id(token)
            } else {
                LoginView()
            }
        }
    }
}

struct LoginView: View {
    @Environment(AppSession.self) private var session
    @State private var username = ""
    @State private var password = ""
    @State private var working = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 30) {
                    VStack(alignment: .leading, spacing: 18) {
                        Image(systemName: "text.viewfinder")
                            .font(.system(size: 38, weight: .medium)).foregroundStyle(.red)
                            .frame(width: 76, height: 76).background(.red.opacity(0.09), in: RoundedRectangle(cornerRadius: 24))
                        Text("IGN Daily").font(.largeTitle.bold())
                        Text("你的新闻翻译工作台")
                            .font(.title3).foregroundStyle(.secondary)
                        Text("选文、翻译、阅读与校对。\n后台任务持续运行，进度随时回来查看。")
                            .foregroundStyle(.secondary).lineSpacing(4)
                    }.padding(.top, 42)

                    VStack(spacing: 16) {
                        TextField("网站用户名", text: $username)
                            .textContentType(.username).textInputAutocapitalization(.never).autocorrectionDisabled()
                            .accessibilityIdentifier("login.username")
                        Divider()
                        SecureField("网站密码", text: $password)
                            .textContentType(.password).submitLabel(.go)
                            .onSubmit { signIn() }.accessibilityIdentifier("login.password")
                    }.padding(20).background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 20))

                    if let message = error ?? session.restoreError {
                        Text(message).font(.callout).foregroundStyle(.red).accessibilityIdentifier("login.error")
                    }
                    Button(action: signIn) {
                        HStack {
                            if working { ProgressView().tint(.white) }
                            Text(working ? "正在登录…" : "登录工作台").fontWeight(.semibold)
                            Spacer()
                            Image(systemName: "arrow.right")
                        }.padding(.vertical, 10)
                    }
                    .buttonStyle(.borderedProminent).controlSize(.large)
                    .disabled(working || username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || password.isEmpty)
                    .accessibilityIdentifier("login.submit")
                    if session.restoreError != nil {
                        Button("重试已有登录") { Task { await session.restore() } }
                    }
                    Label("连接 igndaily.site", systemImage: "lock.shield")
                        .font(.footnote).foregroundStyle(.secondary)
                }.padding(26)
            }
            .background(Color(.systemGroupedBackground))
        }
    }

    private func signIn() {
        guard !working, !username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, !password.isEmpty else { return }
        working = true
        error = nil
        Task {
            defer { working = false }
            do {
                try await session.login(username: username.trimmingCharacters(in: .whitespacesAndNewlines), password: password)
                password = ""
            } catch { self.error = error.localizedDescription }
        }
    }
}

struct AccountView: View {
    @Environment(AppSession.self) private var session
    @State private var confirmLogout = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Label(session.username, systemImage: "person.crop.circle.fill").font(.headline)
                    LabeledContent("服务器", value: "igndaily.site")
                    LabeledContent("版本", value: "0.1.0")
                } header: { Text("当前账号") }
                Section {
                    Label("采集与翻译在服务器执行", systemImage: "server.rack")
                    Label("关闭 App 不会中断已提交任务", systemImage: "checkmark.circle")
                    Label("新闻日以北京时间 08:00 划分", systemImage: "clock")
                } header: { Text("工作方式") }
                Section {
                    Link(destination: URL(string: "https://igndaily.site")!) {
                        Label("打开网页工作台", systemImage: "safari")
                    }
                    Text("学习周报、模型配置与 Google Docs 同步可在网页工作台管理。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section {
                    Button("退出登录", role: .destructive) { confirmLogout = true }
                }
            }
            .navigationTitle("我的")
            .confirmationDialog("退出当前账号？", isPresented: $confirmLogout, titleVisibility: .visible) {
                Button("退出登录", role: .destructive) { Task { await session.logout() } }
            } message: { Text("本机登录凭据将清除，服务器上的任务继续运行。") }
        }
    }
}
