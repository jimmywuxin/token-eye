package com.coffeelab.tokeneye

import android.Manifest
import android.content.Context
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
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
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.coffeelab.tokeneye.BuildConfig
import com.coffeelab.tokeneye.core.ConfigRepository
import com.coffeelab.tokeneye.core.EnabledStore
import com.coffeelab.tokeneye.core.Provider
import com.coffeelab.tokeneye.core.RefreshEngine
import com.coffeelab.tokeneye.core.SecretStore
import com.coffeelab.tokeneye.core.SecretStoreInvalidatedException
import com.coffeelab.tokeneye.core.Snapshot
import com.coffeelab.tokeneye.core.SnapshotStore
import com.coffeelab.tokeneye.core.Status
import com.coffeelab.tokeneye.work.RefreshWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 设置页：provider 列表 + 密钥录入 + 启用开关 + 立即刷新。
 *
 * 配置本体只读 assets（见 [ConfigRepository]），本页**不提供改配置入口** ——
 * 改配置走 git：改根目录 providers.json → 拷 assets → 重打 APK。
 */
class MainActivity : ComponentActivity() {

    private val notifPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33) {
            notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        setContent { TokenEyeApp() }
    }
}

/** 首屏一次性加载结果（全在 IO 线程产出，组合期只读内存） */
private data class InitData(
    val providers: List<Provider>,
    val snapshot: Snapshot,
    val invalidated: Boolean,
    val keyStates: Map<String, Boolean>,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TokenEyeApp() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    // 进程级单例；构造不触发加密 prefs 打开（lazy），读写都在 IO 线程
    val secrets = remember { SecretStore.getInstance(context) }

    // 组合期只读内存：初始为空，统一在 LaunchedEffect 里切 IO 一次性加载，
    // 避免 SnapshotStore / ConfigRepository / SecretStore 的文件 IO 落到主线程。
    var snapshot by remember { mutableStateOf(Snapshot()) }
    var providers by remember { mutableStateOf(emptyList<Provider>()) }
    var keyStates by remember { mutableStateOf<Map<String, Boolean>>(emptyMap()) }
    var refreshing by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<Provider?>(null) }
    var editingCurrentKey by remember { mutableStateOf("") }
    var message by remember { mutableStateOf<String?>(null) }

    val doRefresh: (Boolean) -> Unit = { force ->
        scope.launch {
            refreshing = true
            try {
                // RefreshEngine 内部仍自带 IO 切换，这里再包一层保证组合触发路径也不占主线程
                val outcome = withContext(Dispatchers.IO) {
                    RefreshEngine.refresh(context, force = force)
                }
                snapshot = outcome.snapshot
                // 有平台没拉成功时给一句提示；小部件仍显示上次数据 + 「数据陈旧」标注。
                // 与 RefreshWorker 同一套自愈路径：失败就排接力任务并累加连续失败计数，
                // 成功则清零（否则「在 App 内手动刷新失败」这条路径不经过 Worker、永远不自愈）
                if (outcome.anyFailed) {
                    message = "部分平台更新失败，显示的是上次数据"
                    RefreshWorker.enqueueRecovery(context)
                } else {
                    message = null
                    RefreshWorker.clearFailStreak(context)
                }
            } catch (e: Exception) {
                message = "刷新失败：${e.message}"
                RefreshWorker.enqueueRecovery(context)
            }
            refreshing = false
        }
    }

    // 打开 App：一次性读入快照 / 配置 / 密钥状态（IO），再按陈旧程度决定是否自动刷新
    LaunchedEffect(Unit) {
        val init = withContext(Dispatchers.IO) {
            val cfg = ConfigRepository.load(context).providers
            val snap = SnapshotStore.load(context)
            val (invalidated, keys) = try {
                false to cfg.associate { it.id to secrets.get(it.id).isNotBlank() }
            } catch (e: SecretStoreInvalidatedException) {
                true to cfg.associate { it.id to false }
            }
            InitData(cfg, snap, invalidated, keys)
        }
        providers = init.providers
        snapshot = init.snapshot
        keyStates = init.keyStates
        when {
            init.invalidated -> message = "加密密钥已失效，请重新录入各平台 API Key"
            System.currentTimeMillis() - init.snapshot.fetchedAt > 15 * 60 * 1000 -> doRefresh(false)
        }
    }

    MaterialTheme {
        Scaffold(
            topBar = {
                TopAppBar(title = { Text("Token Eye") })
            },
        ) { padding ->
            Column(
                modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp),
            ) {
                // 顶部一行：上次更新在左、版本号在右（版本与 Mac/Linux 端 tag 同步）
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "上次更新：" + if (snapshot.fetchedAt == 0L) "从未"
                        else TIME_FMT.format(Date(snapshot.fetchedAt)),
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.weight(1f))
                    Text(
                        "v${BuildConfig.VERSION_NAME}",
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(8.dp))

                LazyColumn(modifier = Modifier.weight(1f)) {
                    items(providers, key = { it.id }) { p ->
                        ProviderCard(
                            provider = p,
                            result = snapshot.results.firstOrNull { it.id == p.id },
                            hasKey = keyStates[p.id] ?: false,
                            onToggle = { enabled ->
                                scope.launch {
                                    val (next, ok) = toggleProvider(context, providers, p.id, enabled)
                                    if (ok) {
                                        providers = next
                                    } else {
                                        message = "启用状态保存失败，已保留原状态"
                                    }
                                }
                            },
                            onEditKey = {
                                scope.launch {
                                    // 打开对话框前在 IO 线程读一次当前密钥，避免组合期读加密 prefs
                                    editingCurrentKey = withContext(Dispatchers.IO) {
                                        try { secrets.get(p.id) } catch (e: SecretStoreInvalidatedException) { "" }
                                    }
                                    editing = p
                                }
                            },
                        )
                    }
                }

                message?.let {
                    Text(it, fontSize = 12.sp, color = MaterialTheme.colorScheme.error)
                    Spacer(Modifier.height(4.dp))
                }

                Row(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Button(onClick = { doRefresh(true) }, enabled = !refreshing) {
                        if (refreshing) {
                            CircularProgressIndicator(modifier = Modifier.width(16.dp).height(16.dp), strokeWidth = 2.dp)
                            Spacer(Modifier.width(6.dp))
                        }
                        Text(if (refreshing) "刷新中" else "立即刷新")
                    }
                }
            }
        }
    }

    editing?.let { p ->
        KeyEditDialog(
            provider = p,
            current = editingCurrentKey,
            onDismiss = { editing = null },
            onSave = { key ->
                scope.launch {
                    val ok = withContext(Dispatchers.IO) {
                        try {
                            if (key.isBlank()) secrets.remove(p.id) else secrets.set(p.id, key)
                            true
                        } catch (e: SecretStoreInvalidatedException) {
                            false
                        }
                    }
                    if (ok) {
                        // 只更新内存 hasKey 状态，不重新读加密 prefs
                        keyStates = keyStates + (p.id to key.isNotBlank())
                        editing = null
                    } else {
                        message = "加密密钥已失效，请重新打开 App 后重试"
                    }
                }
            },
        )
    }
}

