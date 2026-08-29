package app.protbot.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import app.protbot.core.Linking
import app.protbot.data.UsageRepository
import app.protbot.sync.SyncClientFactory
import com.google.mlkit.vision.barcode.BarcodeScanner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import kotlinx.coroutines.launch

/**
 * Scan the QR code the desktop app's Devices tab shows, to link this phone.
 *
 * CameraX for the feed, ML Kit's on-device barcode scanner to read it --
 * both new dependencies; everything else this module needed (Room, Work,
 * Compose itself) was already in use elsewhere. `core/linking.py`'s own
 * https App Link intent-filter (AndroidManifest.xml) already lets the stock
 * camera app open ProtBot; this is the "or scan from inside the app" path
 * STATUS.md names as the piece still missing.
 *
 * The payload itself is decoded by app.protbot.core.Linking.parsePayload,
 * tested without a camera or a device. This screen is the camera plumbing
 * around it, plus the network call to actually join once a code decodes --
 * neither of which can be exercised without one.
 */
@Composable
fun ScanScreen(onDone: () -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val scope = rememberCoroutineScope()

    var hasCameraPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    val requestPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted -> hasCameraPermission = granted }

    LaunchedEffect(Unit) {
        if (!hasCameraPermission) requestPermission.launch(Manifest.permission.CAMERA)
    }

    var status by remember {
        mutableStateOf("Point the camera at the code on your PC's Devices tab.")
    }
    // Set once a code decodes, so frames still arriving from the analyzer
    // while the join request is in flight are ignored -- ML Kit calls the
    // analyzer repeatedly while the camera runs, and a code held in frame
    // for even a second is many frames, not one.
    var handled by remember { mutableStateOf(false) }

    fun handleScanned(text: String) {
        if (handled) return
        when (val result = Linking.parsePayload(text)) {
            is Linking.Result.Failed -> status = result.reason
            is Linking.Result.Key -> {
                handled = true
                status = "Joining…"
                scope.launch {
                    val repository = UsageRepository.get(context)
                    var client = SyncClientFactory.create(context, repository)

                    // Registering (Device Sync, or right here) works without
                    // visiting that screen first -- scanning a link code is,
                    // in effect, the moment sync turns on for this phone if
                    // it has not already, exactly as registering is on the
                    // desktop app. Auto-register with the device model
                    // rather than forcing a detour through a second screen.
                    if (!client.enabled) {
                        status = "Registering this device…"
                        val name = android.os.Build.MODEL?.takeIf { it.isNotBlank() } ?: "Android"
                        val id = runCatching { client.register(name) }.getOrDefault("")
                        if (id.isEmpty()) {
                            status = "Could not register this device. Check your connection."
                            handled = false
                            return@launch
                        }
                        // register() only wrote the new id and token to
                        // SharedPreferences -- client's own HttpTransport had
                        // its bearer token fixed at construction, before
                        // registration, so it is still the empty one. Rebuild
                        // rather than reuse, or the join call below (the
                        // first authenticated request this flow makes) goes
                        // out with no Authorization header at all.
                        client = SyncClientFactory.create(context, repository)
                        status = "Joining…"
                    }

                    val ok = runCatching { client.joinLink(result.key) }.getOrDefault(false)
                    if (ok) {
                        onDone()
                    } else {
                        status = "That code has expired or already been used. Try again."
                        handled = false
                    }
                }
            }
        }
    }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onDone) { Text("Cancel") }
            Spacer(Modifier.width(8.dp))
            Text("Scan link code", style = MaterialTheme.typography.titleMedium)
        }
        HorizontalDivider()

        if (!hasCameraPermission) {
            Column(Modifier.fillMaxSize().padding(16.dp)) {
                Text(
                    "ProtBot needs the camera to scan the code. It is only used " +
                        "to read what is on screen right now; nothing is recorded " +
                        "or sent anywhere.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.height(12.dp))
                TextButton(onClick = { requestPermission.launch(Manifest.permission.CAMERA) }) {
                    Text("Grant camera access")
                }
            }
        } else {
            Box(Modifier.fillMaxSize()) {
                AndroidView(
                    modifier = Modifier.fillMaxSize(),
                    factory = { viewContext ->
                        val previewView = PreviewView(viewContext)
                        val providerFuture = ProcessCameraProvider.getInstance(viewContext)
                        val mainExecutor = ContextCompat.getMainExecutor(viewContext)

                        providerFuture.addListener({
                            val provider = providerFuture.get()

                            val preview = Preview.Builder().build().also {
                                it.setSurfaceProvider(previewView.surfaceProvider)
                            }

                            val scanner = BarcodeScanning.getClient(
                                BarcodeScannerOptions.Builder()
                                    .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                                    .build(),
                            )

                            // STRATEGY_KEEP_ONLY_LATEST: the analyzer must never
                            // fall behind and queue frames -- a stale frame's
                            // scan result would still be correct (decoding the
                            // same static code), but a growing queue on a slow
                            // decode is exactly how a preview starts stuttering.
                            val analysis = ImageAnalysis.Builder()
                                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                                .build()
                            analysis.setAnalyzer(mainExecutor) { imageProxy ->
                                analyzeFrame(imageProxy, scanner, ::handleScanned)
                            }

                            try {
                                provider.unbindAll()
                                provider.bindToLifecycle(
                                    lifecycleOwner,
                                    CameraSelector.DEFAULT_BACK_CAMERA,
                                    preview,
                                    analysis,
                                )
                            } catch (e: Exception) {
                                android.util.Log.e(TAG, "Could not bind the camera", e)
                            }
                        }, mainExecutor)

                        previewView
                    },
                )

                Text(
                    status,
                    color = Color.White,
                    textAlign = TextAlign.Center,
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .background(Color.Black.copy(alpha = 0.6f))
                        .padding(16.dp),
                )
            }
        }
    }
}

/**
 * One frame from the analyzer: decode it, hand any QR text found to
 * [onDecoded], and always close [imageProxy] -- CameraX stops delivering
 * new frames if a previous one is never closed.
 */
@OptIn(ExperimentalGetImage::class)
private fun analyzeFrame(imageProxy: ImageProxy, scanner: BarcodeScanner, onDecoded: (String) -> Unit) {
    val mediaImage = imageProxy.image
    if (mediaImage == null) {
        imageProxy.close()
        return
    }

    val image = InputImage.fromMediaImage(mediaImage, imageProxy.imageInfo.rotationDegrees)
    scanner.process(image)
        .addOnSuccessListener { barcodes ->
            val value = barcodes.firstNotNullOfOrNull { it.rawValue }
            if (value != null) onDecoded(value)
        }
        .addOnCompleteListener { imageProxy.close() }
}

private const val TAG = "ProtBotScan"
