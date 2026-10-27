import Foundation

/// TransportRecovery: one bounded sequence per generation, mirroring the
/// Android shell, and its agreement with the shared contract.
@MainActor
final class Recorder {
    var states: [(RecoveryState, Bool)] = []
    var failures: [Error?] = []
    var resumed: Int { states.filter(\.1).count }
    var phases: [RecoveryPhase] { states.map(\.0.phase) }
    var generations: Set<Int> { Set(states.map(\.0.generation)) }
}

private struct Down: Error {}
private struct SignedOut: Error {}

@MainActor
final class Counter {
    var value = 0
    func next() -> Int { value += 1; return value }
}

@main
@MainActor
struct RecoveryChecks {
    static func require(_ condition: Bool, _ message: @autoclosure () -> String = "", file: StaticString = #file, line: UInt = #line) {
        if !condition { fatalError(message(), file: file, line: line) }
    }

    static func recovery(_ recorder: Recorder, probe: @escaping @MainActor () async -> PathHealth,
                         reconnect: @escaping @MainActor () async throws -> Void = {},
                         terminal: @escaping @MainActor (Error) -> Bool = { _ in false },
                         retryDelays: [TimeInterval] = [0.03, 0.06]) -> TransportRecovery {
        TransportRecovery(probe: probe, reconnect: reconnect,
                          publish: { state, resumed, failure in recorder.states.append((state, resumed)); recorder.failures.append(failure) },
                          terminal: terminal, probeBudget: 0.3, reconnectBudget: 0.8, retryDelays: retryDelays)
    }

    static func waitFor(_ timeout: TimeInterval = 5, _ condition: () -> Bool) async {
        let deadline = Date().addingTimeInterval(timeout)
        while !condition() && Date() < deadline { try? await Task.sleep(nanoseconds: 5_000_000) }
        require(condition(), "Timed out waiting")
    }

