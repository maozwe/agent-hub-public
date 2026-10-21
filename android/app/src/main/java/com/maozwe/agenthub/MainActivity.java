package com.maozwe.agenthub;

import android.annotation.SuppressLint;
import android.graphics.Color;
import android.content.Intent;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import androidx.activity.ComponentActivity;
import androidx.activity.OnBackPressedCallback;
import android.text.InputType;
import android.view.View;
import android.view.MotionEvent;
import android.webkit.CookieManager;
import android.webkit.SslErrorHandler;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.ByteArrayInputStream;
import java.util.Collections;
import android.Manifest;
import android.os.Build;
import android.content.pm.PackageManager;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;

public class MainActivity extends ComponentActivity {
    private static final int BACKGROUND = Color.rgb(23, 28, 32);
    private static final int MINT = Color.rgb(168, 219, 187);
    private LinearLayout root;
    private WebView web;
    private TextView status;
    private String origin;
    private boolean failed;
    private ActivityResultLauncher<String> notificationPermission;
    private ActivityResultLauncher<String> microphonePermission;
    private android.webkit.PermissionRequest pendingMicrophone;

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        microphonePermission = registerForActivityResult(new ActivityResultContracts.RequestPermission(), allowed -> {
            android.webkit.PermissionRequest request = pendingMicrophone; pendingMicrophone = null;
            if (request == null) return;
            if (allowed && web != null && ServerOrigin.allows(origin, request.getOrigin().toString()) && ServerOrigin.allows(origin, web.getUrl()))
                request.grant(new String[]{android.webkit.PermissionRequest.RESOURCE_AUDIO_CAPTURE});
            else request.deny();
        });
        notificationPermission = registerForActivityResult(new ActivityResultContracts.RequestPermission(), allowed -> {
            if (allowed) enablePush(); else pushMessage("אישור התראות נדחה. אפשר לשנות בהגדרות Android.");
        });
        PushClient.channel(this);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BACKGROUND);
        root.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        setContentView(root);
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override public void handleOnBackPressed() {navigateBack();}
        });
        origin = getPreferences(MODE_PRIVATE).getString("server", "");
        if (origin.isEmpty()) showSettings(); else openHub();
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private TextView text(String value, int size) {
        TextView label = new TextView(this);
        label.setText(value); label.setTextSize(size); label.setTextColor(Color.rgb(231, 237, 235));
        label.setPadding(dp(16), dp(10), dp(16), dp(10));
        return label;
    }

    private Button button(String value, View.OnClickListener action) {
        Button button = new Button(this);
        button.setText(value); button.setTextColor(MINT); button.setAllCaps(false);
        button.setMinHeight(dp(48)); button.setOnClickListener(action);
        return button;
    }

    private void clearScreen() {
        if (web != null) {
            root.removeView(web);web.stopLoading();web.destroy();web = null;
        }
        root.removeAllViews();
    }

    private void showSettings() {
        clearScreen();
        android.widget.ScrollView scroll = new android.widget.ScrollView(this);
        LinearLayout content = new LinearLayout(this);content.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(content);this.root.addView(scroll);
        LinearLayout root = content;
        root.addView(text(getString(R.string.app_with_version, BuildConfig.VERSION_NAME), 27));
        root.addView(text("מרכז החלטות · חיבור לשרת הפרטי", 17));
        root.addView(text("הפעילו Tailscale בטלפון ובמחשב, והדביקו את כתובת ה־HTTPS שמופיעה בקישור לטלפון בווב. המחשב והיישום צריכים להישאר פועלים.", 14));
        TextView label = text("כתובת שרת HTTPS", 14);root.addView(label);
        EditText address = new EditText(this);
        address.setId(View.generateViewId());label.setLabelFor(address.getId());
        address.setSingleLine(true);address.setText(origin);address.setTextColor(Color.WHITE);
        address.setHint("https://computer.example.ts.net");address.setHintTextColor(Color.GRAY);
        address.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        address.setLayoutDirection(View.LAYOUT_DIRECTION_LTR);
        address.setTextDirection(View.TEXT_DIRECTION_LTR);
        address.setPadding(dp(16), dp(12), dp(16), dp(12));root.addView(address);
        TextView error = text("", 13);error.setTextColor(Color.rgb(255, 170, 161));
        error.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        root.addView(button("שמירה וחיבור", view -> {
            try {
                String next = ServerOrigin.parse(address.getText().toString());
                if (!next.equals(origin) && PushClient.enabled(this)) {
                    error.setText("כבו קודם את הפוש לפני מעבר לשרת אחר.");return;
                }
                if (!next.equals(origin)) {CookieManager.getInstance().removeAllCookies(null);}
                origin = next;getPreferences(MODE_PRIVATE).edit().putString("server", origin).apply();
                openHub();
            } catch (IllegalArgumentException invalid) {error.setText(R.string.invalid_address);}
        }));
        if (!origin.isEmpty()) root.addView(button("חזרה לשרת השמור", view -> openHub()));
        root.addView(error);
        root.addView(text("פוש שולח דרך Google הודעה כללית בלבד. פרטי המשימה נשארים בשרת הפרטי.", 13));
        Button push = button(PushClient.enabled(this) ? "כיבוי התראות פוש" : "הפעלת התראות פוש", view -> {
            if (!BuildConfig.PUSH_CONFIGURED) {pushMessage("בנייה זו אינה מחוברת ל־Firebase.");return;}
            if (origin.isEmpty()) {pushMessage("שמרו קודם כתובת שרת.");return;}
            if (PushClient.enabled(this)) {
                PushClient.disable(this, success -> pushMessage(success ? "הפוש כובה" : "הכיבוי נכשל. בדקו חיבור לשרת ונסו שוב."));
            } else if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS);
            } else enablePush();
        });
        root.addView(push);
    }

    private void enablePush() {
        PushClient.enable(this, origin, success -> pushMessage(success ? "פוש הופעל. המחשב וה־Hub צריכים להישאר פועלים." : "הרישום נכשל. בדקו Tailscale והגדרות Firebase בשרת."));
    }
    private void pushMessage(String message) {
        runOnUiThread(() -> {
            if (isFinishing() || isDestroyed()) return;
            showSettings();android.widget.Toast.makeText(this, message, android.widget.Toast.LENGTH_LONG).show();
        });
    }

    @SuppressLint("SetJavaScriptEnabled") // The selected Hub uses JS; no native bridge or local-file access exists.
    private void openHub() {
        clearScreen();failed = false;
        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setOrientation(LinearLayout.HORIZONTAL);
        TextView title = text(getString(R.string.app_with_version, BuildConfig.VERSION_NAME), 15);
        toolbar.addView(title, new LinearLayout.LayoutParams(0, dp(54), 1));
        toolbar.addView(button("שרת", view -> showSettings()));
        toolbar.addView(button("רענון", view -> openHub()));root.addView(toolbar);
        status = text("מתחבר לשרת הפרטי…", 11);
        status.setTextColor(MINT);status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        root.addView(status);
        web = new WebView(this) {
            private float startX, startY;
            private boolean beganAtBottom;
            @Override public boolean dispatchTouchEvent(MotionEvent event) {
                if (event.getActionMasked() == MotionEvent.ACTION_DOWN) {
                    startX = event.getX();startY = event.getY();beganAtBottom = !canScrollVertically(1);
                }
                if (event.getPointerCount() != 1 || event.getActionMasked() == MotionEvent.ACTION_CANCEL) beganAtBottom = false;
                if (event.getActionMasked() == MotionEvent.ACTION_UP) {
                    boolean refresh = !canScrollVertically(1) && PullUpRefresh.matches(beganAtBottom,
                        startX, startY, event.getX(), event.getY(), dp(96));
                    beganAtBottom = false;
                    if (refresh) {
                        MotionEvent cancel = MotionEvent.obtain(event);cancel.setAction(MotionEvent.ACTION_CANCEL);
                        super.dispatchTouchEvent(cancel);cancel.recycle();
                        status.setText("מרענן את המסך…");post(() -> openHub());return true;
                    }
                }
                return super.dispatchTouchEvent(event);
            }
        };web.setBackgroundColor(BACKGROUND);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(false);
        settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setSafeBrowsingEnabled(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        web.setWebChromeClient(new android.webkit.WebChromeClient() {
            @Override public void onPermissionRequest(android.webkit.PermissionRequest request) {
                runOnUiThread(() -> {
                    if (!ServerOrigin.allows(origin,request.getOrigin().toString()) || !ServerOrigin.allows(origin,web.getUrl()) ||
                        !java.util.Arrays.asList(request.getResources()).contains(android.webkit.PermissionRequest.RESOURCE_AUDIO_CAPTURE)) {request.deny();return;}
                    if (pendingMicrophone != null) {request.deny();return;}
                    if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED)
                        request.grant(new String[]{android.webkit.PermissionRequest.RESOURCE_AUDIO_CAPTURE});
                    else {pendingMicrophone=request;microphonePermission.launch(Manifest.permission.RECORD_AUDIO);}
                });
            }
            @Override public void onPermissionRequestCanceled(android.webkit.PermissionRequest request) {
                if (pendingMicrophone==request) pendingMicrophone=null;
            }
        });
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (ServerOrigin.allows(origin, request.getUrl().toString())) return false;
                if (request.hasGesture() && request.getUrl().toString().equals("https://github.com/maozwe/agent-hub-public/releases")) {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(request.getUrl().toString())));return true;
                }
                status.setText("הקישור מחוץ לשרת שנבחר ונחסם.");return true;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                if (ServerOrigin.allows(origin, request.getUrl().toString())) return null;
                return new WebResourceResponse("text/plain", "UTF-8", 403, "Blocked",
                        Collections.emptyMap(), new ByteArrayInputStream(new byte[0]));
            }
            @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.cancel();connectionError("אימות תעודת השרת נכשל. בדקו את כתובת ה־HTTPS והתעודה במחשב.");
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) connectionError("אין חיבור לשרת. בדקו ש־Tailscale פעיל ושהמחשב והיישום פועלים.");
            }
            @Override public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                if (request.isForMainFrame()) connectionError(response.getStatusCode() == 403 ?
                        "השרת דחה את החיבור. בדקו שהטלפון מחובר לחשבון Tailscale המורשה." : "השרת החזיר שגיאה. נסו לרענן.");
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (!failed && ServerOrigin.allows(origin, url)) status.setText(getString(R.string.encrypted_connection, origin));
            }
        });
        root.addView(web, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1));
        web.loadUrl(origin + "/", Collections.singletonMap("X-Agent-Hub-Client-Version", BuildConfig.VERSION_NAME));
    }

    private void connectionError(String message) {
        failed = true;status.setText(message);status.setTextColor(Color.rgb(255, 170, 161));
    }

    private void navigateBack() {if (web != null && web.canGoBack()) web.goBack();else finish();}
    @Override protected void onDestroy() {clearScreen();super.onDestroy();}
}
