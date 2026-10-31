package com.ipoanalyser.gmp.data

import android.net.Uri
import com.ipoanalyser.gmp.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

@Serializable
data class GmpPointDto(
    val date: String,
    val gmp: Int? = null,
    val trend: String? = null,
    @SerialName("gain_pct") val gainPct: Double? = null,
    @SerialName("last_updated") val lastUpdated: String? = null,
    val source: String = "ipowatch",
)

@Serializable
data class LatestGmpDto(
    val date: String,
    val gmp: Int? = null,
    val trend: String? = null,
    @SerialName("gain_pct") val gainPct: Double? = null,
    val change: Int? = null,
    @SerialName("change_pct") val changePct: Double? = null,
)

@Serializable
data class BuyLinksDto(
    val groww: String,
    @SerialName("groww_exact") val growwExact: Boolean = false,
    val zerodha: String,
)

@Serializable
data class DashboardItemDto(
    val rank: Int,
    val name: String,
    val slug: String,
    val category: String? = null,
    @SerialName("latest_gmp") val latestGmp: LatestGmpDto? = null,
    @SerialName("est_gain_pct") val estGainPct: Double? = null,
    @SerialName("profit_per_lot") val profitPerLot: Double? = null,
    @SerialName("min_investment") val minInvestment: Double? = null,
    @SerialName("days_to_close") val daysToClose: Int? = null,
    @SerialName("listing_date") val listingDate: String? = null,
    @SerialName("gmp_series") val gmpSeries: List<GmpPointDto> = emptyList(),
)

/** A card on the Current / Upcoming / Listed tabs (GET /ipos?status=...). */
@Serializable
data class IpoSummaryDto(
    val name: String,
    val slug: String,
    val category: String? = null,
    val status: String,
    @SerialName("price_band_max") val priceBandMax: Double? = null,
    @SerialName("lot_size") val lotSize: Int? = null,
    @SerialName("open_date") val openDate: String? = null,
    @SerialName("close_date") val closeDate: String? = null,
    @SerialName("listing_date") val listingDate: String? = null,
    @SerialName("latest_gmp") val latestGmp: LatestGmpDto? = null,
    @SerialName("estimated_listing_price") val estimatedListingPrice: Double? = null,
)

@Serializable
data class DashboardDto(
    @SerialName("as_of") val asOf: String,
    val open: List<DashboardItemDto> = emptyList(),
    @SerialName("awaiting_listing") val awaitingListing: List<DashboardItemDto> = emptyList(),
    val disclaimer: String = "",
)

@Serializable
data class IpoDetailDto(
    val name: String,
    val slug: String,
    val category: String? = null,
    val status: String,
    @SerialName("price_band_min") val priceBandMin: Double? = null,
    @SerialName("price_band_max") val priceBandMax: Double? = null,
    @SerialName("open_date") val openDate: String? = null,
    @SerialName("close_date") val closeDate: String? = null,
    @SerialName("listing_date") val listingDate: String? = null,
    @SerialName("lot_size") val lotSize: Int? = null,
    @SerialName("estimated_listing_price") val estimatedListingPrice: Double? = null,
    @SerialName("latest_gmp") val latestGmp: LatestGmpDto? = null,
    @SerialName("buy_links") val buyLinks: BuyLinksDto? = null,
    val about: String? = null,
    @SerialName("about_summary") val aboutSummary: String? = null,
    @SerialName("gmp_history") val gmpHistory: List<GmpPointDto> = emptyList(),
)

@Serializable
data class RegisterOut(
    @SerialName("user_id") val userId: String,
    @SerialName("user_secret") val userSecret: String,
)

@Serializable
data class TrackedOut(val slugs: List<String> = emptyList())

@Serializable
private data class FcmTokenIn(@SerialName("fcm_token") val fcmToken: String)

/** HTTP error with its status code, so callers can react to 401 (lost/unknown device). */
class ApiException(val code: Int) : IOException("Server returned $code")

