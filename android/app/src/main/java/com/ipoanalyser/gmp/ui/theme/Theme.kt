package com.ipoanalyser.gmp.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Same tokens as the web preview (backend/preview/index.html) so both look identical.
private val Light = lightColorScheme(
    primary = Color(0xFF5367FF),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFE6E9FF),
    onPrimaryContainer = Color(0xFF1B2A99),
    background = Color.White,
    onBackground = Color(0xFF2B2D3A),
    surface = Color.White,
    onSurface = Color(0xFF2B2D3A),
    surfaceVariant = Color(0xFFF3F3F5), // "pill" grey
    onSurfaceVariant = Color(0xFF7C7E8C), // muted text
    outline = Color(0xFFD5D5DA),
    outlineVariant = Color(0xFFE9E9EB), // hairlines and card borders
    surfaceContainerLow = Color.White,
    surfaceContainer = Color.White,
    surfaceContainerHigh = Color(0xFFF7F7F9),
    surfaceContainerHighest = Color(0xFFF3F3F5),
)

private val Dark = darkColorScheme(
    primary = Color(0xFF8B97FF),
    onPrimary = Color(0xFF0B1240),
    primaryContainer = Color(0xFF26306E),
    onPrimaryContainer = Color(0xFFDDE1FF),
    background = Color(0xFF121212),
    onBackground = Color(0xFFF2F2F5),
    surface = Color(0xFF121212),
    onSurface = Color(0xFFF2F2F5),
    surfaceVariant = Color(0xFF232327),
    onSurfaceVariant = Color(0xFF8E8E98),
    outline = Color(0xFF3A3A40),
    outlineVariant = Color(0xFF2C2C30),
    surfaceContainerLow = Color(0xFF1D1D21),
    surfaceContainer = Color(0xFF1D1D21),
    surfaceContainerHigh = Color(0xFF232327),
    surfaceContainerHighest = Color(0xFF232327),
)

/** Light by default; dark only when the user turns it on (never follows the system). */
@Composable
fun AppTheme(dark: Boolean, content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (dark) Dark else Light, content = content)
}
