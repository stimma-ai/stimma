import AuthenticationServices
import Combine
import Foundation
import Network
import OSLog
import Security
import UIKit

struct MobileRoute: Codable, Hashable {
    let host: String
    let port: Int
    let kind: String
}

struct MobileDevice: Codable, Identifiable, Hashable {
    let deviceId: String
    let name: String
    let routes: [MobileRoute]
    let certFingerprint: String?
    let serving: Bool
    var id: String { deviceId }
}

struct MobileUser: Codable {
    let id: String
    let email: String
    let displayName: String?
    enum CodingKeys: String, CodingKey {
        case id, email
        case displayName = "display_name"
    }
}

private enum MobileAuthError: LocalizedError {
    case message(String)
    case sessionExpired
    var errorDescription: String? {
        switch self {
        case .message(let text): return text
        case .sessionExpired: return "Your session expired. Please sign in again."
        }
    }
}

@MainActor
final class MobileAuth: NSObject, ObservableObject, ASWebAuthenticationPresentationContextProviding {
    @Published var user: MobileUser?
    @Published var status = "Sign in to find your computers"
    @Published var error: String?
    let cloudURL = URL(string: "https://stimma.ai")!
    private let authSession: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.timeoutIntervalForRequest = 10
        configuration.timeoutIntervalForResource = 20
        return URLSession(configuration: configuration)
    }()
    private let firebaseKey = "AIzaSyB4xzVbmK5OnZGfs9qSwGJdPVbBoddYCvw"
    private let keychainService = "ai.stimma.mobile.auth"
    private var idToken: String?
    private var expiry = Date.distantPast
    private var anchor: UIWindow?
    private var webSession: ASWebAuthenticationSession?
    private var listener: AuthCallbackListener?
    private var callback: CheckedContinuation<String, Error>?
    private var timeoutTask: Task<Void, Never>?
    private var state = ""
    private var refreshTask: Task<String, Error>?
    private var authGeneration = UUID()
    private var loginInProgress = false
    private let logger = Logger(subsystem: "ai.stimma.mobile", category: "authentication")
    var hasSavedSession: Bool { readRefreshToken() != nil }

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        anchor ?? UIWindow()
    }

    func login(presentationAnchor: UIWindow) async {
        guard !loginInProgress else { return }
        loginInProgress = true
        defer { loginInProgress = false; anchor = nil }
        authGeneration = UUID()
        refreshTask?.cancel()
        refreshTask = nil
        error = nil
        status = "Opening sign in…"
        anchor = presentationAnchor
        state = UUID().uuidString + UUID().uuidString
        let generation = authGeneration
        do {
            let code = try await receiveBrowserCode()
            logger.notice("callback_received")
            struct Exchange: Decodable { let custom_token: String; let user: MobileUser }
            logger.notice("token_exchange")
            let exchange: Exchange = try await post(cloudURL.appendingPathComponent("api/auth/desktop/exchange"), body: ["code": code])
            struct Tokens: Decodable { let idToken: String; let refreshToken: String; let expiresIn: String }
            let url = URL(string: "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key=\(firebaseKey)")!
            logger.notice("firebase_sign_in")
            let tokens: Tokens = try await post(url, body: ["token": exchange.custom_token, "returnSecureToken": true])
            guard generation == authGeneration else { return }
            try saveRefreshToken(tokens.refreshToken)
            idToken = tokens.idToken
            expiry = Date().addingTimeInterval(Double(tokens.expiresIn) ?? 3600)
            user = exchange.user
            status = "Signed in"
            logger.notice("complete")
        } catch {
            guard generation == authGeneration else { return }
            logError(error)
            self.error = error.localizedDescription
            status = "Sign in required"
        }
        anchor = nil
    }

    func logout() {
        authGeneration = UUID()
        finishCallback(.failure(MobileAuthError.message("Sign in cancelled")))
        refreshTask?.cancel()
        refreshTask = nil
        SecItemDelete(keychainQuery() as CFDictionary)
        idToken = nil
        expiry = .distantPast
        user = nil
        error = nil
        status = "Signed out"
    }

    func validIDToken() async throws -> String {
        if let token = idToken, user != nil, expiry.timeIntervalSinceNow > 120 { return token }
        if let task = refreshTask { return try await task.value }
        guard let refresh = readRefreshToken() else { throw MobileAuthError.message("Please sign in") }
        let generation = authGeneration
        let task = Task { @MainActor [self] () throws -> String in
            var request = URLRequest(url: URL(string: "https://securetoken.googleapis.com/v1/token?key=\(firebaseKey)")!)
            request.httpMethod = "POST"
            request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
            var form = URLComponents()
            form.queryItems = [URLQueryItem(name: "grant_type", value: "refresh_token"), URLQueryItem(name: "refresh_token", value: refresh)]
            request.httpBody = form.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B").data(using: .utf8)
            struct Tokens: Decodable { let id_token: String; let refresh_token: String; let expires_in: String; let user_id: String }
            let tokens: Tokens = try await perform(request)
            try Task.checkCancellation()
            guard generation == authGeneration else { throw CancellationError() }
            try saveRefreshToken(tokens.refresh_token)
            idToken = tokens.id_token
            expiry = Date().addingTimeInterval(Double(tokens.expires_in) ?? 3600)
            if user == nil {
                // Firebase user_id is not Stimma's database account id. Restore
                // the account through the same authenticated cloud endpoint as desktop.
                var accountRequest = URLRequest(url: cloudURL.appendingPathComponent("api/auth/me"))
                accountRequest.setValue("Bearer \(tokens.id_token)", forHTTPHeaderField: "Authorization")
                let account: MobileUser = try await perform(accountRequest)
                try Task.checkCancellation()
                guard generation == authGeneration else { throw CancellationError() }
                user = account
            }
            status = "Signed in"
            return tokens.id_token
        }
        refreshTask = task
        defer { if generation == authGeneration { refreshTask = nil } }
        do { return try await task.value }
        catch MobileAuthError.sessionExpired {
            if generation == authGeneration {
                logout()
                error = MobileAuthError.sessionExpired.localizedDescription
            }
            throw MobileAuthError.sessionExpired
        }
    }

    func devices() async throws -> [MobileDevice] {
        var request = URLRequest(url: cloudURL.appendingPathComponent("api/devices"))
        request.setValue("Bearer \(try await validIDToken())", forHTTPHeaderField: "Authorization")
        struct Roster: Decodable { let devices: [MobileDevice] }
        let roster: Roster = try await perform(request)
        return roster.devices.filter(\.serving)
    }

    private func receiveBrowserCode() async throws -> String {
        return try await withCheckedThrowingContinuation { continuation in
            callback = continuation
            let listener = AuthCallbackListener(state: state) { [weak self] code in
                self?.finishCallback(.success(code))
            }
            self.listener = listener
            Task { [weak self] in
                do {
                    let port = try await listener.start()
                    guard let self, self.callback != nil else { listener.stop(); return }
                    self.openBrowser(port: port)
                } catch {
                    self?.logError(error)
                    self?.finishCallback(.failure(MobileAuthError.message("Could not start the sign-in callback")))
                }
            }
            timeoutTask = Task { [weak self] in
                try? await Task.sleep(for: .seconds(300))
                guard !Task.isCancelled else { return }
                self?.finishCallback(.failure(MobileAuthError.message("Sign in timed out. Please try again.")))
            }
        }
    }

    private func openBrowser(port: UInt16) {
        var url = URLComponents(url: cloudURL.appendingPathComponent("auth/desktop-login"), resolvingAgainstBaseURL: false)!
        url.queryItems = [URLQueryItem(name: "port", value: String(port)), URLQueryItem(name: "state", value: state), URLQueryItem(name: "mode", value: "sign-in")]
        let browserState = state
        let session = ASWebAuthenticationSession(url: url.url!, callbackURLScheme: nil) { [weak self] _, failure in
            Task { @MainActor in
                guard let self, self.callback != nil, self.state == browserState else { return }
                if let failure {
                    self.logError(failure)
                    self.finishCallback(.failure(MobileAuthError.message("Sign in cancelled")))
                }
            }
        }
        #if DEBUG && targetEnvironment(simulator)
        // Isolate simulator auth from shared Safari state: iOS 18 shared
        // sessions reproducibly fail with -1005; fresh sessions load normally.
        // Physical devices retain browser SSO. Keychain sessions persist in both.
        session.prefersEphemeralWebBrowserSession = true
        #endif
        session.presentationContextProvider = self
        webSession = session
        status = "Complete sign in in your browser"
        if session.start() { logger.notice("browser_opened") }
        else { finishCallback(.failure(MobileAuthError.message("Could not open sign in"))) }
    }

    private func finishCallback(_ result: Result<String, Error>) {
        let pending = callback
        callback = nil
        listener?.stop()
        listener = nil
        timeoutTask?.cancel()
        timeoutTask = nil
        webSession?.cancel()
        webSession = nil
        pending?.resume(with: result)
    }

    private func post<T: Decodable>(_ url: URL, body: [String: Any]) async throws -> T {
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await perform(request)
    }

    private func perform<T: Decodable>(_ input: URLRequest) async throws -> T {
        var request = input
        request.timeoutInterval = 30
        let (data, response) = try await authSession.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw MobileAuthError.message("Invalid server response") }
        guard (200..<300).contains(response.statusCode) else {
            if request.url?.host == "securetoken.googleapis.com",
               [400, 401, 403].contains(response.statusCode),
               let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let failure = payload["error"] as? [String: Any],
               let message = failure["message"] as? String,
               ["INVALID_REFRESH_TOKEN", "TOKEN_EXPIRED", "USER_DISABLED", "USER_NOT_FOUND", "INVALID_GRANT"].contains(message) {
                throw MobileAuthError.sessionExpired
            }
            throw MobileAuthError.message("Authentication request failed (HTTP \(response.statusCode)). Please try signing in again.")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func logError(_ error: Error) {
        let failure = error as NSError
        // Never emit userInfo or localizedDescription: URL errors can carry
        // the callback's one-time code/state or credential-bearing requests.
        logger.error("failed domain=\(failure.domain, privacy: .public) code=\(failure.code)")
    }

    private func keychainQuery(account: String = "refresh-token") -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: keychainService, kSecAttrAccount as String: account]
    }

    private func readRefreshToken(account: String = "refresh-token") -> String? {
        var query = keychainQuery(account: account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private func saveRefreshToken(_ token: String, account: String = "refresh-token") throws {
        let query = keychainQuery(account: account)
        let value: [String: Any] = [kSecValueData as String: Data(token.utf8), kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        var result = SecItemUpdate(query as CFDictionary, value as CFDictionary)
        if result == errSecItemNotFound {
            var item = query
            value.forEach { item[$0.key] = $0.value }
            result = SecItemAdd(item as CFDictionary, nil)
        }
        guard result == errSecSuccess else {
            logger.error("keychain_save_failed status=\(result)")
            throw MobileAuthError.message("Could not securely save your sign-in session")
        }
    }

    #if DEBUG && targetEnvironment(simulator)
    func checkAuthNetwork() async throws {
        // Deliberately invalid credentials: check transport and HTTP responses
        // without creating a login session, consuming a real code, or storing tokens.
        let checks: [(String, String, [String: Any]?, Set<Int>)] = [
            ("exchange", "https://stimma.ai/api/auth/desktop/exchange", ["code": "simulator-network-check"], [400, 401]),
            ("firebase", "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key=\(firebaseKey)", ["token": "invalid-simulator-test-token", "returnSecureToken": true], [400]),
            ("refresh", "https://securetoken.googleapis.com/v1/token?key=\(firebaseKey)", [:], [400]),
            ("account", "https://stimma.ai/api/auth/me", nil, [401]),
            ("devices", "https://stimma.ai/api/devices", nil, [401]),
            ("exchange-repeat", "https://stimma.ai/api/auth/desktop/exchange", ["code": "simulator-network-check"], [400, 401]),
        ]
        for (name, address, body, expected) in checks {
            var request = URLRequest(url: URL(string: address)!)
            request.timeoutInterval = 20
            if let body {
                request.httpMethod = "POST"
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                request.httpBody = try JSONSerialization.data(withJSONObject: body)
            }
            if name == "refresh" {
                request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
                request.httpBody = Data("grant_type=refresh_token&refresh_token=invalid-simulator-test-token".utf8)
            }
            do {
                let (_, response) = try await authSession.data(for: request)
                guard let response = response as? HTTPURLResponse, expected.contains(response.statusCode) else {
                    throw MobileAuthError.message("Unexpected auth endpoint response: \(name)")
                }
                logger.notice("network_check_passed stage=\(name, privacy: .public)")
            } catch {
                throw MobileAuthError.message("Auth network check failed at \(name): \(error.localizedDescription)")
            }
        }
    }

    // Exercise the real credential storage across launches without accessing
    // the user's refresh-token item or contacting an authentication service.
    func checkKeychain(stage: String) throws {
        let account = "simulator-keychain-check"
        let query = keychainQuery(account: account)
        if stage == "write" {
            SecItemDelete(query as CFDictionary)
            try saveRefreshToken("keychain-test-first", account: account)
        } else if stage == "verify" {
            defer { SecItemDelete(query as CFDictionary) }
            guard readRefreshToken(account: account) == "keychain-test-first" else {
                throw MobileAuthError.message("Keychain did not persist across launches")
            }
            try saveRefreshToken("keychain-test-updated", account: account)
            guard readRefreshToken(account: account) == "keychain-test-updated" else {
                throw MobileAuthError.message("Keychain update failed")
            }
        } else { throw MobileAuthError.message("Invalid Keychain check") }
    }
    #endif

}
