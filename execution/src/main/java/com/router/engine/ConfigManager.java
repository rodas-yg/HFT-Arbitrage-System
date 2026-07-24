package com.router.engine;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Singleton configuration manager that parses config.json on boot.
 */
public class ConfigManager {

    private static ConfigManager instance = null;

    private String executionMode = "BINANCE"; // Default

    private ConfigManager() {
        try {
            String content = Files.readString(Path.of("config.json"));
            // Simple parsing to avoid extra dependencies like Gson/Jackson for a single field
            if (content.contains("\"execution_mode\"") && content.contains("\"KALSHI\"")) {
                executionMode = "KALSHI";
            } else if (content.contains("\"execution_mode\"") && content.contains("\"BINANCE\"")) {
                executionMode = "BINANCE";
            }
            System.out.println("[Java] ConfigManager loaded execution_mode: " + executionMode);
        } catch (IOException e) {
            System.out.println("[Java] config.json not found or readable, defaulting execution_mode to " + executionMode);
        }
    }

    public static synchronized ConfigManager getInstance() {
        if (instance == null) {
            instance = new ConfigManager();
        }
        return instance;
    }

    public String getExecutionMode() {
        return executionMode;
    }
}
