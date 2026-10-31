package com.ipoanalyser.gmp.ui.detail

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ipoanalyser.gmp.data.GmpApi
import com.ipoanalyser.gmp.data.GmpPointDto
import com.ipoanalyser.gmp.data.IpoDetailDto
import com.ipoanalyser.gmp.push.Account
import com.ipoanalyser.gmp.ui.DISCLAIMER_SOURCE
import com.ipoanalyser.gmp.ui.GCard
import com.ipoanalyser.gmp.ui.LoadingBox
import com.ipoanalyser.gmp.ui.MessageBox
import com.ipoanalyser.gmp.ui.Muted
import com.ipoanalyser.gmp.ui.SectionTitle
import com.ipoanalyser.gmp.ui.chart.GmpChartColors
import com.ipoanalyser.gmp.ui.chart.GmpChartPoint
import com.ipoanalyser.gmp.ui.chart.GmpChartSection
import com.ipoanalyser.gmp.ui.dayMonth
import com.ipoanalyser.gmp.ui.formatRupees
import com.ipoanalyser.gmp.ui.toLocalDateOrNull
import kotlinx.coroutines.launch

@Composable
fun DetailScreen(slug: String, onTitle: (String) -> Unit) {
    val context = LocalContext.current
    var ipo by remember(slug) { mutableStateOf<IpoDetailDto?>(null) }
    var error by remember(slug) { mutableStateOf<String?>(null) }
    var attempt by remember(slug) { mutableIntStateOf(0) }
    LaunchedEffect(slug, attempt) {
        error = null
        runCatching { GmpApi.ipo(slug, fresh = attempt > 0) }
            .onSuccess { ipo = it; onTitle(it.name) }
            .onFailure { error = "Couldn't load this IPO. The server may be waking up (~30 s)." }
    }
    val i = ipo
    when {
        i == null && error != null -> MessageBox(error!!) { attempt++ }
        i == null -> LoadingBox()
        else -> DetailContent(i, context)
    }
}

@Composable
private fun DetailContent(i: IpoDetailDto, context: Context) {
    val density = LocalDensity.current
    var showAbout by remember(i.slug) { mutableStateOf(true) }
    var aboutOpen by remember(i.slug) { mutableStateOf(false) }
    var aboutHeightPx by remember(i.slug) { mutableIntStateOf(0) }
    val summary = i.aboutSummary

    Box(Modifier.fillMaxSize()) {
        // Leave exactly the floating card's height (+ a gap) free at the end, whatever the font size.
        val reserved = if (showAbout && summary != null) with(density) { aboutHeightPx.toDp() } + 16.dp else 0.dp
        Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp).padding(bottom = reserved)) {
            val points = i.gmpHistory.mapNotNull { p ->
                val d = p.date.toLocalDateOrNull()
                if (d == null || p.gmp == null) null else GmpChartPoint(d, p.gmp, p.trend, p.lastUpdated)
            }
            GmpChartSection(
                points = points,
                subtitle = listOfNotNull(
                    if (i.category == "sme") "SME" else "Mainboard", "GMP",
                    i.listingDate.toLocalDateOrNull()?.let { "Lists ${it.dayMonth()}" } ?: "Listing date TBA",
                ).joinToString(" · "),
            )
            if (i.status != "listed") TrackButton(i.slug)
            i.buyLinks?.let { links ->
                Spacer(Modifier.height(12.dp))
                GCard {
                    SectionTitle("Apply for this IPO")
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.padding(top = 8.dp)) {
                        Button(onClick = { openLink(context, links.groww) }, modifier = Modifier.weight(1f)) { Text("Groww") }
                        OutlinedButton(onClick = { openLink(context, links.zerodha) }, modifier = Modifier.weight(1f)) { Text("Zerodha Kite") }
                    }
                    Muted(
                        "Opens the app if it's installed, otherwise the website. " +
                            (if (links.growwExact) "Groww opens this IPO directly." else "Groww opens its IPO list.") +
                            " Kite opens its IPO section; pick ${i.name} there.",
                        Modifier.padding(top = 8.dp),
                    )
                }
            }
            Spacer(Modifier.height(10.dp))
            GCard {
                SectionTitle("IPO details", Modifier.padding(bottom = 4.dp))
                Detail("Price band", "${formatRupees(i.priceBandMin)} – ${formatRupees(i.priceBandMax)}")
                Detail("Est. listing price", formatRupees(i.estimatedListingPrice))
                Detail("Lot size", i.lotSize?.let { "$it shares" } ?: "—")
                Detail("Min. investment", if (i.lotSize != null && i.priceBandMax != null) formatRupees(i.lotSize * i.priceBandMax) else "—")
                Detail("Open", i.openDate.toLocalDateOrNull()?.dayMonth() ?: "—")
                Detail("Close", i.closeDate.toLocalDateOrNull()?.dayMonth() ?: "—")
                Detail("Listing", i.listingDate.toLocalDateOrNull()?.dayMonth() ?: "—", last = true)
            }
            Spacer(Modifier.height(10.dp))
            DayWiseTable(i.gmpHistory)
            if (i.gmpHistory.any { it.source != "ipowatch" }) {
                Muted(
                    "* GMP from investorgain.com on days ipowatch.in had none. The two sites often quote different figures.",
                    Modifier.fillMaxWidth().padding(top = 12.dp), align = TextAlign.Center,
                )
            }
            Muted(DISCLAIMER_SOURCE, Modifier.fillMaxWidth().padding(top = 12.dp), align = TextAlign.Center)
        }

        // "About the company" card floating at the bottom, like the web preview.
        if (showAbout && summary != null) {
            ElevatedCard(
                modifier = Modifier.align(Alignment.BottomCenter).padding(12.dp).fillMaxWidth().onSizeChanged { aboutHeightPx = it.height },
                elevation = CardDefaults.elevatedCardElevation(defaultElevation = 8.dp),
                colors = CardDefaults.elevatedCardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
            ) {
                Row(Modifier.padding(start = 16.dp, top = 12.dp, bottom = 12.dp, end = 4.dp)) {
                    Column(Modifier.weight(1f)) {
                        Muted("About ${i.name}")
                        Text(
                            if (aboutOpen) i.about ?: summary else summary,
                            maxLines = if (aboutOpen) 16 else 3, overflow = TextOverflow.Ellipsis, fontSize = 14.sp,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        if ((i.about?.length ?: 0) > summary.length) {
                            Text(
                                if (aboutOpen) "Show less" else "Read more", color = MaterialTheme.colorScheme.primary, fontSize = 13.sp,
                                fontWeight = FontWeight.Medium,
                                modifier = Modifier.padding(top = 4.dp).clickable { aboutOpen = !aboutOpen },
                            )
                        }
                    }
                    TextButton(onClick = { showAbout = false }) { Text("✕") }
                }
            }
        }
    }
}

