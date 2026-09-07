package ai.stimma.mobile

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/** Stable account/server preferences, independent of the loopback port and UI package. */
class LocalPreferences(context: Context, account: String, server: String) {
    private val scope = sha256(JSONArray(listOf(account, server)).toString().toByteArray())
    private val preferences = context.getSharedPreferences("local-preferences-$scope", Context.MODE_PRIVATE)
    fun load(): JSONObject = JSONObject(preferences.getString("values", "{}")!!)
    fun save(values: JSONObject) {
        require(values.keys().asSequence().all { values.get(it) is String })
        val json = values.toString()
        require(json.toByteArray().size <= 6 * 1024 * 1024)
        preferences.edit().putString("values", json).apply()
    }
    fun script(origin: String): String = "($BOOTSTRAP)(JSON.parse(${JSONObject.quote(load().toString())}), ${JSONObject.quote(origin)});"
    companion object {
        private val BOOTSTRAP = """
    function(seed, origin) {
        if (window !== window.top || location.origin !== origin ||
            /^\/(api|ws|assets)(\/|${'$'})/.test(location.pathname)) return;
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
            window.stimmaPreferences.postMessage(JSON.stringify(values));
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
        """.trimIndent()
    }
}
