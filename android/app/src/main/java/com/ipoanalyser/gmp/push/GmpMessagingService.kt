package com.ipoanalyser.gmp.push

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/** Receives FCM token changes and foreground messages. */
class GmpMessagingService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        // Firebase rotated this phone's address: tell our API (with the device secret).
        scope.launch { runCatching { Account.sync(applicationContext, token) } }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val title = message.notification?.title ?: message.data["title"] ?: return
        val body = message.notification?.body ?: message.data["body"].orEmpty()
        Notifications.showDigest(this, title, body, message.data["slug"])
    }

    private companion object {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    }
}
