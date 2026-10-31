package com.ipoanalyser.gmp.data

import android.content.Context

/** Small local settings shared by the app and the widget. */
object Settings {
    private const val FILE = "settings"
    private const val KEY_DARK = "dark_theme"

    /** Light by default; dark only when the user turns it on in the app. */
    fun isDark(context: Context): Boolean =
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE).getBoolean(KEY_DARK, false)

    fun setDark(context: Context, dark: Boolean) {
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().putBoolean(KEY_DARK, dark).apply()
    }
}

/** Last dashboard response, so the widget can draw instantly and offline. */
object WidgetCache {
    private const val FILE = "widget_cache"
    private const val KEY_JSON = "dashboard_json"
    private const val KEY_AT = "fetched_at"

    fun save(context: Context, json: String) {
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit()
            .putString(KEY_JSON, json)
            .putLong(KEY_AT, System.currentTimeMillis())
            .apply()
    }

    fun load(context: Context): Pair<DashboardDto, Long>? {
        val prefs = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)
        val json = prefs.getString(KEY_JSON, null) ?: return null
        val dashboard = runCatching { GmpApi.parseDashboard(json) }.getOrNull() ?: return null
        return dashboard to prefs.getLong(KEY_AT, 0L)
    }
}
