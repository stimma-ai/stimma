import Foundation

/// A budgeted waiter on shared work (a token refresh) stops with its budget,
/// while the shared work continues and later waiters still get its result.
@main
struct SharedTaskChecks {
    static func main() async throws {
        let shared = Task<String, Error> {
            try? await Task.sleep(nanoseconds: 600_000_000) // A stalled refresh, not cancelled by any waiter.
            return "token"
        }
        let started = Date()
        let budgeted = try await withBudget(0.04) { try await SharedTask.value(of: shared) }
        let waited = Date().timeIntervalSince(started)
        precondition(budgeted == nil, "The budget should have run out")
        precondition(waited < 0.3, "A cancelled waiter waited out the shared task (\(waited) s)")
        precondition(!shared.isCancelled, "Cancelling a waiter must not cancel the shared task")
        let later = try await SharedTask.value(of: shared)
        precondition(later == "token", "Later waiters must still get the shared result")
        // A waiter cancelled before it starts waiting stops at once.
        let early = Task { () -> String? in
            withUnsafeCurrentTask { $0?.cancel() }
            return try? await SharedTask.value(of: Task<String, Error> { try await Task.sleep(nanoseconds: 5_000_000_000); return "late" })
        }
        let earlyStart = Date()
        let earlyValue = await early.value
        precondition(earlyValue == nil && Date().timeIntervalSince(earlyStart) < 0.3)
        // Errors pass through unchanged.
        struct Expired: Error {}
        do { _ = try await SharedTask.value(of: Task<String, Error> { throw Expired() }); fatalError("Error swallowed") }
        catch is Expired {}
        print("Shared task waiters stop with their own cancellation checks passed")
    }
}
