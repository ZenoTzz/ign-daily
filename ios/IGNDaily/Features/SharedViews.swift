import SwiftUI

struct StatusBadge: View {
    let status: String
    var color: Color {
        switch status {
        case "done": return .green
        case "running", "requested": return .orange
        case "failed", "needs_review": return .red
        default: return .secondary
        }
    }
    var label: String {
        switch status {
        case "done": return "已完成"
        case "running": return "翻译中"
        case "requested", "queued": return "已排队"
        case "failed": return "失败"
        case "needs_review": return "待复核"
        default: return "待翻译"
        }
    }
    var body: some View {
        Text(label).font(.caption.weight(.semibold)).foregroundStyle(color)
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(color.opacity(0.1), in: Capsule())
    }
}

struct RetryPanel: View {
    let message: String
    let retry: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(message, systemImage: "exclamationmark.triangle").foregroundStyle(.secondary).font(.callout)
            Button("重新加载", action: retry)
        }.padding(.vertical, 8)
    }
}

enum NewsDay {
    static func current(at now: Date = Date()) -> String {
        // The day's feed covers the 24-hour window ending at 08:00 Beijing.
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        let hour = calendar.component(.hour, from: now)
        let day = hour < 8 ? calendar.date(byAdding: .day, value: -1, to: now)! : now
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: day)
    }
}
