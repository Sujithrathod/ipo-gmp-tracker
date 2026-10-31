package com.ipoanalyser.gmp.ui

import java.text.NumberFormat
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import java.util.Locale
import kotlin.math.abs

private val indianLocale: Locale = Locale.Builder().setLanguage("en").setRegion("IN").build()
private val dayMonth = DateTimeFormatter.ofPattern("d MMM", Locale.ENGLISH)
private val dayMonthYear = DateTimeFormatter.ofPattern("d MMM yyyy", Locale.ENGLISH)

val IST: ZoneId = ZoneId.of("Asia/Kolkata")

fun todayIst(): LocalDate = LocalDate.now(IST)

/** ₹1,94,012 style (Indian digit grouping). */
fun formatRupees(value: Number?): String {
    if (value == null) return "—"
    val nf = NumberFormat.getNumberInstance(indianLocale).apply { maximumFractionDigits = 2 }
    return "₹" + nf.format(value)
}

/** "+40 (133.33%)", "−2 (22.22%)", "0 (0.00%)". */
fun formatChange(change: Int, pct: Double?): String {
    val sign = when {
        change > 0 -> "+"
        change < 0 -> "−"
        else -> ""
    }
    val pctText = pct?.let { " (" + String.format(Locale.ENGLISH, "%.2f", abs(it)) + "%)" } ?: ""
    return "$sign${abs(change)}$pctText"
}

fun LocalDate.dayMonth(): String = format(dayMonth)

fun LocalDate.dayMonthYear(): String = format(dayMonthYear)

fun String?.toLocalDateOrNull(): LocalDate? = this?.let { runCatching { LocalDate.parse(it) }.getOrNull() }

/** ₹1.12 L / ₹3.4 Cr for big amounts, full digits below a lakh (Indian convention). */
fun formatRupeesShort(value: Number?): String {
    if (value == null) return "—"
    val v = value.toDouble()
    fun trim(x: Double) = String.format(Locale.ENGLISH, "%.2f", x).trimEnd('0').trimEnd('.')
    return when {
        abs(v) >= 1e7 -> "₹" + trim(v / 1e7) + " Cr"
        abs(v) >= 1e5 -> "₹" + trim(v / 1e5) + " L"
        else -> formatRupees(value)
    }
}

/** "+44.3%", "−2.0%", "0.0%"; "—" when unknown. */
fun formatSignedPct(pct: Double?): String = pct?.let {
    (if (it > 0) "+" else if (it < 0) "−" else "") + String.format(Locale.ENGLISH, "%.1f%%", abs(it))
} ?: "—"

/** "Lists in 3 days" / "Lists tomorrow" / "Lists today" / "Listed 3 Nov" / "Opens 5 Nov". */
fun listingCountdown(listingDate: String?, openDate: String?): String? {
    val listing = listingDate.toLocalDateOrNull()
    if (listing != null) {
        val days = ChronoUnit.DAYS.between(todayIst(), listing)
        return when {
            days > 1 -> "Lists in $days days"
            days == 1L -> "Lists tomorrow"
            days == 0L -> "Lists today"
            else -> "Listed ${listing.dayMonth()}"
        }
    }
    return openDate.toLocalDateOrNull()?.let { "Opens ${it.dayMonth()}" }
}

/** "Closes in 3 days" etc. while bidding is open; afterwards the listing date. */
fun closingText(daysToClose: Int?, listingDate: String?): String? = when {
    daysToClose == null -> null
    daysToClose > 1 -> "Closes in $daysToClose days"
    daysToClose == 1 -> "Closes tomorrow"
    daysToClose == 0 -> "Closes today"
    else -> listingDate.toLocalDateOrNull()?.let { "Lists ${it.dayMonth()}" }
}