@Composable
private fun TrackButton(slug: String) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var tracked by remember(slug) { mutableStateOf(false) }
    var busy by remember(slug) { mutableStateOf(false) }
    var message by remember(slug) { mutableStateOf<String?>(null) }
    LaunchedEffect(slug) {
        runCatching { Account.trackedSlugs(context) }.onSuccess { tracked = slug in it }
    }
    val toggle: () -> Unit = {
        busy = true
        message = null
        scope.launch {
            runCatching { Account.setTracked(context, slug, !tracked) }
                .onSuccess {
                    tracked = !tracked
                    message = if (tracked) "You'll get its GMP in the 10 AM digest." else null
                }
                .onFailure { message = "Couldn't update tracking. Check your connection and try again." }
            busy = false
        }
    }
    Spacer(Modifier.height(12.dp))
    if (tracked) {
        OutlinedButton(onClick = toggle, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Text("✓ Tracking · tap to stop") }
    } else {
        Button(onClick = toggle, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Text("🔔 Track · daily 10 AM GMP alert") }
    }
    message?.let { Muted(it, Modifier.padding(top = 4.dp)) }
}

@Composable
private fun Detail(label: String, value: String, last: Boolean = false) {
    Row(Modifier.fillMaxWidth().padding(vertical = 7.dp)) {
        Text(label, Modifier.weight(1f), color = MaterialTheme.colorScheme.onSurface, fontSize = 14.sp)
        Text(value, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurface, fontSize = 14.sp)
    }
    if (!last) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
}

/** Newest first; "*" marks days filled from the backup source. */
@Composable
private fun DayWiseTable(history: List<GmpPointDto>) {
    GCard {
        SectionTitle("Day-wise GMP", Modifier.padding(bottom = 6.dp))
        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
            Muted("Date", Modifier.weight(1.3f))
            Muted("GMP", Modifier.weight(1f), align = TextAlign.End)
            Muted("Trend", Modifier.weight(0.8f), align = TextAlign.End)
            Muted("Gain", Modifier.weight(1f), align = TextAlign.End)
        }
        history.reversed().forEach { p ->
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Row(Modifier.fillMaxWidth().padding(vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
                val date = p.date.toLocalDateOrNull()?.dayMonth() ?: p.date
                Text(
                    date + if (p.source != "ipowatch") " *" else "",
                    Modifier.weight(1.3f), fontSize = 14.sp, color = MaterialTheme.colorScheme.onSurface,
                )
                Text(formatRupees(p.gmp), Modifier.weight(1f), textAlign = TextAlign.End, fontSize = 14.sp, color = MaterialTheme.colorScheme.onSurface)
                val (arrow, color) = when (p.trend) {
                    "up" -> "▲" to GmpChartColors.Up
                    "down" -> "▼" to GmpChartColors.Down
                    "flat" -> "▶" to GmpChartColors.Flat
                    else -> "–" to GmpChartColors.Flat
                }
                Text(arrow, Modifier.weight(0.8f), textAlign = TextAlign.End, color = color, fontSize = 14.sp)
                Text(p.gainPct?.let { "$it%" } ?: "—", Modifier.weight(1f), textAlign = TextAlign.End, fontSize = 14.sp, color = MaterialTheme.colorScheme.onSurface)
            }
        }
    }
}

/** Opens Groww/Kite: Android hands https links to the broker's app when it's installed. */
private fun openLink(context: Context, url: String) {
    if (!GmpApi.isSafeBuyLink(url)) return
    try {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE))
    } catch (_: ActivityNotFoundException) {
        // No app or browser can open it.
    }
}
