import Foundation
import CryptoKit
import zlib

struct UIPackageManifest: Codable, Equatable {
    let formatVersion: Int
    let hash: String
    let bytes: Int
    let unpackedBytes: Int
    let bridgeVersion: Int
    let apiVersion: Int
    let entrypoint: String

    func validate() throws {
        guard formatVersion == 1, bridgeVersion == 1, apiVersion == 1, entrypoint == "index.html" else {
            throw UIPackageError.incompatible
        }
        guard hash.count == 64, hash.allSatisfy({ "0123456789abcdef".contains($0) }),
              bytes > 0, bytes <= UIPackageCache.maxCompressedBytes,
              unpackedBytes > 0, unpackedBytes <= UIPackageCache.maxExpandedBytes else {
            throw UIPackageError.invalidManifest
        }
    }
}

struct UIPackageResolution {
    let directory: URL
    let hash: String
    let cacheHit: Bool
}

enum UIPackageError: LocalizedError, Equatable {
    case invalidManifest, incompatible, invalidArchive, integrity, unsafePath, budgetExceeded
    var errorDescription: String? {
        switch self {
        case .invalidManifest: return "The server returned an invalid interface package description."
        case .incompatible: return "This server's interface needs a newer version of the Stimma app."
        case .invalidArchive: return "The server's interface package could not be unpacked."
        case .integrity: return "The interface package failed its integrity check."
        case .unsafePath: return "The interface package contains an unsupported file."
        case .budgetExceeded: return "There is not enough interface cache space while the current server interface is open."
        }
    }
}

