# Token Eye Android — release 混淆规则
# Gson 靠字段名反射读写数据类，泛型签名（List<ProviderResult> / Map<String,Long>）必须保留，
# 否则 release 反序列化 Snapshot 会抛 ClassCastException。
-keepattributes Signature
-keepattributes *Annotation*
-keepattributes EnclosingMethod
-keepattributes InnerClasses

# 只保留被 Gson 反射的数据类：原「全包 core.** keep」过宽，把 ApiClient / RefreshEngine /
# SecretStore 等逻辑类也一并钉死。Snapshot / ProviderResult / Status 由 SnapshotStore 通过
# Gson 序列化；配置模型保留以防未来 Gson 化与反射型日志。逻辑类照常参与混淆/优化。
-keep class com.coffeelab.tokeneye.core.Snapshot { *; }
-keep class com.coffeelab.tokeneye.core.ProviderResult { *; }
-keep class com.coffeelab.tokeneye.core.Status { *; }
-keep class com.coffeelab.tokeneye.core.ApiSpec { *; }
-keep class com.coffeelab.tokeneye.core.EnvelopeSpec { *; }
-keep class com.coffeelab.tokeneye.core.ParserSpec { *; }
-keep class com.coffeelab.tokeneye.core.PeakWindowSpec { *; }
-keep class com.coffeelab.tokeneye.core.DisplaySpec { *; }
-keep class com.coffeelab.tokeneye.core.AlertSpec { *; }
-keep class com.coffeelab.tokeneye.core.Provider { *; }
-keep class com.coffeelab.tokeneye.core.EyeConfig { *; }

# Gson 本体
-keep class com.google.gson.** { *; }
-dontwarn com.google.gson.**
