import Foundation

/// Waiting for work that several callers share (a token refresh, say).
/// `task.value` ignores the waiter's own cancellation, so a caller with a
/// budget would wait out a stalled shared task. Here the waiter stops as soon
/// as it is cancelled, while the shared task itself carries on for others.
enum SharedTask {
    private final class Waiter<T>: @unchecked Sendable {
        private let lock = NSLock()
        private var continuation: CheckedContinuation<T, Error>?
        private var finished = false

        func start(_ continuation: CheckedContinuation<T, Error>) {
            lock.lock()
            if finished { lock.unlock(); continuation.resume(throwing: CancellationError()); return }
            self.continuation = continuation
            lock.unlock()
        }

        func finish(_ result: Result<T, Error>) {
            lock.lock()
            finished = true
            let pending = continuation
            continuation = nil
            lock.unlock()
            pending?.resume(with: result)
        }
    }

    static func value<T: Sendable>(of task: Task<T, Error>) async throws -> T {
        let waiter = Waiter<T>()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                waiter.start(continuation)
                Task { waiter.finish(await task.result) }
            }
        } onCancel: {
            waiter.finish(.failure(CancellationError()))
        }
    }
}
