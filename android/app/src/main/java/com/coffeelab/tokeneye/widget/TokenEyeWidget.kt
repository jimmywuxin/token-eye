package com.coffeelab.tokeneye.widget

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.GlanceTheme
import androidx.glance.LocalSize
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.SizeMode
import androidx.glance.appwidget.action.ActionCallback
import androidx.glance.appwidget.action.actionRunCallback
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.provideContent
import androidx.glance.background
import androidx.glance.action.ActionParameters
import androidx.glance.action.clickable
import androidx.glance.layout.Alignment
import androidx.glance.layout.Box
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
import com.coffeelab.tokeneye.core.ConfigRepository
import com.coffeelab.tokeneye.core.ProviderResult
import com.coffeelab.tokeneye.core.Snapshot
import com.coffeelab.tokeneye.core.SnapshotStore
import com.coffeelab.tokeneye.core.Status
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.roundToInt

/**
 * 桌面小部件 = Mac 版菜单栏的 Android 对应物。
 * - 只展示「已配置密钥」的平台：配置几个显示几个，未配置的不占行
 * - SizeMode.Exact：按用户拖出的实际尺寸自适应字号/行距（1 格紧凑 → 3 格放大）
 * - 内容整体垂直居中，多余空间不堆在底部，避免空洞感
 * - 点按任意位置立即刷新
 */
class TokenEyeWidget : GlanceAppWidget() {

