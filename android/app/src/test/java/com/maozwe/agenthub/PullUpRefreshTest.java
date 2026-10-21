package com.maozwe.agenthub;
import org.junit.Test;
import static org.junit.Assert.*;

public class PullUpRefreshTest {
    @Test public void refreshesOnlyAnUpwardPullStartingAtBottom() {
        assertTrue(PullUpRefresh.matches(true, 100, 300, 110, 180, 96));
        assertFalse(PullUpRefresh.matches(false, 100, 300, 110, 180, 96));
        assertFalse(PullUpRefresh.matches(true, 100, 180, 110, 300, 96));
    }
    @Test public void ignoresTapsSmallMovesAndHorizontalSwipes() {
        assertFalse(PullUpRefresh.matches(true, 100, 300, 100, 300, 96));
        assertFalse(PullUpRefresh.matches(true, 100, 300, 100, 250, 96));
        assertFalse(PullUpRefresh.matches(true, 100, 300, 300, 180, 96));
    }
}
