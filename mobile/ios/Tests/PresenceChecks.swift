import Foundation

@main
struct PresenceChecks {
    @MainActor
    static func main() async throws {
        let presence = MobilePresence()
        let url = URL(string: CommandLine.arguments[1])!
        var tokens = 0
        var snapshots = 0
        var states: [String] = []
        func start() {
            presence.start(cloudURL: url, token: {
                tokens += 1
                return "fixture-\(tokens)"
            }, refresh: { snapshots += 1 }, state: { states.append($0) })
        }
        func waitFor(_ condition: () -> Bool) async throws {
            for _ in 0..<200 {
                if condition() { return }
                try await Task.sleep(for: .milliseconds(50))
            }
            fatalError("Presence timed out: tokens=\(tokens), snapshots=\(snapshots), states=\(states)")
        }
        start()
        start() // Must not create a second concurrent subscription.
        try await waitFor { tokens == 2 && snapshots == 4 }
        precondition(states.contains("reconnecting"))
        precondition(states.last == "live")
        presence.stop()
        let stoppedSnapshots = snapshots
        try await Task.sleep(for: .milliseconds(250))
        precondition(snapshots == stoppedSnapshots)
        start() // Foregrounding must subscribe and fetch a new snapshot.
        try await waitFor { tokens == 3 && snapshots == 5 }
        presence.stop()
        print("Presence checks passed: authenticated observer, event updates, reconnect resync, stop and resume")
    }
}
