package com.coffeelab.tokeneye

import android.Manifest
import android.content.ClipboardManager
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
import com.coffeelab.tokeneye.core.ConfigLoader
import com.coffeelab.tokeneye.core.ConfigRepository
import com.coffeelab.tokeneye.core.Provider
import com.coffeelab.tokeneye.core.RefreshEngine
import com.coffeelab.tokeneye.core.SecretStore
import com.coffeelab.tokeneye.core.Snapshot
import com.coffeelab.tokeneye.core.SnapshotStore
import com.coffeelab.tokeneye.core.Status
import com.coffeelab.tokeneye.core.validateConfigJson
import com.coffeelab.tokeneye.work.RefreshWorker
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 设置页 MVP：provider 列表 + 密钥录入 + 启用开关 + 剪贴板导入 providers.json + 立即刷新。
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TokenEyeApp() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val secrets = remember { SecretStore(context) }

    var snapshot by remember { mutableStateOf(SnapshotStore.load(context)) }
    var providers by remember { mutableStateOf(ConfigRepository.load(context).providers) }
    var refreshing by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<Provider?>(null) }
    var message by remember { mutableStateOf<String?>(null) }

    val doRefresh: (Boolean) -> Unit = { force ->
        scope.launch {
            refreshing = true
            try {
                snapshot = RefreshEngine.refresh(context, force = force)
            } catch (e: Exception) {
                message = "刷新失败：${e.message}"
            }
            refreshing = false
        }
    }

    // 打开 App 时若快照已陈旧（>15 分钟）自动刷新
    LaunchedEffect(Unit) {
        if (System.currentTimeMillis() - snapshot.fetchedAt > 15 * 60 * 1000) doRefresh(false)
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
                Text(
                    "上次更新：" + if (snapshot.fetchedAt == 0L) "从未"
                    else TIME_FMT.format(Date(snapshot.fetchedAt)),
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))

                LazyColumn(modifier = Modifier.weight(1f)) {
                    items(providers, key = { it.id }) { p ->
                        ProviderCard(
                            provider = p,
                            result = snapshot.results.firstOrNull { it.id == p.id },
                            hasKey = secrets.get(p.id).isNotBlank(),
                            onToggle = { enabled ->
                                providers = toggleProvider(context, providers, p.id, enabled)
                            },
                            onEditKey = { editing = p },
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
                    OutlinedButton(onClick = {
                        val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        val clip = cm.primaryClip?.getItemAt(0)?.text?.toString()
                        if (clip.isNullOrBlank()) {
                            message = "剪贴板为空，先复制 providers.json 内容"
                        } else {
                            val err = validateConfigJsonCompat(clip)
                            if (err != null) {
                                message = "导入失败：$err"
                            } else {
                                ConfigRepository.saveUserConfig(context, clip)
                                providers = ConfigRepository.load(context).providers
                                message = "已导入，配置生效"
                            }
                        }
                    }) {
                        Text("剪贴板导入配置")
                    }
                }
            }
        }
    }

    editing?.let { p ->
        KeyEditDialog(
            provider = p,
            current = secrets.get(p.id),
            onDismiss = { editing = null },
            onSave = { key ->
                if (key.isBlank()) secrets.remove(p.id) else secrets.set(p.id, key)
                editing = null
            },
        )
    }
}

private val TIME_FMT = SimpleDateFormat("HH:mm", Locale.getDefault())

private fun validateConfigJsonCompat(text: String): String? = try {
    val root = com.google.gson.JsonParser.parseString(text)
    if (!root.isJsonObject) "根节点不是对象" else validateConfigJson(root.asJsonObject)
} catch (e: Exception) {
    "JSON 无效：${e.message}"
}

private fun toggleProvider(context: Context, providers: List<Provider>, id: String, enabled: Boolean): List<Provider> {
    val raw = ConfigRepository.loadRaw(context)
    return try {
        val root = com.google.gson.JsonParser.parseString(raw).asJsonObject
        root.getAsJsonArray("providers")?.forEach { el ->
            val o = el.asJsonObject
            if (o.get("id")?.asString == id) o.addProperty("enabled", enabled)
        }
        ConfigRepository.saveUserConfig(context, root.toString())
        ConfigLoader.parse(root.toString()).providers
    } catch (e: Exception) {
        providers
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
                        else -> statusText(result.status)
                    },
                    fontSize = 12.sp,
                    color = when {
                        !hasKey -> MaterialTheme.colorScheme.onSurfaceVariant
                        result == null -> MaterialTheme.colorScheme.onSurfaceVariant
                        else -> statusColor(result.status)
                    },
                )
                Spacer(Modifier.weight(1f))
                Switch(checked = provider.enabled, onCheckedChange = onToggle)
            }
            result?.let {
                Text(it.summary, style = MaterialTheme.typography.bodyLarge)
                it.details.take(3).forEach { d ->
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
