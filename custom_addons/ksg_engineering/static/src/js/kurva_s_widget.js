/** @odoo-module **/
/**
 * Kurva-S Widget — Line chart Planned vs Actual per minggu.
 * Ref: FR-010
 */

import { Component, onMounted, onWillUnmount, useRef, useState, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { loadJS } from "@web/core/assets";

export class KurvaSWidget extends Component {
    static template = xml`
        <div class="o_kurva_s_widget">
            <div t-if="state.loading" class="text-muted p-3 text-center">
                Memuat grafik...
            </div>
            <div t-if="!state.loading and !state.hasData" class="text-muted p-3 text-center border rounded bg-light">
                Belum ada data Kurva-S. Data akan muncul setelah Laporan Mingguan dibuat.
            </div>
            <canvas t-ref="canvas" t-att-style="state.hasData ? 'max-height: 400px;' : 'display: none;'"/>
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

        let weeklyReports = [];
        try {
            weeklyReports = await this.orm.searchRead(
                "ksg.engineering.weekly.report",
                [["project_id", "=", projectId]],
                ["periode_minggu_id", "planned_progress", "actual_progress"],
                { order: "periode_minggu_id asc" }
            );
        } catch (e) {
            console.warn("Kurva-S: Could not fetch weekly reports", e);
            this.state.loading = false;
            return;
        }

        this.state.loading = false;

        if (!weeklyReports.length) {
            this.state.hasData = false;
            return;
        }

        this.state.hasData = true;

        const labels = weeklyReports.map(
            (wr) => wr.periode_minggu_id ? wr.periode_minggu_id[1] : "?"
        );
        const planned = weeklyReports.map((wr) => wr.planned_progress || 0);
        const actual = weeklyReports.map((wr) => wr.actual_progress || 0);

        // Cumulative
        const plannedCum = [];
        const actualCum = [];
        let sumP = 0, sumA = 0;
        for (let i = 0; i < planned.length; i++) {
            sumP += planned[i];
            sumA += actual[i];
            plannedCum.push(parseFloat(sumP.toFixed(2)));
            actualCum.push(parseFloat(sumA.toFixed(2)));
        }

        // Wait for next tick so canvas is rendered
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
                labels,
                datasets: [
                    {
                        label: "Rencana (Kumulatif)",
                        data: plannedCum,
                        borderColor: "#3b82f6",
                        backgroundColor: "rgba(59, 130, 246, 0.1)",
                        fill: false,
                        tension: 0.3,
                        pointRadius: 4,
                    },
                    {
                        label: "Realisasi (Kumulatif)",
                        data: actualCum,
                        borderColor: "#22c55e",
                        backgroundColor: "rgba(34, 197, 94, 0.1)",
                        fill: false,
                        tension: 0.3,
                        pointRadius: 4,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    title: { display: true, text: "Kurva-S: Rencana vs Realisasi" },
                    legend: { position: "bottom" },
                },
                scales: {
                    y: {
                        beginAtZero: true,
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
