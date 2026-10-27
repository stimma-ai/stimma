package ai.stimma.mobile

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

/**
 * What a check of the WebView's own path found. Only [HEALTHY] means the
 * WebView can reach the server; a direct route that works says nothing about
 * the local listener, proxy, pool or session in between.
 */
enum class PathHealth { HEALTHY, SESSION_EXPIRED, MISSING, UNREACHABLE }

/**
 * The phases the UI sees, named as in `mobile/contract/transport-recovery.json`.
 * Requests are held while checking or reconnecting, for at most the phase's
 * budget; unavailable fails them fast while recovery keeps retrying.
 */
enum class RecoveryPhase(val wire: String, val connectionState: String) {
    CHECKING("checking", "connecting"),
    RECONNECTING("reconnecting", "connecting"),
    READY("ready", "ready"),
    UNAVAILABLE("unavailable", "unreachable"),
}

data class RecoveryState(val generation: Int, val phase: RecoveryPhase, val budgetMillis: Long) {
    fun toJson(): JSONObject = JSONObject().put("generation", generation).put("phase", phase.wire).put("budgetMs", budgetMillis)
}

/**
 * One recovery sequence at a time for the WebView's connection.
 *
 * A resume or network change opens a new generation: the WebView's own path
 * is checked within [probeBudgetMillis]; if that fails, or the session has
 * expired, the session is re-established within [reconnectBudgetMillis] and
 * the path is checked again. The generation ends [RecoveryPhase.READY] exactly
 * once, which is when the UI replaces its socket and refreshes, or
 * [RecoveryPhase.UNAVAILABLE], after which reconnection keeps retrying with
 * bounded backoff in the same generation. A newer trigger cancels an older
 * sequence, so a superseded check can never declare the connection ready.
 *
 * Budgets are enforced here, not just published, so the UI can hold requests
 * for exactly as long as native recovery may take.
 */
