import java.util.Base64

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("app.cash.paparazzi") version "1.3.5"
}

// 和 AppUpdate.versionCodeOf 同一条规则：主版本 * 1000000 + 次版本 * 1000 + 修订。
fun releaseVersionCode(versionName: String): Int {
    val parts = versionName.split(".")
    return parts[0].toInt() * 1_000_000 + parts[1].toInt() * 1_000 + parts[2].toInt()
}

val appVersion = (findProperty("lorabge.versionName") as String?) ?: "0.1.8"
val skipNative = findProperty("lorabge.skipNative") == "true"
fun secretOr(name: String, fallback: String): String =
    System.getenv(name)?.trim()?.takeIf { it.isNotEmpty() } ?: fallback

val keystoreB64 = System.getenv("ANDROID_KEYSTORE_B64").orEmpty()
val signingStore = if (keystoreB64.isNotBlank()) {
    val out = layout.buildDirectory.file("ci-keystore.jks").get().asFile
    out.parentFile.mkdirs()
    out.writeBytes(Base64.getDecoder().decode(keystoreB64))
    out
} else {
    rootProject.file("keystore/debug-test-only.jks")
}

android {
    namespace = "com.lorabge.memory"
    compileSdk = 35
    ndkVersion = "27.2.12479018"

    defaultConfig {
        applicationId = "com.lorabge.memory"
        minSdk = 29
        targetSdk = 35
        versionName = appVersion
        versionCode = releaseVersionCode(appVersion)
        if (!skipNative) {
            ndk {
                abiFilters += "arm64-v8a"
            }
            externalNativeBuild {
                cmake {
                    cppFlags += "-std=c++17"
                }
            }
        }
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        create("stable") {
            storeFile = signingStore
            storePassword = secretOr("ANDROID_KEYSTORE_PASS", "lorabge-test-only")
            keyAlias = secretOr("ANDROID_KEY_ALIAS", "lorabge-test")
            keyPassword = secretOr("ANDROID_KEY_PASS", "lorabge-test-only")
        }
    }

    buildTypes {
        debug {
            isDebuggable = true
            signingConfig = signingConfigs.getByName("stable")
        }
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("stable")
        }
    }

    // 草稿注入只在显式打开的仪器测试包里。发布用的 debug 包和 release 包都走空实现，dex 里没有这条路径。
    val e2eHooks = findProperty("lorabge.e2eHooks") == "true"
    sourceSets {
        getByName("debug") {
            java.srcDir(if (e2eHooks) "src/e2eHooks/java" else "src/e2eHooksOff/java")
        }
        getByName("release") {
            java.srcDir("src/e2eHooksOff/java")
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
    }
    if (!skipNative) {
        externalNativeBuild {
            cmake {
                path = file("src/main/cpp/CMakeLists.txt")
                version = "3.22.1"
            }
        }
    }
    packaging {
        jniLibs {
            useLegacyPackaging = true
            if (skipNative) {
                excludes += setOf("**/*.so")
            }
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.10.01")
    implementation(composeBom)
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.core:core-ktx:1.15.0")
    debugImplementation("androidx.compose.ui:ui-tooling")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    androidTestImplementation(composeBom)
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test:core:1.6.1")
    androidTestImplementation("androidx.test.uiautomator:uiautomator:2.3.0")
}

tasks.withType<Test> {
    // 单元测试跑在 JVM 上,android.jar 里的 org.json 是空壳。换成真正的实现。
    classpath = files(classpath.filter { file -> !file.name.contains("android.jar") })
}
