/**
 * CarDigno - Main Dashboard Controller & Glue Layer
 * Orchestrates event-driven communication between WebSocket transport, Chart.js manager,
 * 2D SVG schematic renderer, and DOM UI renderer.
 */

import { TelemetrySocket } from './websocket_client.js';
import { TelemetryChartManager } from './chart_manager.js';
import { SchematicRenderer } from './schematic_render.js';
import { UIRenderer } from './ui_render.js';

class CarDignoDashboardApp {
    constructor() {
        // Instantiate decoupled modules
        this.socket = new TelemetrySocket('ws://127.0.0.1:8000/ws/telemetry');
        this.chartManager = new TelemetryChartManager('telemetry-chart', 20);
        this.schematicRenderer = new SchematicRenderer();
        this.uiRenderer = new UIRenderer();

        this.init();
    }

    init() {
        console.log('[CarDignoApp] Initializing Vehicle Intelligence Dashboard...');

        // 1. Bind Transport Lifecycle Events to UI Renderer
        this.socket.on('open', () => {
            this.uiRenderer.updateConnectionStatus('connected');
        });

        this.socket.on('close', () => {
            this.uiRenderer.updateConnectionStatus('disconnected');
        });

        this.socket.on('error', () => {
            this.uiRenderer.updateConnectionStatus('connecting');
        });

        // 2. Bind Incoming Telemetry Payloads to Renderers
        this.socket.on('message', (payload) => {
            if (!payload || payload.type !== 'telemetry_update') return;

            const telemetry = payload.telemetry || {};
            const features = payload.features || {};
            const health = payload.health || {};

            // A. Update Top Metric Gauges
            this.uiRenderer.updateGauges(telemetry, features, health);

            // B. Update DTC Alerts Panel
            this.uiRenderer.renderDTCAlerts(health.active_dtcs || []);

            // C. Update 2D Spatial Subsystem Schematic & Health Bars
            this.schematicRenderer.updateSchematic(health, health.active_dtcs || []);

            // D. Update Rolling 20-Sample Chart.js Plot
            if (features.RPM !== undefined && features.Coolant_Temp !== undefined) {
                const timestamp = telemetry.timestamp || (Date.now() / 1000);
                this.chartManager.updateChart(timestamp, features.RPM, features.Coolant_Temp);
            }
        });

        // 3. Connect to WebSocket Server
        this.socket.connect();
    }
}

// Instantiate dashboard application when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new CarDignoDashboardApp();
});