    override val sizeMode = SizeMode.Exact

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val snapshot = SnapshotStore.load(context)
        // 以当前配置为准：配置里已移除/未配置密钥的平台不占行（快照残留行也一并过滤）
        val allowedIds = ConfigRepository.load(context).providers.map { it.id }.toSet()
        val rows = snapshot.results.filter { it.id in allowedIds && it.status != Status.NOKEY }
        provideContent {
            GlanceTheme {
                WidgetContent(snapshot, rows)
            }
        }
    }

    @Composable
    private fun WidgetContent(snapshot: Snapshot, rows: List<ProviderResult>) {
        val size = LocalSize.current
        val m = metrics(width = size.width, height = size.height, rows = rows)

        Column(
            modifier = GlanceModifier.fillMaxSize()
                .background(GlanceTheme.colors.widgetBackground)
                .cornerRadius(16.dp)
                .clickable(onClick = actionRunCallback<RefreshAction>())
                .padding(horizontal = m.hPad, vertical = m.vPad),
            // 自上而下排列：字号固定，多余空间留在底部（用户可拖小到 1 格）
            verticalAlignment = Alignment.Vertical.Top,
        ) {
            if (m.showHeader) {
                Row(
                    modifier = GlanceModifier.fillMaxWidth(),
                    verticalAlignment = Alignment.Vertical.CenterVertically,
                ) {
                    Text(
                        "Token Eye",
                        style = TextStyle(
                            fontSize = m.titleSize,
                            fontWeight = FontWeight.Bold,
                            color = GlanceTheme.colors.onSurface,
                        ),
                        maxLines = 1,
                    )
                    Spacer(modifier = GlanceModifier.defaultWeight())
                    if (m.showTime) {
                        Text(
                            "更新 " + TIME_FMT.format(Date(snapshot.fetchedAt)),
                            style = TextStyle(
                                fontSize = m.metaSize,
                                color = GlanceTheme.colors.onSurfaceVariant,
                            ),
                            maxLines = 1,
                        )
                    }
                }
                Spacer(modifier = GlanceModifier.height(m.gap))
            }

            if (rows.isEmpty()) {
                Box(modifier = GlanceModifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(
                        "点按刷新（未配置密钥）",
                        style = TextStyle(
                            fontSize = m.rowSize,
                            color = GlanceTheme.colors.onSurfaceVariant,
                        ),
                        maxLines = 1,
                    )
                }
            } else {
                rows.forEachIndexed { i, r ->
                    if (i > 0) Spacer(modifier = GlanceModifier.height(m.gap))
                    ProviderRow(r, m)
                }
            }
        }
    }

    /** 单行布局：状态点 + 名称（左） + 数值（右），字号固定不随尺寸放大 */
    @Composable
    private fun ProviderRow(r: ProviderResult, m: Metrics) {
        Row(
            modifier = GlanceModifier.fillMaxWidth(),
            verticalAlignment = Alignment.Vertical.CenterVertically,
        ) {
            StatusDot(r.status, m.dotSize)
            Spacer(modifier = GlanceModifier.width((m.dotSize.value * 0.8f).dp))
            Text(
                r.name,
                style = TextStyle(fontSize = m.rowSize, color = GlanceTheme.colors.onSurface),
                maxLines = 1,
                modifier = GlanceModifier.defaultWeight(),
            )
            Text(
                summaryCandidates(shortSummary(r))[m.summaryLevel],
                style = TextStyle(
                    fontSize = m.rowSize,
                    fontWeight = FontWeight.Bold,
                    color = ColorProvider(statusColor(r.status)),
                ),
                maxLines = 1,
            )
        }
    }

    /** 小部件空间有限：错误摘要只留关键词（如「鉴权失败 401」） */
    private fun shortSummary(r: ProviderResult): String {
        if (r.status != Status.ERR) return r.summary
        val code = Regex("""\d{3}""").find(r.summary)?.value
        val kind = when {
            r.summary.contains("鉴权") -> "鉴权失败"
            r.summary.contains("超时") -> "超时"
            r.summary.contains("网络") -> "网络错误"
            r.summary.contains("服务端") -> "服务异常"
            r.summary.contains("解析") -> "解析失败"
            else -> "错误"
        }
        return if (code != null) "$kind $code" else kind
    }

    @Composable
    private fun StatusDot(status: Status, size: Dp) {
        Box(
            modifier = GlanceModifier
                .width(size)
                .height(size)
                .background(ColorProvider(statusColor(status))),
        ) {}
    }

    /** 沿用项目 Okabe-Ito 配色，深浅底色下均可读 */
    private fun statusColor(status: Status): Color = when (status) {
        Status.OK -> Color(0xFF1D9E75)
        Status.WARN -> Color(0xFFE69F00)
        Status.ERR -> Color(0xFFD1495B)
        Status.NOKEY -> Color(0xFF888888)
    }

    /** 按小部件实际尺寸推导排版参数：字号固定，自上而下排列；宽度不足时缩短摘要 */
    private data class Metrics(
        val showHeader: Boolean,
        val showTime: Boolean,
        val summaryLevel: Int,
        val titleSize: TextUnit,
        val metaSize: TextUnit,
        val rowSize: TextUnit,
        val dotSize: Dp,
        val gap: Dp,
        val hPad: Dp,
        val vPad: Dp,
    )

    private fun metrics(width: Dp, height: Dp, rows: List<ProviderResult>): Metrics {
        val h = height.value
        val w = width.value
        val n = rows.size.coerceAtLeast(1)
        // 1 格高（≈40-70dp）装不下「标题行 + 数据行」，此时只留数据
        val showHeader = h >= 72f
        val titleSize = 10f.sp
        val vPad = if (showHeader) 8f.dp else 1f.dp
        val hPad = if (w < 160f) 8f.dp else 12f.dp

        // 字号固定：只受宽度约束（放不下就缩短摘要，实在不行才缩字）
        val cands = rows.map { summaryCandidates(shortSummary(it)) }
        val nameEm = rows.map { emWidth(it.name) }
        val availW = w - 2f * hPad.value
        val (rowSize, level) = fitRow(availW, nameEm, cands)

        // 行距：把富余高度匀一部分进来，但不撑太开（上限 MAX_GAP），其余留在底部
        val headerH = if (showHeader) titleSize.value * 1.4f else 0f
        val contentH = headerH + n * rowSize * 1.35f
        val spare = (h - 2f * vPad.value - contentH) / (n + 1)
        val gap = if (showHeader) spare.coerceIn(4f, MAX_GAP) else 1f

        return Metrics(
            showHeader = showHeader,
            showTime = w >= 210f,
            summaryLevel = level,
            titleSize = titleSize,
            metaSize = 9f.sp,
            rowSize = rowSize.sp,
            dotSize = (rowSize * 0.5f).roundToInt().toFloat().dp,
            gap = gap.dp,
            hPad = hPad,
            vPad = vPad,
        )
    }

    /**
     * 固定字号 ROW_FS，宽度装不下时逐级缩短摘要；最短摘要仍放不下才缩字号（下限 9sp）。
     * 返回 (字号, 摘要级别)
     */
    private fun fitRow(
        availW: Float,
        nameEm: List<Double>,
        cands: List<List<String>>,
    ): Pair<Float, Int> {
        val last = cands[0].lastIndex
        for (level in 0 until last) {
            val need = cands.indices.maxOf { i ->
                nameEm[i] + DOT_EM + emWidth(cands[i][level])
            }.toFloat()
            val fs = minOf(ROW_FS, availW / need)
            if (fs >= ROW_FS * 0.9f) return fs to level
        }
        val need = cands.indices.maxOf { i ->
            nameEm[i] + DOT_EM + emWidth(cands[i][last])
        }.toFloat()
        return maxOf(9f, minOf(ROW_FS, availW / need)) to last
    }

    /**
     * 摘要候选（由详到略）：完整 → 去掉「· 」后的段落 → 只留百分比。
     * 无分隔符的短摘要（如「¥12.34」）三级相同，不会被误压缩。
     */
    private fun summaryCandidates(s: String): List<String> {
        val head = s.substringBefore(" · ").trim()
        val pct = Regex("""\d+(?:\.\d+)?%""").find(s)?.value
        return listOf(s, head, pct ?: head)
    }

    /** 粗略字宽估算（单位 em）：中日韩全角按 1.0，空格 0.3，其余 0.55 */
    private fun emWidth(s: String): Double = s.sumOf { c ->
        when {
            c.code > 0x2E80 -> 1.0
            c.isWhitespace() -> 0.3
            else -> 0.55
        }
    }

    private companion object {
        val TIME_FMT = SimpleDateFormat("HH:mm", Locale.getDefault())
        /** 数据行固定字号（不随小部件尺寸放大） */
        const val ROW_FS = 13f
        /** 富余高度匀给行距的上限，避免高格子里行距撑太开 */
        const val MAX_GAP = 12f
        /** 状态圆点 + 间隔占用的宽度（em，以行字号为基准） */
        const val DOT_EM = 1.2
    }
}

/** 小部件点击 → 立即刷新 */
class RefreshAction : ActionCallback {
    override suspend fun onAction(
        context: Context,
        glanceId: GlanceId,
        parameters: ActionParameters,
    ) {
        com.coffeelab.tokeneye.work.RefreshWorker.refreshNow(context, force = true)
    }
}
