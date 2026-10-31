package com.ipoanalyser.gmp.ui.list

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ipoanalyser.gmp.data.GmpApi
import com.ipoanalyser.gmp.data.IpoSummaryDto
import com.ipoanalyser.gmp.ui.ChangeBadge
import com.ipoanalyser.gmp.ui.Chip
import com.ipoanalyser.gmp.ui.DISCLAIMER_SOURCE
import com.ipoanalyser.gmp.ui.GCard
import com.ipoanalyser.gmp.ui.LoadingBox
import com.ipoanalyser.gmp.ui.MessageBox
import com.ipoanalyser.gmp.ui.Muted
import com.ipoanalyser.gmp.ui.formatRupees
import com.ipoanalyser.gmp.ui.listingCountdown
import java.util.Locale

/** Current / Upcoming / Listed tab: one card per IPO, like the web preview. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IpoListScreen(status: String, onOpen: (String) -> Unit) {
    var items by remember(status) { mutableStateOf<List<IpoSummaryDto>?>(null) }
    var error by remember(status) { mutableStateOf<String?>(null) }
    var refreshing by remember(status) { mutableStateOf(false) }
    var reload by remember(status) { mutableIntStateOf(0) }

    LaunchedEffect(status, reload) {
        runCatching { GmpApi.ipos(status, fresh = reload > 0) }
            .onSuccess { items = it; error = null }
            .onFailure { if (items == null) error = "Couldn't load. The server may be waking up (~30 s)." }
        refreshing = false
    }

    PullToRefreshBox(isRefreshing = refreshing, onRefresh = { refreshing = true; reload++ }, modifier = Modifier.fillMaxSize()) {
        val list = items
        when {
            list == null && error != null -> MessageBox(error!!) { reload++ }
            list == null -> LoadingBox()
            list.isEmpty() -> MessageBox("No $status IPOs right now.")
            else -> LazyColumn(
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 32.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
                modifier = Modifier.fillMaxSize(),
            ) {
                items(list, key = { it.slug }) { ipo -> IpoCard(ipo) { onOpen(ipo.slug) } }
                item { Muted(DISCLAIMER_SOURCE, Modifier.fillMaxWidth().padding(top = 8.dp), align = TextAlign.Center) }
            }
        }
    }
}

@Composable
private fun IpoCard(ipo: IpoSummaryDto, onClick: () -> Unit) {
    val colors = MaterialTheme.colorScheme
    val latest = ipo.latestGmp
    GCard(onClick = onClick) {
        Text(ipo.name, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis, color = colors.onSurface)
        Muted(
            listOf(
                if (ipo.category == "sme") "SME" else "Mainboard",
                formatRupees(ipo.priceBandMax),
                "Lot ${ipo.lotSize ?: "—"}",
            ).joinToString(" · "),
            size = 13,
        )
        Row(verticalAlignment = Alignment.Bottom, modifier = Modifier.fillMaxWidth().padding(top = 10.dp)) {
            Column(Modifier.weight(1f)) {
                Muted("GMP")
                Text(formatRupees(latest?.gmp), fontSize = 24.sp, fontWeight = FontWeight.Bold, color = colors.onSurface)
            }
            ChangeBadge(latest)
            Spacer(Modifier.width(12.dp))
            Column(horizontalAlignment = Alignment.End) {
                Muted("Est. gain")
                Text(
                    latest?.gainPct?.let { String.format(Locale.ENGLISH, "%.2f%%", it) } ?: "—",
                    fontSize = 15.sp, color = colors.onSurface,
                )
            }
        }
        listingCountdown(ipo.listingDate, ipo.openDate)?.let { Chip(it, Modifier.padding(top = 8.dp)) }
    }
}
