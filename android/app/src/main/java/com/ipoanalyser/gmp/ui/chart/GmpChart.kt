package com.ipoanalyser.gmp.ui.chart

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.LinearOutSlowInEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ipoanalyser.gmp.ui.dayMonth
import com.ipoanalyser.gmp.ui.formatChange
import com.ipoanalyser.gmp.ui.formatRupees
import java.time.LocalDate
import java.time.temporal.ChronoUnit
import kotlin.math.abs
import kotlin.math.roundToInt

/** One day of GMP data, as plotted (days with no GMP reported are left out). */
data class GmpChartPoint(
    val date: LocalDate,
    val gmp: Int,
    val trend: String? = null, // "up" | "down" | "flat" from ipowatch, if any
    val lastUpdated: String? = null,
)

enum class GmpRange(val label: String, val days: Long?) {
    D3("3D", 3), W1("1W", 7), W2("2W", 14), M1("1M", 30), ALL("All", null),
}

object GmpChartColors {
    val Up = Color(0xFF00B386)
    val Down = Color(0xFFEB5B3C)
    val Flat = Color(0xFF9CA3AF)

    fun forChange(change: Int): Color = when {
        change > 0 -> Up
        change < 0 -> Down
        else -> Flat
    }
}

private val ChartEdge = 6.dp
private val LabelArea = 30.dp

private data class ChartWindow(val points: List<GmpChartPoint>, val base: Int)

/**
 * Points inside the range, plus the reference ("previous close") value: the
 * last GMP before the range starts, or the range's first GMP for "All".
 */
private fun windowFor(all: List<GmpChartPoint>, range: GmpRange): ChartWindow {
    val days = range.days ?: return ChartWindow(all, all.first().gmp)
    val start = all.last().date.minusDays(days - 1)
    val inside = all.filter { !it.date.isBefore(start) }
    val before = all.lastOrNull { it.date.isBefore(start) }
    return ChartWindow(inside, before?.gmp ?: inside.first().gmp)
}

/**
 * Groww-style GMP chart: big value + change header that follows the scrubber,
 * a single line coloured by the change over the selected range, a dashed
 * reference line, and range pills underneath.
 */
@Composable
fun GmpChartSection(
    points: List<GmpChartPoint>,
    subtitle: String,
    modifier: Modifier = Modifier,
) {
    if (points.isEmpty()) {
        Text(
            "No GMP reported yet",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = modifier.padding(vertical = 32.dp),
        )
        return
    }
    val sorted = remember(points) { points.sortedBy { it.date } }
    val span = ChronoUnit.DAYS.between(sorted.first().date, sorted.last().date) + 1
    // Only offer ranges that show less than "All".
    val ranges = remember(span) { GmpRange.entries.filter { it.days == null || it.days < span } }
    var range by rememberSaveable { mutableStateOf(GmpRange.ALL) }
    val activeRange = if (range in ranges) range else GmpRange.ALL
    val window = remember(sorted, activeRange) { windowFor(sorted, activeRange) }
    var selected by remember(window) { mutableStateOf<Int?>(null) }

    val shown = window.points[selected ?: window.points.lastIndex]
    val change = shown.gmp - window.base
    val pct = if (window.base != 0) change * 100.0 / abs(window.base) else null
    val lineColor by animateColorAsState(
        GmpChartColors.forChange(window.points.last().gmp - window.base),
        label = "lineColor",
    )

    Column(modifier) {
        Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Row {
            Text(
                formatRupees(shown.gmp),
                fontSize = 32.sp,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.alignByBaseline(),
            )
            Spacer(Modifier.width(8.dp))
            Text(
                formatChange(change, pct),
                fontSize = 15.sp,
                fontWeight = FontWeight.Medium,
                color = GmpChartColors.forChange(change),
                modifier = Modifier.alignByBaseline(),
            )
            Spacer(Modifier.width(4.dp))
            Text(
                activeRange.label,
                fontSize = 15.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.alignByBaseline(),
            )
        }
        Spacer(Modifier.height(16.dp))
        GmpLineChart(
            points = window.points,
            base = window.base,
            lineColor = lineColor,
            selected = selected,
            onSelect = { selected = it },
            modifier = Modifier.fillMaxWidth().height(230.dp),
        )
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Row(
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            modifier = Modifier.padding(top = 12.dp).horizontalScroll(rememberScrollState()),
        ) {
            ranges.forEach { r -> RangePill(r.label, r == activeRange) { range = r } }
        }
    }
}

