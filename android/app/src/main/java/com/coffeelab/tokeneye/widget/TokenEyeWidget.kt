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
            // 多余高度由居中吸收（上方留白 = 下方留白），不再全堆在底部
            verticalAlignment = Alignment.Vertical.CenterVertically,
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
            StatusDot(r.status, m.dotSize, r.stale)
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
                    color = ColorProvider(statusColor(r.status, r.stale)),
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
    private fun StatusDot(status: Status, size: Dp, stale: Boolean = false) {
        Box(
            modifier = GlanceModifier
                .width(size)
                .height(size)
                .background(ColorProvider(statusColor(status, stale)))
                // 圆点：方块在小尺寸下显得笨重，圆点在深色卡片上更精致
                .cornerRadius((size.value / 2f).dp),
        ) {}
    }

    /** 沿用项目 Okabe-Ito 配色，深浅底色下均可读。
     *  陈旧数据（stale）用 WARN 黄点：不是错误（红），但要能看出不是刚拉到的。 */
    private fun statusColor(status: Status, stale: Boolean = false): Color = when {
        stale -> Color(0xFFE69F00)
        else -> when (status) {
            Status.OK -> Color(0xFF1D9E75)
            Status.WARN -> Color(0xFFE69F00)
            Status.ERR -> Color(0xFFD1495B)
            Status.NOKEY -> Color(0xFF888888)
        }
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

        // 先定字号：2 格以上放宽到 READ_FS（宽屏可读性），1 格保持 ROW_FS；
        // 标题跟随数据行一起放大（原 10sp 固定值在 15sp 数据行旁边显得过小）
        val big = h >= 120f
        val baseFs = if (big) READ_FS else ROW_FS
        val titleFs = if (big) READ_FS else TITLE_FS
        val metaFs = if (big) 11f else 9f
        val cands = rows.map { summaryCandidates(shortSummary(it)) }
        val nameEm = rows.map { emWidth(it.name) }
        val availW = w - 2f * hPadFor(w).value
        val (rowSize, level) = if (rows.isEmpty()) baseFs to 0
        else fitRow(availW, nameEm, cands, baseFs)

        // 标题行「装得下才显示」：1 格高 + 多行数据时优先保数据，不再按固定高度阈值切
        val titleBlock = titleFs * 1.4f + MIN_GAP
        val showHeader = h - 2f * VPAD_ROOMY - titleBlock - n * rowSize * 1.35f >= 0f
        val vPad = if (showHeader) VPAD_ROOMY else VPAD_TIGHT

        // 行距：富余高度按「实际间距个数」均分 —— 标题后 1 个 + 行间 n-1 个 = n 个。
        // 原实现除以 (n+1) 且上限 12dp，导致 2 格高时富余高度全堆在底部（大片空白）。
        val headerH = if (showHeader) titleFs * 1.4f else 0f
        val contentH = headerH + n * rowSize * 1.35f
        val spare = (h - 2f * vPad - contentH) / n
        val gap = if (showHeader) spare.coerceIn(MIN_GAP, MAX_GAP) else MIN_GAP_TIGHT

        return Metrics(
            showHeader = showHeader,
            showTime = w >= 210f,
            summaryLevel = level,
            titleSize = titleFs.sp,
            metaSize = metaFs.sp,
            rowSize = rowSize.sp,
            dotSize = (rowSize * 0.5f).roundToInt().toFloat().dp,
            gap = gap.dp,
            hPad = hPadFor(w),
            vPad = vPad.dp,
        )
    }

    private fun hPadFor(width: Float): Dp = if (width < 160f) 8f.dp else 12f.dp

    /**
     * 以 baseFs 为目标字号，宽度装不下时逐级缩短摘要；最短摘要仍放不下才缩字号（下限 9sp）。
     * 返回 (字号, 摘要级别)
     */
    private fun fitRow(
        availW: Float,
        nameEm: List<Double>,
        cands: List<List<String>>,
        baseFs: Float = ROW_FS,
    ): Pair<Float, Int> {
        val last = cands[0].lastIndex
        for (level in 0 until last) {
            val need = cands.indices.maxOf { i ->
                nameEm[i] + DOT_EM + emWidth(cands[i][level])
            }.toFloat()
            val fs = minOf(baseFs, availW / need)
            if (fs >= baseFs * 0.9f) return fs to level
        }
        val need = cands.indices.maxOf { i ->
            nameEm[i] + DOT_EM + emWidth(cands[i][last])
        }.toFloat()
        return maxOf(9f, minOf(baseFs, availW / need)) to last
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
        /** 数据行基础字号（1 格紧凑态） */
        const val ROW_FS = 13f
        /** 2 格及以上的数据行字号：靠字号填充空间，而不是拉大行距 */
        const val READ_FS = 15f
        /** 标题字号：1 格紧凑态（2 格以上与数据行同号，见 metrics） */
        const val TITLE_FS = 11f
        /** 行距下限 / 1 格无标题时的行距 */
        const val MIN_GAP = 4f
        const val MIN_GAP_TIGHT = 1f
        /** 行距上限：行距只做呼吸感，富余高度交给居中（拉开到 30dp 会显得稀疏） */
        const val MAX_GAP = 12f
        /** 垂直内边距：有标题时宽松，1 格紧凑时收窄 */
        const val VPAD_ROOMY = 8f
        const val VPAD_TIGHT = 4f
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
        com.coffeelab.tokeneye.work.RefreshWorker.refreshNow(context)
    }
}