/// Immutable content-addressed packages. A cache hit verifies both the archive and
/// every installed file; downloaded files never overlay an existing interface.
actor UIPackageCache {
    static let maxCompressedBytes = 64 * 1024 * 1024
    static let maxExpandedBytes = 128 * 1024 * 1024
    static let maxFiles = 10_000
    private let directory: URL
    private let budgetBytes: Int
    private let files = FileManager.default

    init(directory: URL, budgetBytes: Int = 256 * 1024 * 1024) {
        self.directory = directory.standardizedFileURL
        self.budgetBytes = budgetBytes
    }

    func resolve(manifest data: Data, download: () async throws -> Data,
                 protectedHashes: Set<String> = []) async throws -> UIPackageResolution {
        guard data.count <= 16_384 else { throw UIPackageError.invalidManifest }
        let manifest: UIPackageManifest
        do { manifest = try JSONDecoder().decode(UIPackageManifest.self, from: data) }
        catch { throw UIPackageError.invalidManifest }
        try manifest.validate()
        try prepareDirectory()
        let destination = directory.appendingPathComponent(manifest.hash, isDirectory: true)
        if try verifiedCache(destination, manifest: manifest) {
            try touch(destination)
            try evict(reserving: 0, protected: protectedHashes.union([manifest.hash]))
            return UIPackageResolution(directory: destination.appendingPathComponent("files"), hash: manifest.hash, cacheHit: true)
        }
        try Task.checkCancellation()
        let archive = try await download()
        try Task.checkCancellation()
        let entries = try Self.unpack(archive, manifest: manifest)
        // Another resolve may have installed this hash while our download awaited.
        if try verifiedCache(destination, manifest: manifest) {
            try touch(destination)
            return UIPackageResolution(directory: destination.appendingPathComponent("files"), hash: manifest.hash, cacheHit: true)
        }
        let storedManifest = try JSONEncoder().encode(manifest)
        let packageBytes = archive.count + manifest.unpackedBytes + storedManifest.count
        let staging = directory.appendingPathComponent(".stage-" + UUID().uuidString, isDirectory: true)
        try files.createDirectory(at: staging, withIntermediateDirectories: false)
        defer { try? files.removeItem(at: staging) }
        let content = staging.appendingPathComponent("files", isDirectory: true)
        try files.createDirectory(at: content, withIntermediateDirectories: false)
        for entry in entries {
            try Task.checkCancellation()
            let path = content.appendingPathComponent(entry.name)
            try files.createDirectory(at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
            try entry.data.write(to: path, options: .atomic)
        }
        try archive.write(to: staging.appendingPathComponent("archive.tar.gz"), options: .atomic)
        try storedManifest.write(to: staging.appendingPathComponent("manifest.json"), options: .atomic)
        try Task.checkCancellation()
        try evict(reserving: packageBytes, protected: protectedHashes)
        // An invalid cache directory is never patched in place.
        if files.fileExists(atPath: destination.path) { try files.removeItem(at: destination) }
        try files.moveItem(at: staging, to: destination)
        try touch(destination)
        return UIPackageResolution(directory: destination.appendingPathComponent("files"), hash: manifest.hash, cacheHit: false)
    }

    private func prepareDirectory() throws {
        try files.createDirectory(at: directory, withIntermediateDirectories: true)
        guard try directory.resourceValues(forKeys: [.isSymbolicLinkKey, .isDirectoryKey]).isSymbolicLink != true else {
            throw UIPackageError.unsafePath
        }
        // Staging only exists during a synchronous actor section. These are leftovers
        // from an interrupted process, never another in-flight actor download.
        for path in try files.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
        where path.lastPathComponent.hasPrefix(".stage-") {
            try files.removeItem(at: path)
        }
    }

    private func touch(_ path: URL) throws {
        try files.setAttributes([.modificationDate: Date()], ofItemAtPath: path.path)
    }

    private func verifiedCache(_ path: URL, manifest: UIPackageManifest) throws -> Bool {
        guard files.fileExists(atPath: path.path) else { return false }
        do {
            guard try path.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink != true else { return false }
            let archive = try readRegular(path.appendingPathComponent("archive.tar.gz"), expectedSize: manifest.bytes)
            let stored = try readRegular(path.appendingPathComponent("manifest.json"), maximumSize: 16_384)
            guard try JSONDecoder().decode(UIPackageManifest.self, from: stored) == manifest else { return false }
            let entries = try Self.unpack(archive, manifest: manifest)
            let root = path.appendingPathComponent("files")
            guard try root.resourceValues(forKeys: [.isSymbolicLinkKey, .isDirectoryKey]).isSymbolicLink != true,
                  try root.resourceValues(forKeys: [.isDirectoryKey]).isDirectory == true else { return false }
            var expected = Set(entries.map(\.name))
            guard let iterator = files.enumerator(atPath: root.path) else { return false }
            for case let name as String in iterator {
                let file = root.appendingPathComponent(name)
                let attributes = try file.resourceValues(forKeys: [.isSymbolicLinkKey, .isRegularFileKey, .isDirectoryKey])
                guard attributes.isSymbolicLink != true else { return false }
                if attributes.isDirectory == true { continue }
                guard attributes.isRegularFile == true, expected.remove(name) != nil else { return false }
            }
            guard expected.isEmpty else { return false }
            for entry in entries {
                try Task.checkCancellation()
                let actual = try readRegular(root.appendingPathComponent(entry.name), expectedSize: entry.data.count)
                guard SHA256.hash(data: actual) == SHA256.hash(data: entry.data) else { return false }
            }
            return true
        } catch is CancellationError { throw CancellationError() }
        catch { return false }
    }

    private func readRegular(_ path: URL, expectedSize: Int? = nil, maximumSize: Int? = nil) throws -> Data {
        let values = try path.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true, let size = values.fileSize,
              expectedSize.map({ size == $0 }) ?? true,
              maximumSize.map({ size <= $0 }) ?? true else { throw UIPackageError.integrity }
        return try Data(contentsOf: path, options: .mappedIfSafe)
    }

    private func evict(reserving: Int, protected: Set<String>) throws {
        var candidates: [(url: URL, bytes: Int, modified: Date)] = []
        var total = reserving
        for path in try files.contentsOfDirectory(at: directory, includingPropertiesForKeys: [.contentModificationDateKey]) {
            let name = path.lastPathComponent
            guard name.count == 64, name.allSatisfy({ "0123456789abcdef".contains($0) }) else { continue }
            let size = try diskBytes(path)
            total += size
            if !protected.contains(name) {
                candidates.append((path, size, (try? path.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast))
            }
        }
        // Do not remove any previous packages if protected packages make the new
        // installation impossible regardless of eviction.
        guard total - candidates.reduce(0, { $0 + $1.bytes }) <= budgetBytes else { throw UIPackageError.budgetExceeded }
        for candidate in candidates.sorted(by: { $0.modified < $1.modified }) where total > budgetBytes {
            try files.removeItem(at: candidate.url)
            total -= candidate.bytes
        }
    }

    private func diskBytes(_ path: URL) throws -> Int {
        let attributes = try path.resourceValues(forKeys: [.isSymbolicLinkKey, .isRegularFileKey, .fileSizeKey])
        if attributes.isSymbolicLink == true { return 0 }
        if attributes.isRegularFile == true { return attributes.fileSize ?? 0 }
        var total = 0
        guard let iterator = files.enumerator(at: path, includingPropertiesForKeys: [.isSymbolicLinkKey, .fileSizeKey, .isRegularFileKey]) else { return 0 }
        for case let file as URL in iterator {
            let values = try file.resourceValues(forKeys: [.isSymbolicLinkKey, .fileSizeKey, .isRegularFileKey])
            if values.isSymbolicLink == true { iterator.skipDescendants(); continue }
            if values.isRegularFile == true { total += values.fileSize ?? 0 }
        }
        return total
    }

    struct Entry { let name: String; let data: Data }

    static func unpack(_ archive: Data, manifest: UIPackageManifest) throws -> [Entry] {
        try manifest.validate()
        guard archive.count == manifest.bytes,
              SHA256.hash(data: archive).map({ String(format: "%02x", $0) }).joined() == manifest.hash else { throw UIPackageError.integrity }
        // USTAR adds one header and at most 511 bytes padding per regular file,
        // plus its zero terminator and standard tar blocking padding.
        let tar = try inflate(archive, maximum: manifest.unpackedBytes + maxFiles * 1024 + 10_240)
        guard tar.count % 512 == 0 else { throw UIPackageError.invalidArchive }
        var offset = 0, total = 0
        var entries: [Entry] = []
        var names = Set<String>()
        var caseFolded = Set<String>()
        while offset + 512 <= tar.count {
            try Task.checkCancellation()
            let header = tar.subdata(in: offset..<(offset + 512))
            if header.allSatisfy({ $0 == 0 }) {
                guard offset + 1024 <= tar.count, tar[offset...].allSatisfy({ $0 == 0 }),
                      !entries.isEmpty, total == manifest.unpackedBytes, names.contains(manifest.entrypoint) else { throw UIPackageError.invalidArchive }
                // A regular file may not also be another entry's parent, including
                // case-folding aliases on case-insensitive Apple filesystems.
                var directories = Set<String>()
                for entry in entries {
                    let components = entry.name.precomposedStringWithCanonicalMapping.lowercased().split(separator: "/")
                    guard components.count <= 32 else { throw UIPackageError.unsafePath }
                    for count in 1..<components.count {
                        directories.insert(components.prefix(count).joined(separator: "/"))
                        guard directories.count <= maxFiles else { throw UIPackageError.invalidArchive }
                        guard !caseFolded.contains(components.prefix(count).joined(separator: "/")) else { throw UIPackageError.unsafePath }
                    }
                }
                return entries
            }
            guard entries.count < maxFiles, Array(header[257..<263]) == [117, 115, 116, 97, 114, 0],
                  Array(header[263..<265]) == [48, 48], header[156] == 48 || header[156] == 0 else { throw UIPackageError.invalidArchive }
            let checksum = try octal(header[148..<156])
            let actualChecksum = header.enumerated().reduce(0) { $0 + ((148..<156).contains($1.offset) ? 32 : Int($1.element)) }
            guard checksum == actualChecksum else { throw UIPackageError.invalidArchive }
            let name = try string(header[0..<100])
            let prefix = try string(header[345..<500])
            let fullName = prefix.isEmpty ? name : prefix + "/" + name
            let parts = fullName.split(separator: "/", omittingEmptySubsequences: false)
            guard !fullName.isEmpty, fullName.utf8.count <= 255, !fullName.contains("\\"),
                  fullName.unicodeScalars.allSatisfy({ $0.value >= 32 && $0.value != 127 }),
                  parts.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }),
                  names.insert(fullName).inserted,
                  caseFolded.insert(fullName.precomposedStringWithCanonicalMapping.lowercased()).inserted,
                  try string(header[157..<257]).isEmpty else { throw UIPackageError.unsafePath }
            let size = try octal(header[124..<136])
            guard size <= manifest.unpackedBytes - total else { throw UIPackageError.invalidArchive }
            offset += 512
            guard size <= tar.count - offset else { throw UIPackageError.invalidArchive }
            entries.append(Entry(name: fullName, data: tar[offset..<(offset + size)]))
            total += size
            let paddedSize = ((size + 511) / 512) * 512
            guard paddedSize <= tar.count - offset,
                  tar[(offset + size)..<(offset + paddedSize)].allSatisfy({ $0 == 0 }) else { throw UIPackageError.invalidArchive }
            offset += paddedSize
        }
        throw UIPackageError.invalidArchive
    }

    private static func string(_ bytes: Data.SubSequence) throws -> String {
        let end = bytes.firstIndex(of: 0) ?? bytes.endIndex
        guard bytes[end...].allSatisfy({ $0 == 0 }), let string = String(data: bytes[..<end], encoding: .utf8) else { throw UIPackageError.invalidArchive }
        return string
    }

    private static func octal(_ bytes: Data.SubSequence) throws -> Int {
        guard let raw = String(data: bytes, encoding: .ascii) else { throw UIPackageError.invalidArchive }
        let value = raw.trimmingCharacters(in: CharacterSet(charactersIn: "\0 "))
        guard !value.isEmpty, value.allSatisfy({ "01234567".contains($0) }), let result = Int(value, radix: 8) else { throw UIPackageError.invalidArchive }
        return result
    }

    private static func inflate(_ data: Data, maximum: Int) throws -> Data {
        var stream = z_stream()
        guard inflateInit2_(&stream, 15 + 16, ZLIB_VERSION, Int32(MemoryLayout<z_stream>.size)) == Z_OK else { throw UIPackageError.invalidArchive }
        defer { inflateEnd(&stream) }
        return try data.withUnsafeBytes { input -> Data in
            stream.next_in = UnsafeMutablePointer(mutating: input.bindMemory(to: Bytef.self).baseAddress)
            stream.avail_in = uInt(data.count)
            var output = Data()
            output.reserveCapacity(maximum)
            var buffer = [UInt8](repeating: 0, count: 65_536)
            while true {
                try Task.checkCancellation()
                let result = buffer.withUnsafeMutableBytes { bytes -> Int32 in
                    stream.next_out = bytes.bindMemory(to: Bytef.self).baseAddress
                    stream.avail_out = uInt(bytes.count)
                    return zlib.inflate(&stream, Z_NO_FLUSH)
                }
                let produced = buffer.count - Int(stream.avail_out)
                guard produced <= maximum - output.count else { throw UIPackageError.invalidArchive }
                output.append(contentsOf: buffer.prefix(produced))
                if result == Z_STREAM_END {
                    guard stream.avail_in == 0 else { throw UIPackageError.invalidArchive }
                    return output
                }
                guard result == Z_OK, produced > 0 else { throw UIPackageError.invalidArchive }
            }
        }
    }
}
