/**
 * CarDigno - Spatial Diagnostic Schematic Renderer
 * Manipulates SVG vehicle chassis vector elements (#part-engine, #part-radiator, #part-intake)
 * and updates subsystem health rating bars based on dynamic health threshold rules.
 */

export class SchematicRenderer {
    constructor() {
        // SVG Element Cache
        this.partEngine = document.getElementById('part-engine');
        this.partRadiator = document.getElementById('part-radiator');
        this.partIntake = document.getElementById('part-intake');

        // Text & Progress Bar Elements
        this.thermalVal = document.getElementById('health-thermal-val');
        this.thermalBar = document.getElementById('health-thermal-bar');

        this.airVal = document.getElementById('health-air-val');
        this.airBar = document.getElementById('health-air-bar');

        this.overallVal = document.getElementById('health-overall-val');
        this.overallBar = document.getElementById('health-overall-bar');

        this.anomVal = document.getElementById('anom-score-val');
        this.anomBar = document.getElementById('anom-score-bar');

        this.overallPill = document.getElementById('overall-status-pill');
    }

    /**
     * Determines state class ('nominal' >= 80%, 'warning' 60-79%, 'critical' < 60%)
     * @param {number} healthPct 
     * @returns {string} 'nominal' | 'warning' | 'critical'
     */
    getHealthState(healthPct) {
        if (healthPct >= 80.0) return 'nominal';
        if (healthPct >= 60.0) return 'warning';
        return 'critical';
    }

    /**
     * Maps health state to hex color code.
     */
    getStateColor(state) {
        switch (state) {
            case 'nominal': return '#10b981'; // Green
            case 'warning': return '#f59e0b'; // Yellow
            case 'critical': return '#ef4444'; // Red
            default: return '#10b981';
        }
    }

    /**
     * Updates SVG schematic chassis fills and health bar indicators.
     * @param {Object} healthReport - ML & Subsystem Health evaluation object
     * @param {Array} dtcCodes - Active Diagnostic Trouble Codes list
     */
    updateSchematic(healthReport = {}, dtcCodes = []) {
        if (!healthReport) return;

        const thermalHealth = healthReport.thermal_health ?? 100.0;
        const airHealth = healthReport.air_intake_health ?? 100.0;
        const overallHealth = healthReport.overall_health ?? 100.0;
        const anomalyScore = healthReport.anomaly_score ?? 0.0;

        // 1. Update Thermal / Radiator SVG & Bar
        const thermalState = this.getHealthState(thermalHealth);
        this.updateSvgPart(this.partRadiator, thermalState);
        this.updateBarElement(this.thermalBar, this.thermalVal, thermalHealth, thermalState);

        // 2. Update Air Intake SVG & Bar
        const airState = this.getHealthState(airHealth);
        this.updateSvgPart(this.partIntake, airState);
        this.updateBarElement(this.airBar, this.airVal, airHealth, airState);

        // 3. Update Engine Block SVG (Combines overall & thermal health)
        const engineHealth = Math.min(thermalHealth, overallHealth);
        const engineState = this.getHealthState(engineHealth);
        this.updateSvgPart(this.partEngine, engineState);

        // 4. Update Overall Health Bar & Status Pill
        const overallState = this.getHealthState(overallHealth);
        this.updateBarElement(this.overallBar, this.overallVal, overallHealth, overallState);
        this.updateOverallPill(healthReport.status || 'HEALTHY', overallState);

        // 5. Update Anomaly Score Bar
        if (this.anomVal && this.anomBar) {
            this.anomVal.textContent = anomalyScore.toFixed(3);
            const anomPct = Math.min(100.0, anomalyScore * 100.0);
            this.anomBar.style.width = `${anomPct}%`;
            
            const anomState = anomalyScore >= 0.6 ? 'critical' : (anomalyScore >= 0.4 ? 'warning' : 'nominal');
            this.anomBar.className = `gauge-bar-fill ${anomState}`;
        }
    }

    /**
     * Updates an SVG element's class and inline fill color.
     */
    updateSvgPart(element, state) {
        if (!element) return;
        element.className.baseVal = `chassis-part ${state}`;
        element.setAttribute('fill', this.getStateColor(state));
    }

    /**
     * Updates progress bar fill and text percentage label.
     */
    updateBarElement(barElem, labelElem, value, state) {
        if (labelElem) {
            labelElem.textContent = `${value.toFixed(1)}%`;
        }
        if (barElem) {
            barElem.style.width = `${Math.max(0.0, Math.min(100.0, value))}%`;
            barElem.className = `gauge-bar-fill ${state}`;
        }
    }

    /**
     * Updates overall status pill badge styling.
     */
    updateOverallPill(statusText, state) {
        if (!this.overallPill) return;

        this.overallPill.textContent = statusText.toUpperCase();
        this.overallPill.className = `system-pill ${state === 'nominal' ? 'healthy' : state}`;
    }
}
