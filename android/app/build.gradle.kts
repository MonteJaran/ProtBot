plugins {
    id("com.android.application") version "8.7.3"
    kotlin("android") version "2.0.21"
    // Required from Kotlin 2.0 on. The Compose compiler used to be a separate
    // artifact selected through `composeOptions.kotlinCompilerExtensionVersion`;
    // in 2.0 it moved into the Kotlin project and became this plugin, and AGP
    // fails the build outright when `buildFeatures.compose` is on without it:
    //
    //     Starting in Kotlin 2.0, the Compose Compiler Gradle plugin is
    //     required when compose is enabled.
    //
    // Nothing here had ever been compiled, so the old form sat in this file
    // looking correct. Its version is tied to the Kotlin version, not chosen.
    id("org.jetbrains.kotlin.plugin.compose") version "2.0.21"
    id("com.google.devtools.ksp") version "2.0.21-1.0.28"
}

android {
    namespace = "app.protbot"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.protbot"
        // 26 (Oreo) is the floor: UsageStatsManager.queryEvents is usable
        // earlier, but background execution limits and notification channels
        // below this are a different app.
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                // This file has to exist. Gradle fails the release build with
                // "file not found" rather than treating a missing rules file
                // as an empty one, and it was referenced here without ever
                // being written.
                "proguard-rules.pro",
            )
        }
        debug {
            // So a debug build can be installed alongside a release one, and
            // so a tester can tell at a glance which they are running.
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions { jvmTarget = "17" }

    buildFeatures { compose = true }
    // No `composeOptions` block: the Compose compiler version is the Kotlin
    // plugin's version now, and setting it here has no effect under Kotlin 2.0.

    sourceSets["main"].java.srcDirs("src/main/kotlin")
}

dependencies {
    // The shared rules. Everything the app enforces is decided in here, so it
    // stays testable without a device.
    implementation(project(":core"))

    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.activity:activity-compose:1.9.3")

    val compose = "1.7.6"
    implementation("androidx.compose.ui:ui:$compose")
    implementation("androidx.compose.material3:material3:1.3.1")
    implementation("androidx.compose.ui:ui-tooling-preview:$compose")
    // The other half of ui-tooling-preview. Without it a @Preview composable
    // compiles and renders nothing, and it is debug-only so it never reaches
    // a release build.
    debugImplementation("androidx.compose.ui:ui-tooling:$compose")

    val room = "2.6.1"
    implementation("androidx.room:room-runtime:$room")
    implementation("androidx.room:room-ktx:$room")
    ksp("androidx.room:room-compiler:$room")

    implementation("androidx.work:work-runtime-ktx:2.10.0")

    // Declared explicitly rather than relied on transitively: the sync client
    // and the blocker's policy refresh both use it directly, and a transitive
    // version that moves under us would break them without touching this file.
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    testImplementation(kotlin("test"))
}
