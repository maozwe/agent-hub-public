package com.maozwe.agenthub;

final class PullUpRefresh {
    static boolean matches(boolean beganAtBottom, float startX, float startY,
                           float endX, float endY, float threshold) {
        float upward = startY - endY;
        return beganAtBottom && upward >= threshold && upward > 2 * Math.abs(endX - startX);
    }
}
