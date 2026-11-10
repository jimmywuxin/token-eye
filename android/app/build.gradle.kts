plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// 版本号唯一真源 = 上游核心的 VERSION（swiftbar/token_eye.py），Android 自动跟随，
// 不再手工维护第三处（app 版本号曾长期停在 0.19.1 就是这么漂移的）。
// versionCode 由版本号推导，保证单调递增以满足 `adb install -r` 覆盖升级：0.22.0 → 2200。
val tokenEyeVersion: String = file("../../swiftbar/token_eye.py")
    .readLines()
    .first { it.startsWith("VERSION = ") }
    .substringAfter('"').substringBefore('"')
val tokenEyeVersionCode: Int =
    tokenEyeVersion.split('.').fold(0) { acc, part -> acc * 100 + part.toInt() }

android {
    namespace = "com.coffeelab.tokeneye"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.coffeelab.tokeneye"
        minSdk = 30
        targetSdk = 35
        versionCode = tokenEyeVersionCode
        versionName = tokenEyeVersion
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            // 与 Coffee Notes 同策略：release 复用 debug 签名，adb install -r 可无缝覆盖
            signingConfig = signingConfigs.getByName("debug")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        // 顶部显示当前版本号需要 BuildConfig.VERSION_NAME（AGP 8 默认关闭，需显式开启）
        buildConfig = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.9.0")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation(platform("androidx.compose:compose-bom:2025.05.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.glance:glance-appwidget:1.1.1")
    implementation("androidx.work:work-runtime-ktx:2.10.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("androidx.security:security-crypto:1.1.0")
    implementation("com.google.code.gson:gson:2.13.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")

    testImplementation("junit:junit:4.13.2")
}

// 构建期把根目录 providers.json / holidays 同步进 assets，替代手工拷贝。
// 只按 scripts/sync-android-assets.py 的显式白名单剔除移动端不支持的平台；
// 内容无变化时脚本不写文件，避免每次构建把工作区弄脏。
// make validate / CI 另有 `--check`（只读）校验提交副本是否最新。
val syncAndroidAssets = tasks.register<Exec>("syncAndroidAssets") {
    description = "Sync root providers.json / holidays into Android assets"
    group = "token-eye"
    val repoRoot = rootProject.projectDir.parentFile
    workingDir(repoRoot)
    commandLine("python3", "scripts/sync-android-assets.py")
    inputs.file(repoRoot.resolve("providers.json"))
    inputs.dir(repoRoot.resolve("holidays"))
    outputs.file(file("src/main/assets/providers.json"))
    outputs.dir(file("src/main/assets/holidays"))
}
tasks.matching { it.name == "preBuild" }.configureEach {
    dependsOn(syncAndroidAssets)
}
