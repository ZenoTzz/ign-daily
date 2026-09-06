import Foundation
import Security

enum KeychainStore {
    private static let service = "site.igndaily.ios.session"
    private static let account = "bearer-token"
    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
    }
    static func loadToken() throws -> String? {
        var lookup = query
        lookup[kSecReturnData as String] = true
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(lookup as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw KeychainError(status: status) }
        guard let data = result as? Data, let token = String(data: data, encoding: .utf8), !token.isEmpty else { throw KeychainError(status: errSecDecode) }
        return token
    }
    static func saveToken(_ token: String) throws {
        guard !token.isEmpty else { throw KeychainError(status: errSecParam) }
        let values: [String: Any] = [kSecValueData as String: Data(token.utf8), kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        let status = SecItemUpdate(query as CFDictionary, values as CFDictionary)
        if status == errSecItemNotFound {
            let insertion = query.merging(values) { _, new in new }
            let result = SecItemAdd(insertion as CFDictionary, nil)
            guard result == errSecSuccess else { throw KeychainError(status: result) }
        } else if status != errSecSuccess { throw KeychainError(status: status) }
    }
    static func deleteToken() throws {
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw KeychainError(status: status) }
    }
}
struct KeychainError: LocalizedError {
    let status: OSStatus
    var errorDescription: String? { "无法访问安全登录凭据（\(status)）。请解锁设备后重试。" }
}
