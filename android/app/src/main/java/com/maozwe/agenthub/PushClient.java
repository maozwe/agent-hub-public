package com.maozwe.agenthub;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.SharedPreferences;
import com.google.firebase.messaging.FirebaseMessaging;
import java.net.URL;
import javax.net.ssl.HttpsURLConnection;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONObject;

final class PushClient {
    interface Result { void done(boolean success); }
    static SharedPreferences prefs(Context context) { return context.getSharedPreferences("push", Context.MODE_PRIVATE); }
    static boolean enabled(Context context) { return prefs(context).getBoolean("enabled", false); }
    static void channel(Context context) {
        context.getSystemService(NotificationManager.class).createNotificationChannel(
            new NotificationChannel("hub_updates", "עדכונים מ־Agent Hub", NotificationManager.IMPORTANCE_DEFAULT));
    }
    static void enable(Context context, String origin, Result result) {
        channel(context);
        FirebaseMessaging.getInstance().getToken().addOnCompleteListener(task -> {
            if (!task.isSuccessful()) { result.done(false); return; }
            register(context, origin, task.getResult(), success -> {
                if (success) {
                    prefs(context).edit().putBoolean("enabled", true).putString("origin", origin).apply();
                    FirebaseMessaging.getInstance().setAutoInitEnabled(true);
                }
                result.done(success);
            });
        });
    }
    static void disable(Context context, Result result) {
        register(context, prefs(context).getString("origin", ""), null, success -> {
            if (success) {
                prefs(context).edit().putBoolean("enabled", false).apply();
                FirebaseMessaging.getInstance().setAutoInitEnabled(false);
                FirebaseMessaging.getInstance().deleteToken();
            }
            result.done(success);
        });
    }
    static void refresh(Context context, String token) {
        if (enabled(context)) register(context, prefs(context).getString("origin", ""), token, success -> {});
    }
    private static HttpsURLConnection connect(String address) throws Exception {
        HttpsURLConnection connection = (HttpsURLConnection)new URL(address).openConnection();
        connection.setConnectTimeout(10000);connection.setReadTimeout(10000);
        connection.setInstanceFollowRedirects(false);
        return connection;
    }
    static void register(Context context, String address, String token, Result result) {
        new Thread(() -> {
            boolean success = false;
            try {
                String origin = ServerOrigin.parse(address);
                String device = prefs(context).getString("device", "");
                if (device.isEmpty()) {
                    device = UUID.randomUUID().toString();prefs(context).edit().putString("device", device).apply();
                }
                HttpsURLConnection page = connect(origin + "/");
                String html;
                try {
                    if (page.getResponseCode() != 200) throw new IllegalStateException();
                    try (java.io.InputStream input = page.getInputStream()) {
                        java.io.ByteArrayOutputStream buffer = new java.io.ByteArrayOutputStream();
                        byte[] chunk = new byte[4096];int count;
                        while ((count = input.read(chunk)) != -1) {
                            buffer.write(chunk, 0, count);
                            if (buffer.size() > 262144) throw new IllegalStateException();
                        }
                        html = buffer.toString("UTF-8");
                    }
                } finally { page.disconnect(); }
                Matcher csrf = Pattern.compile("name=\"hub-csrf\" content=\"([A-Za-z0-9_-]{20,100})\"").matcher(html);
                if (!csrf.find()) throw new IllegalStateException();
                JSONObject body = new JSONObject().put("action", "push_register").put("device", device)
                    .put("token", token == null ? JSONObject.NULL : token);
                HttpsURLConnection post = connect(origin + "/api/action");
                try {
                    post.setRequestMethod("POST");post.setDoOutput(true);
                    post.setRequestProperty("Origin", origin);
                    post.setRequestProperty("X-Hub-CSRF", csrf.group(1));
                    post.setRequestProperty("Content-Type", "application/json");
                    byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                    post.setFixedLengthStreamingMode(bytes.length);
                    try (java.io.OutputStream output = post.getOutputStream()) {output.write(bytes);}
                    success = post.getResponseCode() == 200;
                } finally {post.disconnect();}
            } catch (Exception ignored) { /* Do not log device tokens or server content. */ }
            result.done(success);
        }, "hub-push-register").start();
    }
}
