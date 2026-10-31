package com.ipoanalyser.gmp.push

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.ipoanalyser.gmp.MainActivity
import com.ipoanalyser.gmp.R

object Notifications {
    /** Must match CHANNEL_ID in notify/send_digest.py. */
    const val CHANNEL_ID = "gmp_digest"
    private const val DIGEST_ID = 1001

    fun ensureChannel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL_ID) == null) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Daily GMP digest", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "10 AM update for the IPOs you track"
                },
            )
        }
    }

    fun canPost(context: Context): Boolean =
        Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    /**
     * Shows the digest while the app is in the foreground. (In the background,
     * Android draws FCM notification messages itself, and a tap delivers the
     * message's data, including "slug", to MainActivity as intent extras.)
     */
    @SuppressLint("MissingPermission") // checked by canPost()
    fun showDigest(context: Context, title: String, body: String, slug: String?) {
        if (!canPost(context)) return
        ensureChannel(context)
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
            slug?.let { putExtra(MainActivity.EXTRA_SLUG, it) }
        }
        val tap = PendingIntent.getActivity(context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body.lineSequence().firstOrNull() ?: body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setContentIntent(tap)
            .build()
        NotificationManagerCompat.from(context).notify(DIGEST_ID, notification)
    }
}
