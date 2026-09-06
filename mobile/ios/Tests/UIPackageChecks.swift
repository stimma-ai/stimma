import Foundation

@main
struct UIPackageChecks {
    struct Fixture {
        let manifest: Data
        let archive: Data
        let parsed: UIPackageManifest
        init(_ root: URL, _ name: String) throws {
            manifest = try Data(contentsOf: root.appendingPathComponent(name + ".json"))
            archive = try Data(contentsOf: root.appendingPathComponent(name + ".tar.gz"))
            parsed = try JSONDecoder().decode(UIPackageManifest.self, from: manifest)
        }
    }
    static func check(_ condition: Bool) { precondition(condition) }
    enum Failure: Error { case interrupted, unexpectedDownload }
    static func rejected(expecting expected: UIPackageError? = nil, _ operation: () async throws -> Void) async {
        do { try await operation(); fatalError("Invalid package accepted") }
        catch { if let expected { check((error as? UIPackageError) == expected) } }
    }
    static func main() async throws {
        let fixtures = URL(fileURLWithPath: CommandLine.arguments[1])
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let one = try Fixture(fixtures, "one"), two = try Fixture(fixtures, "two"), three = try Fixture(fixtures, "three")
        let cacheRoot = root.appendingPathComponent("cache")
        let cache = UIPackageCache(directory: cacheRoot)
        let first = try await cache.resolve(manifest: one.manifest, download: { one.archive })
        check(!first.cacheHit)
        check(try String(contentsOf: first.directory.appendingPathComponent("index.html"), encoding: .utf8) == "first interface")
        let hit = try await cache.resolve(manifest: one.manifest, download: { throw Failure.unexpectedDownload })
        check(hit.cacheHit && hit.directory == first.directory)
        // Extracted contents are verified against the archive, not trusted by name.
        try Data("tampered interface".utf8).write(to: first.directory.appendingPathComponent("index.html"))
        let repaired = try await cache.resolve(manifest: one.manifest, download: { one.archive })
        check(!repaired.cacheHit)
        check(try String(contentsOf: repaired.directory.appendingPathComponent("index.html"), encoding: .utf8) == "first interface")
        try Data("unexpected".utf8).write(to: repaired.directory.appendingPathComponent("extra.js"))
        check(!(try await cache.resolve(manifest: one.manifest, download: { one.archive })).cacheHit)
        // Corrupt archives and interrupted downloads never destroy the usable package.
        await rejected { _ = try await cache.resolve(manifest: two.manifest, download: { one.archive }) }
        await rejected { _ = try await cache.resolve(manifest: two.manifest, download: { throw Failure.interrupted }) }
        check((try await cache.resolve(manifest: one.manifest, download: { throw Failure.unexpectedDownload })).cacheHit)
        let cancelled = Task {
            try await cache.resolve(manifest: two.manifest, download: {
                withUnsafeCurrentTask { $0?.cancel() }
                return two.archive
            })
        }
        do { _ = try await cancelled.value; fatalError("Cancelled download installed") }
        catch { check(error is CancellationError) }
        check(!FileManager.default.fileExists(atPath: cacheRoot.appendingPathComponent(two.parsed.hash).path))
        let interrupted = cacheRoot.appendingPathComponent(".stage-interrupted")
        try FileManager.default.createDirectory(at: interrupted, withIntermediateDirectories: false)
        _ = try await cache.resolve(manifest: one.manifest, download: { throw Failure.unexpectedDownload })
        check(!FileManager.default.fileExists(atPath: interrupted.path))
        for name in ["symlink", "hardlink", "absolute", "dotdot", "duplicate", "case-collision", "parent-file", "checksum", "truncated", "concatenated", "missing-index", "expanded-bound", "special", "directory", "bad-version", "too-many"] {
            let fixture = try Fixture(fixtures, name)
            await rejected { _ = try await cache.resolve(manifest: fixture.manifest, download: { fixture.archive }) }
        }
        var incompatible = try JSONSerialization.jsonObject(with: one.manifest) as! [String: Any]
        for field in ["formatVersion", "bridgeVersion", "apiVersion"] {
            var changed = incompatible; changed[field] = 2
            let data = try JSONSerialization.data(withJSONObject: changed)
            await rejected(expecting: .incompatible) { _ = try await cache.resolve(manifest: data, download: { throw Failure.unexpectedDownload }) }
        }
        incompatible["entrypoint"] = "../index.html"
        let invalidEntry = try JSONSerialization.data(withJSONObject: incompatible)
        await rejected(expecting: .incompatible) { _ = try await cache.resolve(manifest: invalidEntry, download: { throw Failure.unexpectedDownload }) }
        // Corrupted symlink cache entries cannot turn repair into writes outside cache.
        let outside = root.appendingPathComponent("outside")
        try Data("untouched".utf8).write(to: outside)
        let index = first.directory.appendingPathComponent("index.html")
        try FileManager.default.removeItem(at: index)
        try FileManager.default.createSymbolicLink(at: index, withDestinationURL: outside)
        _ = try await cache.resolve(manifest: one.manifest, download: { one.archive })
        check(try String(contentsOf: outside, encoding: .utf8) == "untouched")
        // Small deterministic budget exercises eviction, protected active packages,
        // and preservation of old content when protected data prevents installation.
        func cost(_ fixture: Fixture) throws -> Int {
            fixture.archive.count + fixture.parsed.unpackedBytes + (try JSONEncoder().encode(fixture.parsed)).count
        }
        let budget = try cost(one) + cost(two) + 16
        let lruRoot = root.appendingPathComponent("lru")
        let lru = UIPackageCache(directory: lruRoot, budgetBytes: budget)
        _ = try await lru.resolve(manifest: one.manifest, download: { one.archive })
        _ = try await lru.resolve(manifest: two.manifest, download: { two.archive })
        _ = try await lru.resolve(manifest: three.manifest, download: { three.archive }, protectedHashes: [one.parsed.hash])
        check(FileManager.default.fileExists(atPath: lruRoot.appendingPathComponent(one.parsed.hash).path))
        check(!FileManager.default.fileExists(atPath: lruRoot.appendingPathComponent(two.parsed.hash).path))
        await rejected { _ = try await lru.resolve(manifest: two.manifest, download: { two.archive }, protectedHashes: [one.parsed.hash, three.parsed.hash]) }
        check(FileManager.default.fileExists(atPath: lruRoot.appendingPathComponent(one.parsed.hash).path))
        check(FileManager.default.fileExists(atPath: lruRoot.appendingPathComponent(three.parsed.hash).path))
        print("UI package integrity, extraction, interruption, compatibility, cache repair and eviction checks passed")
    }
}
