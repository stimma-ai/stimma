import Foundation
import CryptoKit

/// Preferences belong to an account/server, never to a temporary loopback port.
/// Cookies, sessionStorage and other session data remain in the ephemeral WebView.
final class LocalStoragePersistence {
    private let file: URL

    init(directory: URL, accountID: String, serverID: String) {
        let scope = try! JSONEncoder().encode([accountID, serverID])
        let name = SHA256.hash(data: scope).map { String(format: "%02x", $0) }.joined()
        file = directory.appendingPathComponent(name + ".json")
    }

    func load() throws -> [String: String] {
        guard FileManager.default.fileExists(atPath: file.path) else { return [:] }
        return try JSONDecoder().decode([String: String].self, from: Data(contentsOf: file))
    }

    func save(_ values: [String: String]) throws {
        let data = try JSONEncoder().encode(values)
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: file, options: .atomic)
    }

    static func script(values: [String: String], origin: URL) throws -> String {
        let json = String(decoding: try JSONEncoder().encode(values), as: UTF8.self)
        let seed = String(decoding: try JSONEncoder().encode(json), as: UTF8.self)
        let address = String(decoding: try JSONEncoder().encode(origin.absoluteString), as: UTF8.self)
        return "(" + bootstrap + ")(JSON.parse(\(seed)), \(address));"
    }

    // Runs synchronously at document start, before module-level preference reads.
    // Keep real Web Storage semantics (including quota errors and sessionStorage).
    static let bootstrap = #"""
    function(seed, origin) {
        if (window !== window.top || location.origin !== origin ||
            /^\/(api|ws|assets)(\/|$)/.test(location.pathname)) return;
        const storage = window.localStorage;
        const proto = Storage.prototype;
        const set = proto.setItem;
        const remove = proto.removeItem;
        const clear = proto.clear;
        clear.call(storage);
        for (const [key, value] of Object.entries(seed)) set.call(storage, key, value);
        const persist = () => {
            const values = Object.create(null);
            for (let i = 0; i < storage.length; i++) {
                const key = storage.key(i);
                values[key] = storage.getItem(key);
            }
            window.webkit.messageHandlers.stimma.postMessage({
                method: 'saveLocalStorage', args: { values }
            }).catch(error => console.error('Could not save local preferences:', error));
        };
        for (const [name, original] of [['setItem', set], ['removeItem', remove], ['clear', clear]]) {
            proto[name] = function(...args) {
                const result = original.apply(this, args);
                if (this === storage) persist();
                return result;
            };
        }
        // Also capture named-property writes and changes from same-origin frames.
        window.addEventListener('storage', event => { if (event.storageArea === storage) persist(); });
        window.addEventListener('pagehide', persist);
        document.addEventListener('visibilitychange', () => { if (document.hidden) persist(); });
    }
    """#
}
