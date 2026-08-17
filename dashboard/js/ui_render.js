/**
 * CarDigno - DOM & Gauge UI Renderer
 * Handles HTML element updates for metric cards, status indicators, and DTC diagnostic alerts.
 */

export class UIRenderer {
    constructor() {
        // Connection status elements
        this.statusDot = document.getElementById('status-dot');
        this.statusText = document.getElementById('status-text');

        // RPM Card
        this.valRpm = document.getElementById('val-rpm');
        this.emaRpm = document.getElementById('ema-rpm');
        this.barRpm = document.getElementById('bar-rpm');

        // Coolant Temp Card
        this.valTemp = document.getElementById('val-temp');
        this.emaTemp = document.getElementById('ema-temp');
        this.maxTemp = document.getElementById('max-temp');
        this.barTemp = document.getElementById('bar-temp');

        // MAF Card
        this.valMaf = document.getElementById('val-maf');
        this.emaMaf = document.getElementById('ema-maf');
        this.ratioAir = document.getElementById('ratio-air');
        this.barMaf = document.getElementById('bar-maf');

        // Fuel Card
        this.valFuel = document.getElementById('val-fuel');
        this.barFuel = document.getElementById('bar-fuel');

        // DTC List Container
        this.dtcList = document.getElementById('dtc-list');
    }

    /**
     * Updates header WebSocket connection status indicator.
     * @param {string} state - 'connected' | 'disconnected' | 'connecting'
     */
    updateConnectionStatus(state) {
        if (!this.statusDot || !this.statusText) return;

        this.statusDot.className = `status-dot ${state}`;

        switch (state) {
            case 'connected':
                this.statusText.textContent = 'Live (10 Hz)';
                break;
            case 'connecting':
                this.statusText.textContent = 'Connecting...';
                break;
            case 'disconnected':
            default:
                this.statusText.textContent = 'Disconnected';
                break;
        }
    }

    /**
     * Updates top row gauge metric cards.
     * @param {Object} telemetry - Single metric payload or vehicle snapshot
     * @param {Object} features - 10-second rolling feature vector
     * @param {Object} health - ML Subsystem health evaluation
     */
    updateGauges(telemetry = {}, features = {}, health = {}) {
        // 1. Engine RPM Gauge
        const rpm = features.RPM ?? (telemetry.metric_name === 'RPM' ? telemetry.decoded_value : null);
        if (rpm !== null && rpm !== undefined) {
            if (this.valRpm) this.valRpm.textContent = rpm.toFixed(1);
            if (this.emaRpm) this.emaRpm.textContent = (features.rpm_ema ?? rpm).toFixed(1);
            if (this.barRpm) {
                const rpmPct = Math.min(100, (rpm / 7000.0) * 100);
                this.barRpm.style.width = `${rpmPct}%`;
                this.barRpm.className = `gauge-bar-fill ${rpm >= 5500 ? 'warning' : 'nominal'}`;
            }
        }

        // 2. Coolant Temperature Gauge
        const temp = features.Coolant_Temp ?? (telemetry.metric_name === 'Coolant_Temp' ? telemetry.decoded_value : null);
        if (temp !== null && temp !== undefined) {
            if (this.valTemp) this.valTemp.textContent = temp.toFixed(1);
            if (this.emaTemp) this.emaTemp.textContent = (features.temp_ema ?? temp).toFixed(1);
            if (this.maxTemp) this.maxTemp.textContent = (features.temp_max_10s ?? temp).toFixed(1);
            if (this.barTemp) {
                const tempPct = Math.min(100, Math.max(0, ((temp - 40) / (120 - 40)) * 100));
                this.barTemp.style.width = `${tempPct}%`;
                const state = temp >= 115 ? 'critical' : (temp >= 100 ? 'warning' : 'nominal');
                this.barTemp.className = `gauge-bar-fill ${state}`;
            }
        }

        // 3. Mass Air Flow Gauge
        const maf = features.MAF ?? (telemetry.metric_name === 'MAF' ? telemetry.decoded_value : null);
        if (maf !== null && maf !== undefined) {
            if (this.valMaf) this.valMaf.textContent = maf.toFixed(2);
            if (this.emaMaf) this.emaMaf.textContent = (features.maf_ema ?? maf).toFixed(2);
            if (this.ratioAir) this.ratioAir.textContent = (features.air_intake_ratio ?? 0.004).toFixed(5);
            if (this.barMaf) {
                const mafPct = Math.min(100, (maf / 60.0) * 100);
                this.barMaf.style.width = `${mafPct}%`;
                const state = (features.air_intake_ratio > 0.012 || features.air_intake_ratio < 0.0015) ? 'warning' : 'nominal';
                this.barMaf.className = `gauge-bar-fill ${state}`;
            }
        }

        // 4. Fuel Level Gauge
        const fuel = features.Fuel_Level ?? (telemetry.metric_name === 'Fuel_Level' ? telemetry.decoded_value : null);
        if (fuel !== null && fuel !== undefined) {
            if (this.valFuel) this.valFuel.textContent = fuel.toFixed(1);
            if (this.barFuel) {
                this.barFuel.style.width = `${Math.min(100, Math.max(0, fuel))}%`;
                const state = fuel <= 15 ? 'critical' : (fuel <= 30 ? 'warning' : 'nominal');
                this.barFuel.className = `gauge-bar-fill ${state}`;
            }
        }
    }

    /**
     * Renders Diagnostic Trouble Code (DTC) alert cards inside #dtc-list.
     * @param {Array} activeDTCs - List of active DTC dictionaries
     */
    renderDTCAlerts(activeDTCs = []) {
        if (!this.dtcList) return;

        if (!activeDTCs || activeDTCs.length === 0) {
            this.dtcList.innerHTML = `
                <div class="dtc-empty">
                    <span style="font-size: 2rem;">✔</span>
                    <span>All vehicle subsystems operating nominally. No active DTCs.</span>
                </div>
            `;
            return;
        }

        let html = '';
        activeDTCs.forEach(dtc => {
            const isCritical = dtc.severity === 'CRITICAL';
            const cardClass = isCritical ? 'dtc-card critical' : 'dtc-card';
            const badgeClass = isCritical ? 'dtc-badge critical' : 'dtc-badge warning';

            html += `
                <div class="${cardClass}">
                    <div class="dtc-card-header">
                        <span class="dtc-code">▶ [${dtc.code}] ${dtc.subsystem} Subsystem</span>
                        <span class="${badgeClass}">${dtc.severity}</span>
                    </div>
                    <div class="dtc-desc">${dtc.description}</div>
                    <div class="dtc-action">💡 Action: ${dtc.recommended_action}</div>
                </div>
            `;
        });

        this.dtcList.innerHTML = html;
    }
}