/** Client for the IPO API: public read-only endpoints, plus the per-device account calls. */
object GmpApi {
    val json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
        explicitNulls = false
    }

    // Generous read timeout: Render's free tier takes ~30-50 s to wake up.
    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    private val slugPattern = Regex("^[a-z0-9][a-z0-9-]{0,119}$")

    suspend fun dashboardJson(fresh: Boolean = false): String = get("dashboard", fresh)

    fun parseDashboard(body: String): DashboardDto = json.decodeFromString(DashboardDto.serializer(), body)

    suspend fun dashboard(fresh: Boolean = false): DashboardDto = parseDashboard(dashboardJson(fresh))

    suspend fun ipos(status: String, fresh: Boolean = false): List<IpoSummaryDto> {
        require(status in setOf("current", "upcoming", "listed")) { "Bad status" }
        return json.decodeFromString(ListSerializer(IpoSummaryDto.serializer()), get("ipos?status=$status", fresh))
    }

    suspend fun ipo(slug: String, fresh: Boolean = false): IpoDetailDto {
        require(slugPattern.matches(slug)) { "Bad IPO id" }
        return json.decodeFromString(IpoDetailDto.serializer(), get("ipos/$slug", fresh))
    }

    // ---- Device account (see backend/main.py "Users"): the secret proves it's this phone.

    suspend fun register(fcmToken: String): RegisterOut =
        json.decodeFromString(RegisterOut.serializer(), send("POST", "users/register-token", tokenBody(fcmToken)))

    suspend fun updateToken(userId: String, secret: String, fcmToken: String) {
        send("PUT", "users/$userId/token", tokenBody(fcmToken), secret)
    }

    suspend fun tracked(userId: String, secret: String): Set<String> =
        json.decodeFromString(TrackedOut.serializer(), send("GET", "users/$userId/tracked", secret = secret)).slugs.toSet()

    suspend fun setTracked(userId: String, secret: String, slug: String, track: Boolean) {
        require(slugPattern.matches(slug)) { "Bad IPO id" }
        send(if (track) "POST" else "DELETE", "users/$userId/track/$slug", if (track) "" else null, secret)
    }

    private fun tokenBody(fcmToken: String) = json.encodeToString(FcmTokenIn.serializer(), FcmTokenIn(fcmToken))

    // Data changes once a day: keep GET responses for 5 minutes so switching tabs is instant.
    // Pull-to-refresh passes fresh = true.
    private val cache = ConcurrentHashMap<String, Pair<Long, String>>()
    private const val CACHE_MS = 5 * 60_000L

    private suspend fun get(path: String, fresh: Boolean = false): String {
        val now = System.currentTimeMillis()
        if (!fresh) cache[path]?.let { (at, body) -> if (now - at < CACHE_MS) return body }
        return send("GET", path).also { cache[path] = now to it }
    }

    private suspend fun send(method: String, path: String, body: String? = null, secret: String? = null): String =
        withContext(Dispatchers.IO) {
            val builder = Request.Builder()
                .url(BuildConfig.API_BASE_URL + path)
                .header("Accept", "application/json")
                .method(method, body?.toRequestBody(JSON))
            if (secret != null) builder.header("Authorization", "Bearer $secret")
            client.newCall(builder.build()).execute().use { response ->
                if (!response.isSuccessful) throw ApiException(response.code)
                val responseBody = response.body ?: return@use ""
                if (responseBody.contentLength() > MAX_BODY_BYTES) throw IOException("Response too large")
                responseBody.string()
            }
        }

    private val JSON = "application/json".toMediaType()

    private const val MAX_BODY_BYTES = 2L * 1024 * 1024

    /** Only ever open broker links on these hosts (the API builds them, but don't trust blindly). */
    fun isSafeBuyLink(url: String): Boolean {
        val uri = runCatching { Uri.parse(url) }.getOrNull() ?: return false
        return uri.scheme == "https" && uri.host in setOf("groww.in", "kite.zerodha.com")
    }
}
