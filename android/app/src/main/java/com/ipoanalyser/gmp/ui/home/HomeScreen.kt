package com.ipoanalyser.gmp.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ipoanalyser.gmp.data.DashboardDto
import com.ipoanalyser.gmp.data.DashboardItemDto
import com.ipoanalyser.gmp.data.GmpApi
import com.ipoanalyser.gmp.ui.DISCLAIMER_SOURCE
import com.ipoanalyser.gmp.ui.GCard
import com.ipoanalyser.gmp.ui.LoadingBox
import com.ipoanalyser.gmp.ui.MessageBox
import com.ipoanalyser.gmp.ui.Muted
import com.ipoanalyser.gmp.ui.SectionTitle
import com.ipoanalyser.gmp.ui.Sparkline
import com.ipoanalyser.gmp.ui.Stat
import com.ipoanalyser.gmp.ui.chart.GmpChartColors
import com.ipoanalyser.gmp.ui.closingText
import com.ipoanalyser.gmp.ui.dayMonth
import com.ipoanalyser.gmp.ui.formatRupees
import com.ipoanalyser.gmp.ui.formatRupeesShort
import com.ipoanalyser.gmp.ui.formatSignedPct
import com.ipoanalyser.gmp.ui.toLocalDateOrNull
import kotlin.math.abs

private enum class SortKey(val label: String) { Gain("Gain %"), Profit("Profit / lot") }

private fun DashboardItemDto.value(key: SortKey): Double? = when (key) {
    SortKey.Gain -> estGainPct
    SortKey.Profit -> profitPerLot
}

private fun SortKey.format(v: Double?): String = when (this) {
    SortKey.Gain -> formatSignedPct(v)
    SortKey.Profit -> formatRupeesShort(v)
}

/** IPOs with no GMP yet always sit at the bottom, whichever way we sort. */
private fun List<DashboardItemDto>.ranked(key: SortKey, desc: Boolean): List<DashboardItemDto> {
    val byValue = compareBy<DashboardItemDto> { it.value(key) }
    return sortedWith(compareBy<DashboardItemDto> { it.value(key) == null }.then(if (desc) byValue.reversed() else byValue))
}

