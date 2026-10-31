package com.ipoanalyser.gmp.widget

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.LocalSize
import androidx.glance.action.ActionParameters
import androidx.glance.action.actionParametersOf
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.SizeMode
import androidx.glance.appwidget.action.ActionCallback
import androidx.glance.appwidget.action.actionRunCallback
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.provideContent
import androidx.glance.background
import androidx.glance.layout.Alignment
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.layout.width
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import androidx.glance.unit.ColorProvider
import com.ipoanalyser.gmp.MainActivity
import com.ipoanalyser.gmp.data.DashboardItemDto
import com.ipoanalyser.gmp.data.Settings
import com.ipoanalyser.gmp.data.WidgetCache
import com.ipoanalyser.gmp.ui.formatRupees
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs

/** Intent extra / action parameter carrying the IPO to open. */
val SlugKey = ActionParameters.Key<String>(MainActivity.EXTRA_SLUG)

private data class WidgetColors(val bg: Color, val text: Color, val muted: Color, val up: Color, val down: Color)

private val Light = WidgetColors(Color(0xFFFFFFFF), Color(0xFF2B2D3A), Color(0xFF7C7E8C), Color(0xFF00B386), Color(0xFFEB5B3C))
private val Dark = WidgetColors(Color(0xFF1D1D21), Color(0xFFF2F2F5), Color(0xFF8E8E98), Color(0xFF00C896), Color(0xFFFF6B4A))

/**
 * Home-screen widget: open IPOs ranked by GMP-implied listing gain.
 * Data comes from the cached /dashboard response that WidgetRefreshWorker keeps fresh.
 */
class GmpWidget : GlanceAppWidget() {

    override val sizeMode = SizeMode.Responsive(setOf(SMALL, LARGE))

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val cached = WidgetCache.load(context)
        val colors = if (Settings.isDark(context)) Dark else Light
        provideContent { Content(cached?.first?.open.orEmpty(), cached?.second, colors) }
    }

    @Composable
    private fun Content(items: List<DashboardItemDto>, fetchedAt: Long?, c: WidgetColors) {
        val rows = if (LocalSize.current.height >= LARGE.height) 5 else 3
        Column(
            modifier = GlanceModifier.fillMaxSize().background(c.bg).cornerRadius(20.dp).padding(14.dp)
                .clickable(actionStartActivity<MainActivity>()),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = GlanceModifier.fillMaxWidth()) {
                Column(modifier = GlanceModifier.defaultWeight()) {
                    Text("Open IPOs by GMP", style = TextStyle(color = ColorProvider(c.text), fontSize = 15.sp, fontWeight = FontWeight.Bold))
                    Text(
                        fetchedAt?.let { "Updated " + SimpleDateFormat("d MMM, h:mm a", Locale.ENGLISH).format(Date(it)) } ?: "Not loaded yet",
                        style = TextStyle(color = ColorProvider(c.muted), fontSize = 11.sp),
                    )
                }
                Text(
                    "↻",
                    style = TextStyle(color = ColorProvider(c.text), fontSize = 20.sp),
                    modifier = GlanceModifier.padding(horizontal = 6.dp).clickable(actionRunCallback<RefreshAction>()),
                )
            }
            Spacer(GlanceModifier.height(8.dp))
            when {
                fetchedAt == null -> Text("Tap ↻ to load", style = TextStyle(color = ColorProvider(c.muted), fontSize = 13.sp))
                items.isEmpty() -> Text("No IPOs open for bidding today", style = TextStyle(color = ColorProvider(c.muted), fontSize = 13.sp))
                else -> items.take(rows).forEach { IpoRow(it, c) }
            }
            Spacer(GlanceModifier.defaultWeight())
            Text("Unofficial GMP · not advice", style = TextStyle(color = ColorProvider(c.muted), fontSize = 10.sp))
        }
    }

    @Composable
    private fun IpoRow(item: DashboardItemDto, c: WidgetColors) {
        val gain = item.estGainPct
        val gainColor = when {
            gain == null || gain == 0.0 -> c.muted
            gain > 0 -> c.up
            else -> c.down
        }
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = GlanceModifier.fillMaxWidth().padding(vertical = 4.dp)
                .clickable(actionStartActivity<MainActivity>(actionParametersOf(SlugKey to item.slug))),
        ) {
            Text("${item.rank}", style = TextStyle(color = ColorProvider(c.muted), fontSize = 12.sp), modifier = GlanceModifier.width(18.dp))
            Text(
                item.name,
                maxLines = 1,
                style = TextStyle(color = ColorProvider(c.text), fontSize = 13.sp, fontWeight = FontWeight.Medium),
                modifier = GlanceModifier.defaultWeight(),
            )
            Text(
                formatRupees(item.latestGmp?.gmp),
                style = TextStyle(color = ColorProvider(c.text), fontSize = 13.sp),
                modifier = GlanceModifier.padding(horizontal = 6.dp),
            )
            Text(
                gain?.let { (if (it > 0) "+" else if (it < 0) "−" else "") + String.format(Locale.ENGLISH, "%.1f%%", abs(it)) } ?: "—",
                style = TextStyle(color = ColorProvider(gainColor), fontSize = 13.sp, fontWeight = FontWeight.Bold),
            )
        }
    }

    companion object {
        private val SMALL = DpSize(180.dp, 110.dp)
        private val LARGE = DpSize(250.dp, 200.dp)
    }
}

class GmpWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = GmpWidget()

    override fun onEnabled(context: Context) {
        super.onEnabled(context)
        WidgetRefreshWorker.schedule(context)
        WidgetRefreshWorker.refreshNow(context)
    }

    override fun onDisabled(context: Context) {
        super.onDisabled(context)
        WidgetRefreshWorker.cancel(context)
    }
}

/** The ↻ button. */
class RefreshAction : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        WidgetRefreshWorker.refreshNow(context)
    }
}
