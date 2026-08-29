import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    kotlin("jvm") version "2.4.10"
}

repositories { mavenCentral() }

dependencies {
    testImplementation(kotlin("test"))
}

// Target Java 17 bytecode because that is what current Android builds consume,
// but do NOT pin a toolchain: requiring a specific JDK to be installed makes
// the module unbuildable on machines that have a newer one, which is exactly
// what happened first time. Any JDK 17+ can emit 17-compatible output.
kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

tasks.test {
    useJUnitPlatform()
    testLogging { events("passed", "failed", "skipped") }
}
