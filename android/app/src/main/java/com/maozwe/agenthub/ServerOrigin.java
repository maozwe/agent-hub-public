package com.maozwe.agenthub;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

/** Exact HTTPS origin boundary shared by configuration and WebView navigation. */
final class ServerOrigin {
    static String parse(String input) {
        try {
            URI uri = new URI(input.trim());
            if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null ||
                    uri.getRawUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null ||
                    !(uri.getRawPath().isEmpty() || uri.getRawPath().equals("/")) ||
                    uri.getPort() == 0 || uri.getPort() > 65535) {
                throw new IllegalArgumentException("Use an HTTPS server address without credentials, path or query");
            }
            int port = uri.getPort();
            return "https://" + uri.getHost().toLowerCase(Locale.ROOT) +
                    (port == -1 || port == 443 ? "" : ":" + port);
        } catch (URISyntaxException | NullPointerException error) {
            throw new IllegalArgumentException("Invalid HTTPS server address", error);
        }
    }

    static boolean allows(String origin, String url) {
        try {
            URI uri = new URI(url);
            String base = "https://" + uri.getHost() + (uri.getPort() == -1 ? "" : ":" + uri.getPort());
            return "https".equalsIgnoreCase(uri.getScheme()) && uri.getRawUserInfo() == null &&
                    uri.getHost() != null && parse(base).equals(origin);
        } catch (IllegalArgumentException | URISyntaxException error) {
            return false;
        }
    }
}
