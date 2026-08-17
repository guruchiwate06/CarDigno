/**
 * CarDigno - Chart.js Time-Series Manager
 * Initializes and updates dual-axis line chart for Engine RPM and Coolant Temperature.
 */

export class TelemetryChartManager {
    /**
     * @param {string} canvasId - HTML Canvas element ID (default: 'telemetry-chart')
     * @param {number} maxSamples - Rolling window size (default: 20)
     */
    constructor(canvasId = 'telemetry-chart', maxSamples = 20) {
        this.canvasId = canvasId;
        this.maxSamples = maxSamples;
        this.chart = null;
        
        this.initChart();
    }

    /**
     * Initializes Chart.js instance with dual Y-axes and dark theme styling.
     */
    initChart() {
        const ctx = document.getElementById(this.canvasId);
        if (!ctx) {
            console.error(`[ChartManager] Canvas element '#${this.canvasId}' not found.`);
            return;
        }

        this.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Engine RPM',
                        data: [],
                        borderColor: '#38bdf8', // Cyan/Blue
                        backgroundColor: 'rgba(56, 189, 248, 0.1)',
                        borderWidth: 2.5,
                        fill: true,
                        tension: 0.35,
                        yAxisID: 'yRPM',
                        pointRadius: 3,
                        pointHoverRadius: 6,
                    },
                    {
                        label: 'Coolant Temp (°C)',
                        data: [],
                        borderColor: '#ef4444', // Red
                        backgroundColor: 'rgba(239, 68, 68, 0.08)',
                        borderWidth: 2.5,
                        fill: true,
                        tension: 0.35,
                        yAxisID: 'yTemp',
                        pointRadius: 3,
                        pointHoverRadius: 6,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: {
                    duration: 300 // Smooth fast updates
                },
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                        labels: {
                            color: '#94a3b8',
                            font: { family: 'Inter', size: 12, weight: '600' },
                            usePointStyle: true,
                            padding: 16,
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(15, 23, 42, 0.9)',
                        titleColor: '#f8fafc',
                        bodyColor: '#cbd5e1',
                        borderColor: 'rgba(255, 255, 255, 0.1)',
                        borderWidth: 1,
                        padding: 10,
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.04)' },
                        ticks: { color: '#64748b', font: { family: 'Inter', size: 11 } }
                    },
                    yRPM: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        min: 0,
                        max: 6000,
                        title: {
                            display: true,
                            text: 'Engine Speed (RPM)',
                            color: '#38bdf8',
                            font: { family: 'Inter', size: 11, weight: '600' }
                        },
                        grid: { color: 'rgba(255, 255, 255, 0.04)' },
                        ticks: { color: '#94a3b8' }
                    },
                    yTemp: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        min: 40,
                        max: 130,
                        title: {
                            display: true,
                            text: 'Coolant Temp (°C)',
                            color: '#ef4444',
                            font: { family: 'Inter', size: 11, weight: '600' }
                        },
                        grid: { drawOnChartArea: false }, // Avoid duplicate gridlines
                        ticks: { color: '#94a3b8' }
                    }
                }
            }
        });
    }

    /**
     * Updates rolling window dataset with new timestamped metric values.
     * @param {number} timestamp - Unix timestamp in seconds
     * @param {number} rpm - Engine RPM value
     * @param {number} temp - Coolant Temperature in °C
     */
    updateChart(timestamp, rpm, temp) {
        if (!this.chart) return;

        // Format timestamp HH:MM:SS
        const timeStr = new Date(timestamp * 1000).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });

        const labels = this.chart.data.labels;
        const rpmData = this.chart.data.datasets[0].data;
        const tempData = this.chart.data.datasets[1].data;

        labels.push(timeStr);
        rpmData.push(rpm);
        tempData.push(temp);

        // Enforce rolling window limit
        if (labels.length > this.maxSamples) {
            labels.shift();
            rpmData.shift();
            tempData.shift();
        }

        this.chart.update('none'); // Update without full redraw animation lag
    }
}
