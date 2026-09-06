import Foundation

@main
struct LocalStorageChecks {
    static func main() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let first = LocalStoragePersistence(directory: directory, accountID: "account-a", serverID: "server-a")
        let values = ["profileId": "creative", "theme": "light", "draft": "hello 🌍\n\"world\"", "__proto__": "value"]
        try first.save(values)
        let relaunched = LocalStoragePersistence(directory: directory, accountID: "account-a", serverID: "server-a")
        let restored = try relaunched.load()
        precondition(restored == values)
        for scope in [("account-a", "server-b"), ("account-b", "server-a")] {
            let other = LocalStoragePersistence(directory: directory, accountID: scope.0, serverID: scope.1)
            let empty = try other.load()
            precondition(empty.isEmpty)
            try other.save(["profileId": "default"])
        }
        let unchanged = try first.load()
        precondition(unchanged == values)
        try relaunched.save([:])
        let cleared = try first.load()
        precondition(cleared.isEmpty)
        print("Local storage persistence checks passed")
    }
}
