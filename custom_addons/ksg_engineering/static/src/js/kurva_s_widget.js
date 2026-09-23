/** @odoo-module **/
/**
 * Kurva-S Widget — Line chart Planned vs Actual per minggu.
 * Menarik data komputasi dinamis dari ksg.sales.project
 */

import { Component, onMounted, onWillUnmount, useRef, useState, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { loadJS } from "@web/core/assets";

export class KurvaSWidget extends Component {
    static template = xml`
        <div class="o_kurva_s_widget w-100">
            <div t-if="state.loading" class="text-muted p-3 text-center border rounded bg-light">
                <i class="fa fa-spinner fa-spin me-2"/> Memuat grafik Kurva-S...
            </div>
            <div t-if="!state.loading and !state.hasData" class="text-muted p-3 text-center border rounded bg-light">
                <i class="fa fa-line-chart me-2"/>
                Belum ada data Kalender Minggu. Generate Kalender Minggu pada tab sebelahnya agar Kurva-S muncul.
            </div>
            <canvas t-ref="canvas" t-att-style="(!state.loading and state.hasData) ? 'width: 100%; max-height: 400px;' : 'display: none;'"/>
        </div>
    `;
    static props = { ...standardFieldProps };

    setup() {
        this.canvasRef = useRef("canvas");
        this.chart = null;
        this.orm = useService("orm");
        this.state = useState({ hasData: false, loading: true });

        onMounted(() => this.renderChart());
        onWillUnmount(() => {
            if (this.chart) {
                this.chart.destroy();
            }
        });
    }

    async renderChart() {
        const projectId = this.props.record.data.id;
        if (!projectId) {
            this.state.loading = false;
            return;
        }

        let chartData = null;
        try {
            chartData = await this.orm.call(
                "ksg.sales.project",
                "get_kurva_s_data",
                [projectId]
            );
        } catch (e) {
            console.warn("Kurva-S: Could not fetch data", e);
            this.state.loading = false;
            return;
        }

        this.state.loading = false;

        if (!chartData || !chartData.hasData) {
            this.state.hasData = false;
            return;
        }

        this.state.hasData = true;
        
        // Wait for next tick so canvas is rendered in DOM
        await new Promise((r) => setTimeout(r, 50));

        const canvas = this.canvasRef.el;
        if (!canvas) return;

        if (this.chart) {
            this.chart.destroy();
        }

        // Load Chart.js if not available globally
        if (typeof Chart === "undefined") {
            try {
                await loadJS("/web/static/lib/Chart/Chart.js");
            } catch {
                try {
                    await loadJS("/web/static/lib/chart/chart.umd.js");
                } catch {
                    console.warn("Kurva-S: Chart.js not found");
                    return;
                }
            }
        }

        if (typeof Chart === "undefined") return;

        this.chart = new Chart(canvas, {
            type: "line",
            data: {
                labels: chartData.labels,
                datasets: [
                    {
                        label: "Rencana (Kumulatif)",
                        data: chartData.planned,
                        borderColor: "#3b82f6",
                        backgroundColor: "rgba(59, 130, 246, 0.1)",
                        fill: false,
                        tension: 0.4,
                        pointRadius: 4,
                        borderWidth: 2,
                    },
                    {
                        label: "Realisasi (Kumulatif)",
                        data: chartData.actual,
                        borderColor: "#22c55e",
                        backgroundColor: "rgba(34, 197, 94, 0.1)",
                        fill: false,
                        tension: 0.4,
                        pointRadius: 4,
                        borderWidth: 2,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: { display: false },
                    legend: { position: "bottom" },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                    },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        title: { display: true, text: "Progress (%)" },
                    },
                    x: {
                        title: { display: true, text: "Periode Minggu" },
                    },
                },
            },
        });
    }
}

registry.category("fields").add("kurva_s_chart", {
    component: KurvaSWidget,
});
