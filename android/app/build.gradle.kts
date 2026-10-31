import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// Firebase (push notifications) is optional until you drop app/google-services.json
// in from the Firebase console. Without it the app still builds and shows IPO data.
if (file("google-services.json").exists()) {
    apply(plugin = "com.google.gms.google-services")
}

// API base URLs: override in android/local.properties, e.g.
//   api.baseUrl.release=https://ipo-gmp-api.onrender.com/
//   api.baseUrl.debug=http://192.168.1.20:8000/
val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}
fun configValue(name: String, default: String): String =
    localProps.getProperty(name) ?: (project.findProperty(name) as String?) ?: default

// Release signing key: android/keystore.properties (git-ignored) points at a keystore kept
// outside the repo. Without it (e.g. a fresh clone), release builds fall back to the debug key.
val keystoreProps = Properties().apply {
    val f = rootProject.file("keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "com.ipoanalyser.gmp"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.ipoanalyser.gmp"
        minSdk = 26
        targetSdk = 35
        versionCode = 2
        versionName = "1.0.1"
        buildConfigField("String", "API_BASE_URL", "\"${configValue("api.baseUrl.release", "https://ipo-gmp-api.onrender.com/")}\"")
        manifestPlaceholders["usesCleartextTraffic"] = "false"
    }

    signingConfigs {
        if (keystoreProps.getProperty("storeFile") != null) {
            create("release") {
                storeFile = file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            // 10.0.2.2 is the host machine from the Android emulator.
            buildConfigField("String", "API_BASE_URL", "\"${configValue("api.baseUrl.debug", "http://10.0.2.2:8000/")}\"")
            manifestPlaceholders["usesCleartextTraffic"] = "true"
        }
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
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
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.navigation.compose)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    debugImplementation(libs.androidx.compose.ui.tooling)

    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.play.services)

    // Home-screen widget (Jetpack Glance) refreshed in the background by WorkManager
    implementation(libs.glance.appwidget)
    implementation(libs.glance.material3)
    implementation(libs.work.runtime.ktx)

    implementation(platform(libs.firebase.bom))
    implementation(libs.firebase.messaging)
}