private fun gainColor(v: Double?): Color = when {
    v == null || v == 0.0 -> GmpChartColors.Flat
    v > 0 -> GmpChartColors.Up
    else -> GmpChartColors.Down
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(onOpen: (String) -> Unit) {
    var data by remember { mutableStateOf<DashboardDto?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    var reload by remember { mutableIntStateOf(0) }
    var sortKey by rememberSaveable { mutableStateOf(SortKey.Gain) }
    var desc by rememberSaveable { mutableStateOf(true) }

    LaunchedEffect(reload) {
        runCatching { GmpApi.dashboard(fresh = reload > 0) }
            .onSuccess { data = it; error = null }
            .onFailure { if (data == null) error = "Couldn't load. The server may be waking up (~30 s)." }
        refreshing = false
    }

    PullToRefreshBox(isRefreshing = refreshing, onRefresh = { refreshing = true; reload++ }, modifier = Modifier.fillMaxSize()) {
        val d = data
        when {
            d == null && error != null -> MessageBox(error!!) { reload++ }
            d == null -> LoadingBox()
            else -> {
                val open = d.open.ranked(sortKey, desc)
                val awaiting = d.awaitingListing.ranked(sortKey, desc)
                LazyColumn(
                    contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 32.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    item {
                        Column {
                            Muted("Open for bidding · as of ${d.asOf.toLocalDateOrNull()?.dayMonth() ?: d.asOf}", size = 13)
                            Text("Ranked by grey-market gain", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
                        }
                    }
                    item { SortControls(sortKey, desc, onSort = { sortKey = it }, onFlip = { desc = !desc }) }
                    if (open.isEmpty()) {
                        item { GCard { Muted("No IPOs are open for bidding today.", size = 14) } }
                    } else {
                        item { BarChart(open, sortKey, onOpen) }
                        itemsIndexed(open, key = { _, it -> it.slug }) { i, item -> DashCard(i + 1, item) { onOpen(item.slug) } }
                    }
                    if (awaiting.isNotEmpty()) {
                        item { SectionTitle("Closed · awaiting listing", Modifier.padding(top = 12.dp)) }
                        itemsIndexed(awaiting, key = { _, it -> "a-" + it.slug }) { i, item -> DashCard(i + 1, item) { onOpen(item.slug) } }
                    }
                    item {
                        Text(
                            d.disclaimer, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(10.dp)).padding(12.dp),
                        )
                    }
                    item { Muted(DISCLAIMER_SOURCE, Modifier.fillMaxWidth(), align = TextAlign.Center) }
                }
            }
        }
    }
}

@Composable
private fun SortControls(key: SortKey, desc: Boolean, onSort: (SortKey) -> Unit, onFlip: () -> Unit) {
    val colors = MaterialTheme.colorScheme
    val pill = RoundedCornerShape(50)
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Row(Modifier.border(1.dp, colors.outlineVariant, pill).padding(3.dp)) {
            SortKey.entries.forEach { k ->
                val selected = k == key
                Text(
                    k.label, fontSize = 13.sp, fontWeight = FontWeight.Medium,
                    color = if (selected) colors.onSurface else colors.onSurfaceVariant,
                    modifier = Modifier.clip(pill).background(if (selected) colors.surfaceVariant else Color.Transparent)
                        .clickable { onSort(k) }.padding(horizontal = 12.dp, vertical = 6.dp),
                )
            }
        }
        Spacer(Modifier.weight(1f))
        Text(
            if (desc) "High → Low" else "Low → High", fontSize = 13.sp, fontWeight = FontWeight.Medium, color = colors.onSurface,
            modifier = Modifier.clip(pill).border(1.dp, colors.outlineVariant, pill).clickable(onClick = onFlip)
                .padding(horizontal = 12.dp, vertical = 7.dp),
        )
    }
}

/** Comparison bars, one per open IPO, in the current sort order. */
@Composable
private fun BarChart(items: List<DashboardItemDto>, key: SortKey, onOpen: (String) -> Unit) {
    val colors = MaterialTheme.colorScheme
    val max = items.maxOf { abs(it.value(key) ?: 0.0) }.coerceAtLeast(1.0)
    GCard {
        items.forEachIndexed { i, item ->
            val v = item.value(key)
            val color = gainColor(v)
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().clickable { onOpen(item.slug) }.padding(vertical = 8.dp),
            ) {
                Muted("${i + 1}", Modifier.width(18.dp))
                Text(item.name, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, color = colors.onSurface, modifier = Modifier.weight(0.45f))
                Box(
                    Modifier.weight(0.33f).padding(horizontal = 8.dp).height(10.dp).clip(RoundedCornerShape(50)).background(colors.surfaceVariant),
                ) {
                    if (v != null) {
                        Box(Modifier.fillMaxHeight().fillMaxWidth((abs(v) / max).toFloat().coerceIn(0.03f, 1f)).clip(RoundedCornerShape(50)).background(color))
                    }
                }
                Text(
                    key.format(v), fontSize = 13.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.End,
                    color = if (v == null) colors.onSurfaceVariant else color, modifier = Modifier.widthIn(min = 64.dp),
                )
            }
            if (i < items.lastIndex) HorizontalDivider(color = colors.outlineVariant)
        }
    }
}

@Composable
private fun DashCard(rank: Int, item: DashboardItemDto, onClick: () -> Unit) {
    val colors = MaterialTheme.colorScheme
    GCard(onClick = onClick) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(26.dp).background(colors.surfaceVariant, CircleShape), contentAlignment = Alignment.Center) {
                Text("$rank", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = colors.onSurface)
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(item.name, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis, color = colors.onSurface)
                Muted(
                    listOfNotNull(if (item.category == "sme") "SME" else "Mainboard", closingText(item.daysToClose, item.listingDate))
                        .joinToString(" · "),
                    size = 13,
                )
            }
            Sparkline(item.gmpSeries.mapNotNull { it.gmp })
        }
        Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Stat("GMP", formatRupees(item.latestGmp?.gmp), Modifier.weight(1f))
            Stat("Est. gain", formatSignedPct(item.estGainPct), Modifier.weight(1f), valueColor = if (item.estGainPct == null) Color.Unspecified else gainColor(item.estGainPct))
            Stat("Profit / lot", formatRupeesShort(item.profitPerLot), Modifier.weight(1f))
            Stat("Min. invest", formatRupeesShort(item.minInvestment), Modifier.weight(1f))
        }
    }
}
