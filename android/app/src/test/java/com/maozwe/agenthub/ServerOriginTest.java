package com.maozwe.agenthub;

import org.junit.Test;
import static org.junit.Assert.*;

public class ServerOriginTest {
    @Test public void canonicalizesAnHttpsOrigin() {
        assertEquals("https://host.ts.net", ServerOrigin.parse(" https://HOST.ts.net:443/ "));
        assertTrue(ServerOrigin.allows("https://host.ts.net", "https://host.ts.net/api/status"));
        assertTrue(ServerOrigin.allows("https://host.ts.net", "https://host.ts.net:443/#tasks-section"));
    }
    @Test public void rejectsUnsafeConfiguration() {
        for (String url : new String[]{"http://host", "file:///x", "javascript:alert(1)",
                "https://user:pass@host", "https://host/path", "https://host/?token=x", "https://host/#x", "https://host:0"}) {
            assertThrows(url, IllegalArgumentException.class, () -> ServerOrigin.parse(url));
        }
    }
    @Test public void blocksOriginConfusionAndExternalSchemes() {
        for (String url : new String[]{"https://host.ts.net.evil.test/", "http://host.ts.net/",
                "https://host.ts.net@evil.test/", "https://host.ts.net:444/", "//host.ts.net/",
                "file:///data/data/x", "content://x", "javascript:alert(1)", "intent://x", "https://host.ts.net\\@evil.test/"}) {
            assertFalse(url, ServerOrigin.allows("https://host.ts.net", url));
        }
    }
}
