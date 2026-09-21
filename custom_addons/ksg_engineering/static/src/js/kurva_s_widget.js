/** @odoo-module **/
/**
 * Kurva-S Widget — Line chart Planned vs Actual per minggu.
 *
 * Menggunakan Chart.js bawaan Odoo untuk menampilkan chart
 * pada tab Kurva-S di form project.
 *
 * Ref: FR-010
 */

import { Component, onMounted, onWillUnmount, useRef, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class KurvaSWidget extends Component {
    static template = xml`
        <div class="o_kurva_s_widget">
            <canvas t-ref="canvas" style="max-height: 400px;"/>
        </div>
    `;
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.canvasRef = useRef("canvas");
        this.chart = null;
        this.orm = useService("orm");

        onMounted(() => this.renderChart());
        onWillUnmount(() => {
            if (this.chart) {
                this.chart.destroy();
            }
        });
    }

    async renderChart() {
        const projectId = this.props.record.data.id;
        if (!projectId) return;

        // Fetch weekly report data
        const weeklyReports = await this.orm.searchRead(
            "ksg.engineering.weekly.report",
            [["project_id", "=", projectId]],
            ["periode_minggu_id", "planned_progress", "actual_progress"],
            { order: "periode_minggu_id asc" }
        );

        if (!weeklyReports.length) return;

        const labels = weeklyReports.map(
            (wr) => `W${wr.periode_minggu_id ? wr.periode_minggu_id[1] : "?"}`
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
            plannedCum.push(sumP);
            actualCum.push(sumA);
        }

        const canvas = this.canvasRef.el;
        if (!canvas) return;

        if (this.chart) {
            this.chart.destroy();
        }

        this.chart = new Chart(canvas, {
            type: "line",
            data: {
                labels: labels,
                datasets: [
                    {
                        label: "Planned (Kumulatif)",
                        data: plannedCum,
                        borderColor: "#3b82f6",
                        backgroundColor: "rgba(59, 130, 246, 0.1)",
                        fill: false,
                        tension: 0.3,
                    },
                    {
                        label: "Actual (Kumulatif)",
                        data: actualCum,
                        borderColor: "#22c55e",
                        backgroundColor: "rgba(34, 197, 94, 0.1)",
                        fill: false,
                        tension: 0.3,
                    },
                ],
            },
            options: {
                responsive: true,
                plugins: {
                    title: {
                        display: true,
                        text: "Kurva-S: Planned vs Actual",
                    },
                    legend: {
                        position: "bottom",
                    },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: "Progress (%)",
                        },
                    },
                    x: {
                        title: {
                            display: true,
                            text: "Minggu",
                        },
                    },
                },
            },
        });
    }
}

registry.category("fields").add("kurva_s_chart", {
    component: KurvaSWidget,
});