private val TIME_FMT = SimpleDateFormat("HH:mm", Locale.getDefault())

/**
 * 切换某平台的启用状态。
 *
 * 只把 `{"id": false}` 写进 [EnabledStore]，**不改写配置本体**（旧实现把整份 providers.json
 * 写进 filesDir，会把手机端配置永久冻结在那一刻的版本，重装 APK 也更新不了）。
 * 覆盖由 [ConfigRepository.load] 统一叠加。返回写回是否成功，UI 层据此提示 / 回滚。
 */
private suspend fun toggleProvider(
    context: Context,
    providers: List<Provider>,
    id: String,
    enabled: Boolean,
): Pair<List<Provider>, Boolean> {
    val ok = withContext(Dispatchers.IO) { EnabledStore.set(context, id, enabled) }
    return if (ok) {
        providers.map { if (it.id == id) it.copy(enabled = enabled) else it } to true
    } else {
        providers to false
    }
}

@Composable
private fun ProviderCard(
    provider: Provider,
    result: com.coffeelab.tokeneye.core.ProviderResult?,
    hasKey: Boolean,
    onToggle: (Boolean) -> Unit,
    onEditKey: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(provider.name, style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.width(8.dp))
                Text(
                    when {
                        !hasKey -> "未配置密钥"
                        result == null -> "待刷新"
                        result.stale -> "${statusText(result.status)}（数据陈旧）"
                        else -> statusText(result.status)
                    },
                    fontSize = 12.sp,
                    color = when {
                        !hasKey -> MaterialTheme.colorScheme.onSurfaceVariant
                        result == null -> MaterialTheme.colorScheme.onSurfaceVariant
                        result?.stale == true -> statusColor(Status.WARN)
                        else -> statusColor(result.status)
                    },
                )
                Spacer(Modifier.weight(1f))
                Switch(checked = provider.enabled, onCheckedChange = onToggle)
            }
            result?.let {
                Text(it.summary, style = MaterialTheme.typography.bodyLarge)
                // details 只渲染「最后一行」—— peakWindow 行 / 重置行都是末尾追加的；
                // 其他解释性行（"DeepSeek：¥X" / "阈值" / "货币" / "general" / "5h 剩余"）
                // 是从 Mac 版 `lines` 照搬的，对小屏 App 冗余，按小屏排版过滤
                it.details.lastOrNull()?.let { d ->
                    Text(d, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Spacer(Modifier.height(4.dp))
            Row {
                OutlinedButton(onClick = onEditKey) {
                    Text(if (hasKey) "修改密钥" else "填写密钥")
                }
            }
        }
    }
}

@Composable
private fun KeyEditDialog(
    provider: Provider,
    current: String,
    onDismiss: () -> Unit,
    onSave: (String) -> Unit,
) {
    var text by remember { mutableStateOf(current) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("${provider.name} API Key") },
        text = {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
                placeholder = { Text("粘贴 API Key / Cookie") },
            )
        },
        confirmButton = { Button(onClick = { onSave(text) }) { Text("保存") } },
        dismissButton = { OutlinedButton(onClick = onDismiss) { Text("取消") } },
    )
}

private fun statusText(status: Status): String = when (status) {
    Status.OK -> "正常"
    Status.WARN -> "告警"
    Status.ERR -> "错误"
    Status.NOKEY -> "未配置密钥"
}

private fun statusColor(status: Status) = when (status) {
    Status.OK -> androidx.compose.ui.graphics.Color(0xFF0F6E56)
    Status.WARN -> androidx.compose.ui.graphics.Color(0xFF854F0B)
    Status.ERR -> androidx.compose.ui.graphics.Color(0xFFA32D2D)
    Status.NOKEY -> androidx.compose.ui.graphics.Color(0xFF5F5E5A)
}