@Composable
private fun RangePill(label: String, selected: Boolean, onClick: () -> Unit) {
    val colors = MaterialTheme.colorScheme
    OutlinedButton(
        onClick = onClick,
        shape = RoundedCornerShape(50),
        border = BorderStroke(1.dp, if (selected) colors.onSurface else colors.outlineVariant),
        colors = ButtonDefaults.outlinedButtonColors(
            containerColor = if (selected) colors.surfaceVariant else Color.Transparent,
            contentColor = colors.onSurface,
        ),
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 6.dp),
    ) {
        Text(label, fontWeight = FontWeight.Medium)
    }
}

/** Day direction: ipowatch's trend dot if present, else compare with the previous point. */
private fun dayDirection(points: List<GmpChartPoint>, i: Int): String? =
    points[i].trend ?: points.getOrNull(i - 1)?.let { prev ->
        when {
            points[i].gmp > prev.gmp -> "up"
            points[i].gmp < prev.gmp -> "down"
            else -> "flat"
        }
    }

@Composable
fun GmpLineChart(
    points: List<GmpChartPoint>,
    base: Int,
    lineColor: Color,
    selected: Int?,
    onSelect: (Int?) -> Unit,
    modifier: Modifier = Modifier,
) {
    val textMeasurer = rememberTextMeasurer()
    val haptics = LocalHapticFeedback.current
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    val strong = MaterialTheme.colorScheme.onSurface
    val labelStyle = MaterialTheme.typography.labelMedium
    val currentSelected by rememberUpdatedState(selected)
    val currentOnSelect by rememberUpdatedState(onSelect)
    val dragging = remember { mutableStateOf(false) }

    // Pulsing "live" dot on the latest point, like Groww's.
    val pulse = rememberInfiniteTransition(label = "pulse")
    val pulseScale by pulse.animateFloat(
        initialValue = 0.6f, targetValue = 2.2f,
        animationSpec = infiniteRepeatable(tween(1600, easing = LinearOutSlowInEasing)), label = "pulseScale",
    )
    val pulseAlpha by pulse.animateFloat(
        initialValue = 0.45f, targetValue = 0f,
        animationSpec = infiniteRepeatable(tween(1600, easing = LinearOutSlowInEasing)), label = "pulseAlpha",
    )

    fun indexAt(x: Float, width: Float, edge: Float): Int =
        if (points.size < 2) 0
        else (((x - edge) / (width - 2 * edge)) * points.lastIndex).roundToInt().coerceIn(0, points.lastIndex)

    fun select(i: Int?) {
        if (i == currentSelected) return
        if (i != null) haptics.performHapticFeedback(HapticFeedbackType.TextHandleMove)
        currentOnSelect(i)
    }

    Canvas(
        modifier
            .semantics {
                contentDescription = "GMP chart: ${formatRupees(points.first().gmp)} to ${formatRupees(points.last().gmp)}"
            }
            // Press-and-hold shows the value under the finger; release goes back to latest.
            .pointerInput(points) {
                val edge = ChartEdge.toPx()
                detectTapGestures(onPress = { pos ->
                    select(indexAt(pos.x, size.width.toFloat(), edge))
                    tryAwaitRelease()
                    if (!dragging.value) select(null)
                })
            }
            // Horizontal drags scrub; vertical drags still scroll the screen.
            .pointerInput(points) {
                val edge = ChartEdge.toPx()
                detectHorizontalDragGestures(
                    onDragStart = { pos ->
                        dragging.value = true
                        select(indexAt(pos.x, size.width.toFloat(), edge))
                    },
                    onDragEnd = { dragging.value = false; select(null) },
                    onDragCancel = { dragging.value = false; select(null) },
                ) { change, _ ->
                    change.consume()
                    select(indexAt(change.position.x, size.width.toFloat(), edge))
                }
            },
    ) {
        val top = LabelArea.toPx()
        val bottom = 10.dp.toPx()
        val edge = ChartEdge.toPx()
        val values = points.map { it.gmp } + base
        var lo = values.min().toFloat()
        var hi = values.max().toFloat()
        if (lo == hi) { lo -= 1f; hi += 1f }
        val pad = (hi - lo) * 0.08f
        lo -= pad; hi += pad

        fun x(i: Int) = if (points.size == 1) size.width / 2 else edge + i * (size.width - 2 * edge) / points.lastIndex
        fun y(v: Int) = top + (hi - v) * (size.height - top - bottom) / (hi - lo)

        // Dashed reference line at the range's starting GMP.
        drawLine(
            color = muted.copy(alpha = 0.45f),
            start = Offset(0f, y(base)),
            end = Offset(size.width, y(base)),
            strokeWidth = 1.dp.toPx(),
            pathEffect = PathEffect.dashPathEffect(floatArrayOf(5.dp.toPx(), 5.dp.toPx())),
        )

        val path = Path().apply {
            points.forEachIndexed { i, p -> if (i == 0) moveTo(x(i), y(p.gmp)) else lineTo(x(i), y(p.gmp)) }
        }
        drawPath(path, lineColor, style = Stroke(width = 2.5.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))

        val sel = selected
        if (sel == null) {
            val c = Offset(x(points.lastIndex), y(points.last().gmp))
            drawCircle(lineColor.copy(alpha = pulseAlpha), radius = 5.dp.toPx() * pulseScale, center = c)
            drawCircle(lineColor, radius = 4.dp.toPx(), center = c)
        } else {
            val p = points[sel]
            val px = x(sel)
            val c = Offset(px, y(p.gmp))
            drawLine(muted.copy(alpha = 0.5f), Offset(px, top - 6.dp.toPx()), Offset(px, size.height), 1.dp.toPx())
            drawCircle(lineColor.copy(alpha = 0.2f), radius = 8.dp.toPx(), center = c)
            drawCircle(lineColor, radius = 4.dp.toPx(), center = c)

            // "₹38 ▲ | 26 Oct, 09:46" centred over the scrubber, clamped to the chart.
            val label = buildAnnotatedString {
                withStyle(SpanStyle(color = strong, fontWeight = FontWeight.SemiBold)) { append(formatRupees(p.gmp)) }
                when (dayDirection(points, sel)) {
                    "up" -> withStyle(SpanStyle(color = GmpChartColors.Up)) { append(" ▲") }
                    "down" -> withStyle(SpanStyle(color = GmpChartColors.Down)) { append(" ▼") }
                }
                withStyle(SpanStyle(color = muted)) {
                    append(" | ${p.date.dayMonth()}")
                    p.lastUpdated?.let { append(", $it") }
                }
            }
            val layout = textMeasurer.measure(label, labelStyle)
            val maxX = (size.width - layout.size.width).coerceAtLeast(0f)
            drawText(layout, topLeft = Offset((px - layout.size.width / 2f).coerceIn(0f, maxX), 0f))
        }
    }
}

@Preview(showBackground = true, widthDp = 380)
@Composable
private fun GmpChartSectionPreview() {
    val start = LocalDate.of(2026, 10, 20)
    val values = listOf(30, 30, 35, 38, 38, 35, 38, 40, 44, 51, 68, 70)
    MaterialTheme {
        Surface {
            GmpChartSection(
                points = values.mapIndexed { i, v -> GmpChartPoint(start.plusDays(i.toLong()), v) },
                subtitle = "Mainboard · GMP · Lists 3 Nov",
                modifier = Modifier.padding(16.dp),
            )
        }
    }
}
