package com.ipoanalyser.gmp.push

import android.content.Context
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import com.ipoanalyser.gmp.data.ApiException
import com.ipoanalyser.gmp.data.GmpApi
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.tasks.await

/**
 * This phone's account with our API.
 *
 * Registering an FCM token returns a user id + secret. Both stay in app-private
 * storage (excluded from backups by data_extraction_rules.xml); the server only
 * keeps a hash of the secret. Every tracking call sends the secret.
 */
object Account {
    private const val FILE = "account"
    private const val KEY_ID = "user_id"
    private const val KEY_SECRET = "user_secret"
    private const val KEY_TOKEN = "fcm_token"
    private val lock = Mutex()

    private fun prefs(context: Context) = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    /** False when the app was built without google-services.json (no Firebase, no push). */
    fun pushAvailable(context: Context): Boolean = FirebaseApp.getApps(context).isNotEmpty()

    /**
     * Make sure the server knows this phone's current FCM token.
     * Call on app start and from FirebaseMessagingService.onNewToken.
     */
    suspend fun sync(context: Context, newToken: String? = null): Boolean = lock.withLock {
        if (!pushAvailable(context)) return false
        val token = newToken ?: FirebaseMessaging.getInstance().token.await()
        val p = prefs(context)
        val id = p.getString(KEY_ID, null)
        val secret = p.getString(KEY_SECRET, null)
        if (id != null && secret != null) {
            if (p.getString(KEY_TOKEN, null) == token) return true
            try {
                GmpApi.updateToken(id, secret, token)
                p.edit().putString(KEY_TOKEN, token).apply()
                return true
            } catch (e: ApiException) {
                if (e.code != 401) throw e // 401: server forgot this device; register again below
            }
        }
        val account = GmpApi.register(token)
        p.edit()
            .putString(KEY_ID, account.userId)
            .putString(KEY_SECRET, account.userSecret)
            .putString(KEY_TOKEN, token)
            .apply()
        true
    }

    suspend fun trackedSlugs(context: Context): Set<String> {
        val (id, secret) = credentials(context) ?: return emptySet()
        return GmpApi.tracked(id, secret)
    }

    /** Track/untrack an IPO for the 10 AM digest. Registers the device first if needed. */
    suspend fun setTracked(context: Context, slug: String, track: Boolean) {
        if (credentials(context) == null) sync(context)
        val (id, secret) = credentials(context) ?: throw IllegalStateException("Notifications aren't set up on this phone")
        GmpApi.setTracked(id, secret, slug, track)
    }

    private fun credentials(context: Context): Pair<String, String>? {
        val p = prefs(context)
        val id = p.getString(KEY_ID, null) ?: return null
        val secret = p.getString(KEY_SECRET, null) ?: return null
        return id to secret
    }
}
