package com.maozwe.agenthub;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

public class HubMessagingService extends FirebaseMessagingService {
    @Override public void onNewToken(String token) { PushClient.refresh(this, token); }
    @Override public void onMessageReceived(RemoteMessage message) {
        if (!PushClient.enabled(this)) return;
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return;
        PushClient.channel(this);
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification notification = new Notification.Builder(this, "hub_updates")
            .setSmallIcon(R.drawable.ic_hub).setContentTitle("Agent Hub")
            .setContentText("יש עדכון במרכז ההחלטות. פתחו את Agent Hub לצפייה.")
            .setContentIntent(open).setAutoCancel(true).build();
        getSystemService(NotificationManager.class).notify("hub-update", 1, notification);
    }
}
