plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

android {
    namespace = "io.github.dylanneve1.iosonpixel"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.witherblitz.iosoneverything.gpulab"
        minSdk = 34
        targetSdk = 36
        versionCode = 4
        versionName = "0.0.1"
        testInstrumentationRunner = "io.github.dylanneve1.iosonpixel.DeviceChecks"
        ndk { abiFilters += "arm64-v8a" }
    }


    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        // QEMU ships as an executable named lib*.so; it must be extracted to
        // nativeLibraryDir to be exec()able, so keep legacy (extracted) packaging.
        jniLibs.useLegacyPackaging = true
        // Preserve exact native payloads from the device-qualified v5 APK.
        jniLibs.keepDebugSymbols += "**/*.so"
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"
        buildPython(rootProject.file("../python-env/Scripts/python.exe").absolutePath)
        pip {
            install("pyasn1==0.6.1")
            install("pyasn1-modules==0.4.2")
        }
    }
}

dependencies {
    // JVM unit tests only (app/src/test); nothing here ships in the APK.
    testImplementation("junit:junit:4.13.2")
    // android.jar's org.json is stubs that throw in JVM tests; the real one for InstallMigration.
    testImplementation("org.json:json:20240303")
}
