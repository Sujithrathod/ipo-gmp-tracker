package com.ipoanalyser.gmp.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ipoanalyser.gmp.data.LatestGmpDto
import com.ipoanalyser.gmp.ui.chart.GmpChartColors
import java.util.Locale
import kotlin.math.abs

/** White card with a hairline border, like the web preview's .card. */
@Composable
fun GCard(modifier: Modifier = Modifier, onClick: (() -> Unit)? = null, content: @Composable ColumnScope.() -> Unit) {
    val shape = RoundedCornerShape(14.dp)
    Surface(
        modifier = modifier.fillMaxWidth().clip(shape).then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
        shape = shape,
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(Modifier.padding(horizontal = 16.dp, vertical = 14.dp), content = content)
    }
}

/** Tiny Groww-style line: coloured by change over the period, dashed start line, end dot. */
@Composable
fun Sparkline(values: List<Int>, modifier: Modifier = Modifier.size(width = 84.dp, height = 38.dp)) {
    if (values.size < 2) {
        Box(modifier)
        return
    }
    val color = GmpChartColors.forChange(values.last() - values.first())
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    Canvas(modifier) {
        var lo = values.min().toFloat()
        var hi = values.max().toFloat()
        if (lo == hi) { lo -= 1f; hi += 1f }
        val padX = 3.dp.toPx()
        val padY = 4.dp.toPx()
        fun x(i: Int) = padX + i * (size.width - 2 * padX) / values.lastIndex
        fun y(v: Int) = padY + (hi - v) * (size.height - 2 * padY) / (hi - lo)
        drawLine(
            muted.copy(alpha = 0.35f), Offset(0f, y(values.first())), Offset(size.width, y(values.first())), 1.dp.toPx(),
            pathEffect = PathEffect.dashPathEffect(floatArrayOf(3.dp.toPx(), 3.dp.toPx())),
        )
        val path = Path().apply { values.forEachIndexed { i, v -> if (i == 0) moveTo(x(i), y(v)) else lineTo(x(i), y(v)) } }
        drawPath(path, color, style = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
        drawCircle(color, radius = 3.dp.toPx(), center = Offset(x(values.lastIndex), y(values.last())))
    }
}

/** Small label over a bold value (dashboard card stats). */
@Composable
fun Stat(label: String, value: String, modifier: Modifier = Modifier, valueColor: Color = Color.Unspecified) {
    Column(modifier) {
        Text(label, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
        Text(
            value, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis,
            color = if (valueColor == Color.Unspecified) MaterialTheme.colorScheme.onSurface else valueColor,
        )
    }
}

/** Blue pill, e.g. "Lists in 2 days". */
@Composable
fun Chip(text: String, modifier: Modifier = Modifier) {
    val primary = MaterialTheme.colorScheme.primary
    Text(
        text, fontSize = 12.sp, color = primary,
        modifier = modifier.background(primary.copy(alpha = 0.12f), RoundedCornerShape(50)).padding(horizontal = 8.dp, vertical = 2.dp),
    )
}

/** "▲ +₹12 (30.0%)" in green / "▼ −₹2 (22.2%)" in red, vs the previous day. */
@Composable
fun ChangeBadge(latest: LatestGmpDto?) {
    if (latest?.gmp == null) return
    val change = latest.change
    val direction = latest.trend ?: change?.let { if (it > 0) "up" else if (it < 0) "down" else "flat" } ?: "flat"
    val color = when (direction) { "up" -> GmpChartColors.Up; "down" -> GmpChartColors.Down; else -> GmpChartColors.Flat }
    var text = when (direction) { "up" -> "▲"; "down" -> "▼"; else -> "▶" }
    if (change != null) text += " " + (if (change > 0) "+" else if (change < 0) "−" else "±") + "₹" + abs(change)
    if (change != null && change != 0 && latest.changePct != null) {
        text += " (" + String.format(Locale.ENGLISH, "%.1f", abs(latest.changePct)) + "%)"
    }
    Text(text, color = color, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
}

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface, modifier = modifier)
}

@Composable
fun Muted(text: String, modifier: Modifier = Modifier, size: Int = 12, align: TextAlign? = null) {
    Text(text, fontSize = size.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = modifier, textAlign = align)
}

@Composable
fun LoadingBox() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
}

/** Error / empty state. Scrollable so pull-to-refresh still works on it. */
@Composable
fun MessageBox(text: String, onRetry: (() -> Unit)? = null) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(top = 64.dp, start = 24.dp, end = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Top,
    ) {
        Muted(text, size = 14, align = TextAlign.Center)
        if (onRetry != null) TextButton(onClick = onRetry) { Text("Try again") }
    }
}

const val DISCLAIMER_SOURCE = "Source: ipowatch.in · GMP is unofficial and not investment advice."
