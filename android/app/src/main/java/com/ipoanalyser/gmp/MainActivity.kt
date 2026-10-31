package com.ipoanalyser.gmp

import android.Manifest
import android.content.Intent
import android.graphics.Color as AndroidColor
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabPosition
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.lerp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ipoanalyser.gmp.data.Settings
import com.ipoanalyser.gmp.push.Account
import com.ipoanalyser.gmp.push.Notifications
import com.ipoanalyser.gmp.ui.detail.DetailScreen
import com.ipoanalyser.gmp.ui.home.HomeScreen
import com.ipoanalyser.gmp.ui.list.IpoListScreen
import com.ipoanalyser.gmp.ui.theme.AppTheme
import com.ipoanalyser.gmp.widget.WidgetRefreshWorker
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlin.math.abs

class MainActivity : ComponentActivity() {

    /** IPO to open, from a widget row tap or a notification tap. */
    private val pendingSlug = MutableStateFlow<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        applySystemBars(Settings.isDark(this))
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null) handleIntent(intent)
        setContent { App(pendingSlug, onThemeChanged = ::applySystemBars) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        intent?.getStringExtra(EXTRA_SLUG)?.takeIf { SLUG.matches(it) }?.let { pendingSlug.value = it }
    }

    /** Status/navigation bar icons follow the app's own light/dark toggle, not the phone's setting. */
    private fun applySystemBars(dark: Boolean) {
        val style = if (dark) SystemBarStyle.dark(AndroidColor.TRANSPARENT)
        else SystemBarStyle.light(AndroidColor.TRANSPARENT, AndroidColor.TRANSPARENT)
        enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
    }

    companion object {
        const val EXTRA_SLUG = "slug"
        private val SLUG = Regex("^[a-z0-9][a-z0-9-]{0,119}$")
    }
}

private val TABS = listOf("Home" to null, "Current" to "current", "Upcoming" to "upcoming", "Listed" to "listed")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun App(pendingSlug: MutableStateFlow<String?>, onThemeChanged: (Boolean) -> Unit) {
    val context = LocalContext.current
    var dark by remember { mutableStateOf(Settings.isDark(context)) }
    var openSlug by remember { mutableStateOf<String?>(null) }
    var detailTitle by remember { mutableStateOf<String?>(null) }
    val pager = rememberPagerState(pageCount = { TABS.size })

    val requested by pendingSlug.collectAsStateWithLifecycle()
    LaunchedEffect(requested) {
        requested?.let { openSlug = it; detailTitle = null; pendingSlug.value = null }
    }

    // Push: ask for permission once (Android 13+), then register this phone with the API.
    val askPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    LaunchedEffect(Unit) {
        Notifications.ensureChannel(context)
        if (!Notifications.canPost(context)) askPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        runCatching { Account.sync(context) } // offline / server asleep: retried on next launch
    }

    AppTheme(dark) {
        val colors = MaterialTheme.colorScheme
        Scaffold(
            containerColor = colors.background,
            topBar = {
                TopAppBar(
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = colors.background),
                    title = {
                        Text(
                            if (openSlug == null) "IPO GMP Tracker" else detailTitle ?: "",
                            fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        )
                    },
                    navigationIcon = {
                        if (openSlug != null) TextButton(onClick = { openSlug = null }) { Text("←", fontSize = 22.sp, color = colors.onSurface) }
                    },
                    actions = {
                        TextButton(onClick = {
                            dark = !dark
                            Settings.setDark(context, dark)
                            onThemeChanged(dark)
                            WidgetRefreshWorker.refreshNow(context) // widget follows the app's theme
                        }) { Text(if (dark) "☀" else "☾", fontSize = 20.sp, color = colors.onSurface) }
                    },
                )
            },
        ) { padding ->
            Box(Modifier.padding(padding).fillMaxSize()) {
                val slug = openSlug
                if (slug == null) {
                    Tabs(pager, onOpen = { openSlug = it; detailTitle = null })
                } else {
                    BackHandler { openSlug = null }
                    DetailScreen(slug, onTitle = { detailTitle = it })
                }
            }
        }
    }
}

/** Home · Current · Upcoming · Listed: tap a tab or swipe; the underline follows your finger. */
@Composable
private fun Tabs(pager: PagerState, onOpen: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    val colors = MaterialTheme.colorScheme
    Column(Modifier.fillMaxSize()) {
        TabRow(
            selectedTabIndex = pager.currentPage,
            containerColor = colors.background,
            indicator = { positions -> SlidingIndicator(positions, pager) },
            divider = { HorizontalDivider(color = colors.outlineVariant) },
        ) {
            TABS.forEachIndexed { index, (label, _) ->
                val selected = pager.currentPage == index
                Tab(
                    selected = selected,
                    onClick = { scope.launch { pager.animateScrollToPage(index) } },
                    selectedContentColor = colors.primary,
                    unselectedContentColor = colors.onSurfaceVariant,
                    text = { Text(label, fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal, fontSize = 15.sp) },
                )
            }
        }
        // Neighbouring tabs stay composed, so swiping back and forth is instant.
        HorizontalPager(state = pager, beyondViewportPageCount = 1, modifier = Modifier.fillMaxSize()) { page ->
            val status = TABS[page].second
            if (status == null) HomeScreen(onOpen) else IpoListScreen(status, onOpen)
        }
    }
}

@Composable
private fun SlidingIndicator(positions: List<TabPosition>, pager: PagerState) {
    val page = pager.currentPage.coerceIn(0, positions.lastIndex)
    val fraction = pager.currentPageOffsetFraction
    val target = (page + if (fraction > 0) 1 else -1).coerceIn(0, positions.lastIndex)
    val from = positions[page]
    val to = positions[target]
    val f = abs(fraction)
    Box(
        Modifier.fillMaxWidth()
            .wrapContentSize(Alignment.BottomStart)
            .offset(x = lerp(from.left, to.left, f))
            .width(lerp(from.width, to.width, f))
            .height(2.dp)
            .background(MaterialTheme.colorScheme.primary, RoundedCornerShape(2.dp)),
    )
}
