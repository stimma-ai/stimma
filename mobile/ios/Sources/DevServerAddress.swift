import Foundation
import Darwin

enum DevServerAddress {
    static func parse(_ address: String) throws -> URL {
        let value = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, !value.contains(where: { $0.isWhitespace }),
              var parts = URLComponents(string: value.contains("://") ? value : "http://" + value),
              ["http", "https"].contains(parts.scheme),
              let host = parts.host, parts.user == nil, parts.password == nil,
              parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/",
              let port = parts.port, (1...65535).contains(port) else {
            throw AddressError.invalid
        }
        let literal = host.trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
        var ipv4 = in_addr()
        var ipv6 = in6_addr()
        guard inet_pton(AF_INET, literal, &ipv4) == 1 || inet_pton(AF_INET6, literal, &ipv6) == 1 else {
            throw AddressError.invalid
        }
        if port == (parts.scheme == "https" ? 443 : 80) { parts.port = nil }
        parts.path = ""
        guard let url = parts.url else { throw AddressError.invalid }
        return url
    }

    enum AddressError: LocalizedError {
        case invalid
        var errorDescription: String? {
            "Enter an IP address and frontend port, such as 192.168.1.20:9407 (IPv6: [fd00::20]:9407)."
        }
    }
}
