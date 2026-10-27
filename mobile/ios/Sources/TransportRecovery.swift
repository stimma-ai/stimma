import Foundation

/// What a check of the WebView's own path found. Only `healthy` means the
/// WebView can reach the server; a direct route that works says nothing about
/// the local listener, proxy, pool or session in between.
enum PathHealth: Equatable { case healthy, sessionExpired, missing, unreachable }

/// The phases the page sees, named as in `mobile/contract/transport-recovery.json`.
/// Requests are held while checking or reconnecting, for at most the phase's
/// budget; unavailable fails them fast while recovery keeps retrying.
enum RecoveryPhase: String, CaseIterable {
    case checking, reconnecting, ready, unavailable

    var connectionState: String {
        switch self {
        case .checking, .reconnecting: return "connecting"
        case .ready: return "ready"
        case .unavailable: return "unreachable"
        }
    }
    var holdsRequests: Bool { self == .checking || self == .reconnecting }
}

struct RecoveryState: Equatable {
    let generation: Int
    let phase: RecoveryPhase
    let budget: TimeInterval
    var json: [String: Any] { ["generation": generation, "phase": phase.rawValue, "budgetMs": Int((budget * 1000).rounded())] }
}

private struct RecoveryIncomplete: LocalizedError {
    let health: PathHealth
    var errorDescription: String? { "The connection is not usable after reconnecting." }
}

/// Run `body`, giving up (nil) after `seconds`. The body is cancelled when the
/// budget runs out, and must honour cancellation.
func withBudget<T: Sendable>(_ seconds: TimeInterval, _ body: @escaping @Sendable () async throws -> T) async throws -> T? {
    try await withThrowingTaskGroup(of: T?.self) { group in
        group.addTask { try await body() }
        group.addTask {
            try await Task.sleep(nanoseconds: UInt64(max(0, seconds) * 1_000_000_000))
            return nil
        }
        defer { group.cancelAll() }
        return try await group.next() ?? nil
    }
}

/// One recovery sequence at a time for the WebView's connection.
///
/// A resume or network change opens a new generation: the WebView's own path
/// is checked within `probeBudget`; if that fails, or the session has expired,
/// the session is re-established within `reconnectBudget` and the path is
/// checked again. The generation ends `ready` exactly once, which is when the
/// page replaces its socket and refreshes, or `unavailable`, after which
/// reconnection keeps retrying with bounded, jittered backoff in the same
/// generation. A newer trigger cancels an older sequence, so a superseded
/// check can never declare the connection ready.
///
/// Budgets are enforced here, not just published, so the page can hold
/// requests for exactly as long as native recovery may take.
@MainActor
final class TransportRecovery {
    /// One check of the WebView's path: local listener, proxy, pinned upstream and session.
    nonisolated static let probeBudget: TimeInterval = 5
    /// Optional discovery refresh, route probes, session bootstrap and the
    /// confirming check, end to end. Each step has its own shorter limit.
    nonisolated static let reconnectBudget: TimeInterval = 20
    /// After an unavailable sequence, retry with bounded, jittered backoff;
    /// foregrounding or a network change retries at once.
    nonisolated static let retryDelays: [TimeInterval] = [2, 5, 10, 20]

    private let probe: @MainActor () async -> PathHealth
    private let reconnect: @MainActor () async throws -> Void
    /// Called on every state change; `resumed` is true once per generation that reached ready after a disruption.
    private let publish: @MainActor (RecoveryState, Bool, Error?) -> Void
    /// A failure retrying cannot fix (the sign-in itself is gone): stop and let the user act.
    private let terminal: @MainActor (Error) -> Bool
    private let random: () -> Double
    let probeBudget: TimeInterval
    let reconnectBudget: TimeInterval
    private let retryDelays: [TimeInterval]

    private(set) var state = RecoveryState(generation: 0, phase: .ready, budget: 0)
    private var job: Task<Void, Never>?
    private var jobID = 0

    init(probe: @escaping @MainActor () async -> PathHealth,
         reconnect: @escaping @MainActor () async throws -> Void,
         publish: @escaping @MainActor (RecoveryState, Bool, Error?) -> Void,
         terminal: @escaping @MainActor (Error) -> Bool = { _ in false },
         probeBudget: TimeInterval = TransportRecovery.probeBudget,
         reconnectBudget: TimeInterval = TransportRecovery.reconnectBudget,
         retryDelays: [TimeInterval] = TransportRecovery.retryDelays,
         random: @escaping () -> Double = { Double.random(in: 0..<1) }) {
        self.probe = probe
        self.reconnect = reconnect
        self.publish = publish
        self.terminal = terminal
        self.probeBudget = probeBudget
        self.reconnectBudget = reconnectBudget
        self.retryDelays = retryDelays
        self.random = random
    }

    var running: Bool { job != nil }

    /// The app went to the background: anything in progress is obsolete, and the next foreground must re-check.
    func suspend() {
        stop()
        set(RecoveryState(generation: state.generation + 1, phase: .checking, budget: probeBudget), resumed: false)
    }