    static func pause(_ seconds: TimeInterval) async { try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000)) }

    static func main() async {
        try! checkContract()
        await shortOutageResumesOnce()
        await expiredSessionIsReestablished()
        await longOutageRetriesWithinOneGeneration()
        await restartedServerIsNotReauthenticated()
        await halfOpenPathIsBounded()
        await handoffSupersedesCheck()
        await backgroundingAndRoutineChecks()
        await revokedSignInStopsRetrying()
        retryDelaysAreJittered()
        await pathProofEndsCheckEarly()
        networkChanges()
        print("Transport recovery generations, budgets, path proof and network change checks passed")
    }

    /// Phases, budgets and paths agree with mobile/contract/transport-recovery.json.
    static func checkContract() throws {
        let file = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("../../contract/transport-recovery.json").standardizedFileURL
        let contract = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as! [String: Any]
        require(contract["event"] as? String == "stimma:transport-state")
        require(contract["healthPath"] as? String == MobileTransport.healthPath)
        require(contract["legacyHealthPath"] as? String == MobileTransport.legacyHealthPath)
        let phases = contract["phases"] as! [String: [String: Any]]
        require(Set(phases.keys) == Set(RecoveryPhase.allCases.map(\.rawValue)))
        for (name, entry) in phases {
            let phase = RecoveryPhase(rawValue: name)!
            require(entry["connectionState"] as? String == phase.connectionState, name)
            require(entry["holdRequests"] as? Bool == phase.holdsRequests, name)
        }
        let budgets = contract["budgetsMs"] as! [String: Int]
        require(budgets["checking"] == Int(TransportRecovery.probeBudget * 1000))
        require(budgets["reconnecting"] == Int(TransportRecovery.reconnectBudget * 1000))
        let json = RecoveryState(generation: 3, phase: .reconnecting, budget: 20).json
        require(json["generation"] as? Int == 3 && json["phase"] as? String == "reconnecting" && json["budgetMs"] as? Int == 20000)
    }

    static func shortOutageResumesOnce() async {
        let recorder = Recorder()
        let reconnects = Counter()
        let subject = recovery(recorder, probe: { .healthy }, reconnect: { _ = reconnects.next() })
        subject.suspend()
        require(subject.state.phase == .checking)
        subject.disrupted()
        await waitFor { subject.state.phase == .ready }
        await pause(0.1)
        require(recorder.phases == [.checking, .checking, .ready], "\(recorder.phases)")
        require(recorder.resumed == 1 && reconnects.value == 0)
        // Routine checks while ready stay silent.
        subject.routine(); await pause(0.1)
        require(recorder.states.count == 3)
    }

    static func expiredSessionIsReestablished() async {
        let recorder = Recorder()
        let reconnects = Counter()
        let subject = recovery(recorder, probe: { reconnects.value == 0 ? .sessionExpired : .healthy }, reconnect: { _ = reconnects.next() })
        subject.disrupted()
        await waitFor { subject.state.phase == .ready }
        require(recorder.phases == [.checking, .reconnecting, .ready], "\(recorder.phases)")
        require(reconnects.value == 1 && recorder.resumed == 1 && recorder.generations.count == 1)
    }

    static func longOutageRetriesWithinOneGeneration() async {
        let recorder = Recorder()
        var up = false
        let reconnects = Counter()
        let subject = recovery(recorder, probe: { up ? .healthy : .unreachable }, reconnect: { _ = reconnects.next(); if !up { throw Down() } })
        subject.disrupted()
        await waitFor { reconnects.value >= 3 }
        require(subject.state.phase == .unavailable && recorder.resumed == 0)
        up = true
        await waitFor { subject.state.phase == .ready }
        await pause(0.15)
        require(recorder.resumed == 1 && recorder.generations.count == 1 && !subject.running)
    }

    static func restartedServerIsNotReauthenticated() async {
        let recorder = Recorder()
        let probes = Counter()
        let reconnects = Counter()
        // Down for the first check and the first reconnect, back before the retry.
        let subject = recovery(recorder, probe: { probes.next() <= 1 ? .unreachable : .healthy },
                               reconnect: { _ = reconnects.next(); throw Down() })
        subject.disrupted()
        await waitFor { subject.state.phase == .ready }
        require(reconnects.value == 1 && recorder.resumed == 1)
    }

    static func halfOpenPathIsBounded() async {
        let recorder = Recorder()
        let reconnects = Counter()
        let subject = recovery(recorder, probe: {
            if reconnects.value == 0 { try? await Task.sleep(nanoseconds: 60_000_000_000); return .unreachable }
            return .healthy
        }, reconnect: { _ = reconnects.next() })
        let started = Date()
        subject.disrupted()
        await waitFor { subject.state.phase == .ready }
        require(Date().timeIntervalSince(started) < 2)
        require(recorder.phases == [.checking, .reconnecting, .ready], "\(recorder.phases)")
    }

    static func handoffSupersedesCheck() async {
        let recorder = Recorder()
        let calls = Counter()
        // The first check is on the network being left: slow, and it would fail.
        let subject = recovery(recorder, probe: {
            if calls.next() == 1 { try? await Task.sleep(nanoseconds: 250_000_000); return .unreachable }
            return .healthy
        })
        subject.disrupted()
        await pause(0.05)
        subject.disrupted()
        await waitFor { subject.state.phase == .ready }
        await pause(0.4)
        require(recorder.phases == [.checking, .checking, .ready], "\(recorder.phases)")
        require(recorder.resumed == 1 && recorder.states.last!.0.generation == 2)
    }

    static func backgroundingAndRoutineChecks() async {
        let recorder = Recorder()
        var health = PathHealth.unreachable
        let subject = recovery(recorder, probe: { health }, reconnect: { throw Down() })
        subject.disrupted()
        await waitFor { subject.state.phase == .unavailable }
        subject.suspend()
        require(!subject.running)
        let before = recorder.states.count
        await pause(0.2)
        require(recorder.states.count == before, "Recovery kept running in the background")
        health = .healthy
        subject.disrupted()
        await waitFor { subject.state.phase == .ready }
        let ready = subject.state.generation
        health = .unreachable
        subject.routine()
        await waitFor { subject.state.phase == .reconnecting || subject.state.phase == .unavailable }
        require(subject.state.generation == ready + 1, "A failed routine check must open a generation")
        subject.cancel()
    }

    static func revokedSignInStopsRetrying() async {
        let recorder = Recorder()
        let reconnects = Counter()
        let subject = recovery(recorder, probe: { .sessionExpired }, reconnect: { _ = reconnects.next(); throw SignedOut() },
                               terminal: { $0 is SignedOut }, retryDelays: [0.02])
        subject.disrupted()
        await waitFor { subject.state.phase == .unavailable }
        await pause(0.2)
        require(reconnects.value == 1 && !subject.running && recorder.failures.last! is SignedOut)
        // A network failure, by contrast, keeps retrying.
        let retries = Counter()
        let network = recovery(Recorder(), probe: { .unreachable }, reconnect: { _ = retries.next(); throw Down() },
                               terminal: { $0 is SignedOut }, retryDelays: [0.02])
        network.disrupted()
        await waitFor { retries.value >= 3 }
        network.cancel()
    }

    static func retryDelaysAreJittered() {
        var value = 0.0
        let subject = TransportRecovery(probe: { .healthy }, reconnect: {}, publish: { _, _, _ in }, random: { value })
        require(subject.retryDelay(0) == 1)
        value = 0.999
        require(subject.retryDelay(0) < 2 && subject.retryDelay(0) > 1.99)
        value = 0.5
        require(subject.retryDelay(1) == 3.75 && subject.retryDelay(3) == 15 && subject.retryDelay(99) == 15)
    }

    static func pathProofEndsCheckEarly() async {
        let recorder = Recorder()
        var answer = false
        let subject = recovery(recorder, probe: {
            while !answer && !Task.isCancelled { try? await Task.sleep(nanoseconds: 5_000_000) }
            return .healthy
        })
        subject.disrupted()
        let generation = subject.state.generation
        // Proof captured in an earlier generation says nothing about this check.
        subject.pathProven(generation: generation - 1)
        require(subject.state.phase == .checking)
        subject.pathProven(generation: generation)
        require(subject.state.phase == .ready && recorder.resumed == 1 && !subject.running)
        answer = true
        await pause(0.1)
        // The check that would have finished later is gone; ready came once.
        require(recorder.resumed == 1 && recorder.phases == [.checking, .ready])
        // Proof never cuts short re-establishing a session.
        let reconnecting = Recorder()
        let slow = recovery(reconnecting, probe: { .sessionExpired }, reconnect: { try await Task.sleep(nanoseconds: 300_000_000) })
        slow.disrupted()
        await waitFor { slow.state.phase == .reconnecting }
        slow.pathProven(generation: slow.state.generation)
        require(slow.state.phase == .reconnecting)
        slow.cancel()
    }

    static func networkChanges() {
        var changes = 0
        let tracker = NetworkChangeTracker<String> { changes += 1 }
        tracker.available("en0")
        require(changes == 0, "The first network is the starting point")
        tracker.available("en0")
        require(changes == 0, "The same network again is not a change")
        tracker.available("pdp_ip0")
        require(changes == 1, "A different default network is a change")
        tracker.unavailable()
        require(changes == 2, "Losing the default with no successor is a change")
        tracker.unavailable()
        require(changes == 2)
        tracker.available("pdp_ip0")
        require(changes == 3, "A network returning after a loss is a change")
    }
}