class TransportRecovery(
    private val scope: CoroutineScope,
    private val probe: suspend () -> PathHealth,
    private val reconnect: suspend () -> Unit,
    /** Called on every state change; `resumed` is true once per generation that reached ready after a disruption. */
    private val publish: (state: RecoveryState, resumed: Boolean, failure: Exception?) -> Unit,
    val probeBudgetMillis: Long = PROBE_BUDGET_MILLIS,
    val reconnectBudgetMillis: Long = RECONNECT_BUDGET_MILLIS,
    private val retryDelaysMillis: List<Long> = RETRY_DELAYS_MILLIS,
    /** A failure retrying cannot fix (the sign-in itself is gone): stop and let the user act. */
    private val terminal: (Exception) -> Boolean = { false },
    private val random: () -> Double = Math::random,
) {
    @Volatile var state = RecoveryState(0, RecoveryPhase.READY, 0)
        private set
    private var job: Job? = null
    private val lock = Any()

    val running get() = job?.isActive == true

    /** The app went to the background: anything in progress is obsolete, and the next foreground must re-check. */
    fun suspend() = synchronized(lock) {
        job?.cancel(); job = null
        set(RecoveryState(state.generation + 1, RecoveryPhase.CHECKING, probeBudgetMillis), resumed = false)
    }

    /** Foreground, a network change, or anything else that makes the current path suspect. */
    fun disrupted() = synchronized(lock) {
        job?.cancel()
        val generation = state.generation + 1
        set(RecoveryState(generation, RecoveryPhase.CHECKING, probeBudgetMillis), resumed = false)
        job = scope.launch { check(generation, disrupted = true) }
    }

    /** A routine check while ready. Silent unless it fails; never overlaps a running sequence. */
    fun routine() = synchronized(lock) {
        if (running) return@synchronized
        val generation = state.generation
        val disrupted = state.phase != RecoveryPhase.READY
        job = scope.launch { check(generation, disrupted) }
    }

    /** A user operation or a fresh connection replaced the transport; it is ready as installed. */
    fun reset() = synchronized(lock) {
        job?.cancel(); job = null
        set(RecoveryState(state.generation + 1, RecoveryPhase.READY, 0), resumed = false)
    }

    /**
     * The page's own socket just upgraded through the WebView path (local
     * listener, proxy, pinned upstream, session gate) to the current server:
     * that is the same proof the check is looking for, so a check still in
     * progress ends ready now instead of after its own round trips. Only a
     * check is cut short; re-establishing a session always confirms itself.
     */
    fun pathProven(generation: Int) = synchronized(lock) {
        // Proof from a socket that opened during another generation's check says nothing about this one.
        if (state.phase != RecoveryPhase.CHECKING || state.generation != generation) return@synchronized
        job?.cancel(); job = null
        set(RecoveryState(state.generation, RecoveryPhase.READY, 0), resumed = true)
    }

    /** Stop without changing what the UI was told (an explicit operation takes over). */
    fun cancel() = synchronized(lock) { job?.cancel(); job = null }

    /** Jittered between half and all of the step, so phones that lost the same server do not retry in lockstep. */
    internal fun retryDelay(attempt: Int): Long {
        val step = retryDelaysMillis[minOf(attempt, retryDelaysMillis.size - 1)]
        return step / 2 + (step / 2 * random()).toLong()
    }

    private fun set(next: RecoveryState, resumed: Boolean, failure: Exception? = null) {
        state = next
        publish(next, resumed, failure)
    }

    private fun current(generation: Int) = state.generation == generation

    private suspend fun check(generation: Int, disrupted: Boolean) {
        val health = withTimeoutOrNull(probeBudgetMillis) { probe() } ?: PathHealth.UNREACHABLE
        if (health == PathHealth.HEALTHY) {
            // Already ready means the page's own socket proved the path first (pathProven).
            synchronized(lock) { if (current(generation) && state.phase != RecoveryPhase.READY) set(RecoveryState(generation, RecoveryPhase.READY, 0), resumed = true) }
            return
        }
        // A routine check that failed is a disruption of its own.
        val recovering = synchronized(lock) {
            if (!current(generation) || disrupted && state.phase == RecoveryPhase.READY) return
            val next = if (disrupted) generation else generation + 1
            set(RecoveryState(next, RecoveryPhase.RECONNECTING, reconnectBudgetMillis), resumed = false)
            next
        }
        recover(recovering)
    }

    private suspend fun recover(generation: Int) {
        var attempt = 0
        while (true) {
            var failure: Exception? = null
            val recovered = try {
                withTimeoutOrNull(reconnectBudgetMillis) {
                    // A restarted server usually still honours the session: look before re-establishing it.
                    if (attempt > 0 && probe() == PathHealth.HEALTHY) return@withTimeoutOrNull true
                    reconnect()
                    val health = probe()
                    if (health != PathHealth.HEALTHY) throw IllegalStateException("The connection is not usable after reconnecting ($health).")
                    true
                } ?: false
            } catch (error: CancellationException) { throw error }
            catch (error: Exception) { failure = error; false }
            synchronized(lock) {
                if (!current(generation)) return
                if (recovered) { set(RecoveryState(generation, RecoveryPhase.READY, 0), resumed = true); return }
                set(RecoveryState(generation, RecoveryPhase.UNAVAILABLE, 0), resumed = false, failure = failure)
                if (failure != null && terminal(failure)) return
            }
            delay(retryDelay(attempt))
            attempt += 1
        }
    }

    companion object {
        /** One check of the WebView's path: local listener, proxy, pinned upstream and session. */
        const val PROBE_BUDGET_MILLIS = 5000L
        /**
         * Optional discovery refresh, route probes, session bootstrap and the
         * confirming check, end to end. Each step has its own shorter limit.
         */
        const val RECONNECT_BUDGET_MILLIS = 20000L
        /** After an unavailable sequence, retry with bounded, jittered backoff; foregrounding or a network change retries at once. */
        val RETRY_DELAYS_MILLIS = listOf(2000L, 5000L, 10000L, 20000L)
    }
}