    /// Foreground, a network change, or anything else that makes the current path suspect.
    func disrupted() {
        stop()
        let generation = state.generation + 1
        set(RecoveryState(generation: generation, phase: .checking, budget: probeBudget), resumed: false)
        launch { await $0.check(generation, disrupted: true) }
    }

    /// A routine check while ready. Silent unless it fails; never overlaps a running sequence.
    func routine() {
        guard !running else { return }
        let generation = state.generation
        let disrupted = state.phase != .ready
        launch { await $0.check(generation, disrupted: disrupted) }
    }

    /// A user operation or a fresh connection replaced the transport; it is ready as installed.
    func reset() {
        stop()
        set(RecoveryState(generation: state.generation + 1, phase: .ready, budget: 0), resumed: false)
    }

    /// The page's own socket just upgraded through the WebView path (local
    /// listener, proxy, pinned upstream, session gate) to the current server:
    /// the same proof the check is looking for, so a check still in progress
    /// ends ready now instead of after its own round trips. Only a check is
    /// cut short; re-establishing a session always confirms itself.
    func pathProven(generation: Int) {
        // Proof from a socket that opened during another generation's check says nothing about this one.
        guard state.phase == .checking, state.generation == generation else { return }
        stop()
        set(RecoveryState(generation: generation, phase: .ready, budget: 0), resumed: true)
    }

    /// Stop without changing what the page was told (an explicit operation takes over).
    func cancel() { stop() }

    /// Jittered between half and all of the step, so phones that lost the same server do not retry in lockstep.
    func retryDelay(_ attempt: Int) -> TimeInterval {
        let step = retryDelays[min(attempt, retryDelays.count - 1)]
        return step / 2 + step / 2 * random()
    }

    private func stop() {
        job?.cancel()
        job = nil
    }

    private func launch(_ work: @escaping @MainActor (TransportRecovery) async -> Void) {
        jobID += 1
        let id = jobID
        job = Task { @MainActor [weak self] in
            guard let self else { return }
            await work(self)
            if self.jobID == id { self.job = nil }
        }
    }

    private func set(_ next: RecoveryState, resumed: Bool, failure: Error? = nil) {
        state = next
        publish(next, resumed, failure)
    }

    private func current(_ generation: Int) -> Bool { state.generation == generation && !Task.isCancelled }

    private func budgeted<T: Sendable>(_ seconds: TimeInterval, _ body: @escaping @MainActor () async throws -> T) async throws -> T? {
        try await withBudget(seconds) { try await body() }
    }

    private func check(_ generation: Int, disrupted: Bool) async {
        let health = ((try? await budgeted(probeBudget) { await self.probe() }) ?? nil) ?? .unreachable
        guard !Task.isCancelled else { return }
        if health == .healthy {
            // Already ready means the page's own socket proved the path first (pathProven).
            if current(generation) && state.phase != .ready {
                set(RecoveryState(generation: generation, phase: .ready, budget: 0), resumed: true)
            }
            return
        }
        // A routine check that failed is a disruption of its own.
        guard current(generation), !(disrupted && state.phase == .ready) else { return }
        let next = disrupted ? generation : generation + 1
        set(RecoveryState(generation: next, phase: .reconnecting, budget: reconnectBudget), resumed: false)
        await recover(next)
    }

    private func recover(_ generation: Int) async {
        var attempt = 0
        while true {
            var failure: Error?
            var recovered = false
            do {
                let first = attempt == 0
                recovered = try await budgeted(reconnectBudget) {
                    // A restarted server usually still honours the session: look before re-establishing it.
                    if !first, await self.probe() == .healthy { return true }
                    try await self.reconnect()
                    let health = await self.probe()
                    guard health == .healthy else { throw RecoveryIncomplete(health: health) }
                    return true
                } ?? false
            } catch {
                if error is CancellationError || Task.isCancelled { return }
                failure = error
            }
            guard current(generation) else { return }
            if recovered {
                set(RecoveryState(generation: generation, phase: .ready, budget: 0), resumed: true)
                return
            }
            set(RecoveryState(generation: generation, phase: .unavailable, budget: 0), resumed: false, failure: failure)
            if let failure, terminal(failure) { return }
            do { try await Task.sleep(nanoseconds: UInt64(retryDelay(attempt) * 1_000_000_000)) } catch { return }
            attempt += 1
        }
    }
}

/// Reports a change of default network: a different network becoming the
/// default, the default being lost with no successor, or a network returning
/// after the default was lost (connections from before the loss are suspect,
/// and recovery should not wait for its next retry). The first network seen is
/// the starting point, not a change. Generic so the decision is testable
/// without Network.framework paths.
final class NetworkChangeTracker<Network: Equatable> {
    private let changed: () -> Void
    private var current: Network?
    private var lost = false
    init(changed: @escaping () -> Void) { self.changed = changed }

    func available(_ network: Network) {
        let change = lost || (current != nil && current != network)
        current = network
        lost = false
        if change { changed() }
    }

    func unavailable() {
        guard current != nil else { return }
        current = nil
        lost = true
        changed()
    }
}
