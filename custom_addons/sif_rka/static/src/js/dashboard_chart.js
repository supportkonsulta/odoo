/** @odoo-module **/
import { Component, useState, onWillStart, onMounted, useRef, useExternalListener } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";

/**
 * RKA Bar Chart - Client Action
 *
 * Menampilkan diagram batang interaktif dengan:
 * - Dua batang per bulan: Orange (Realisasi) & Biru (Anggaran)
 * - Tooltip hover detail nominal
 * - Filter per COA
 * - Klik batang → detail bulan
 */
class SifRkaBarChartAction extends Component {
    static template = "sif_rka.BarChartAction";
    static props = ["*"];
    static chart = null;

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.canvasRef = useRef("chartCanvas");

        this.state = useState({
            isLoading: true,
            error: false,
            labels: [],
            budgetData: [],
            realisasiData: [],
            coaOptions: [],
            selectedCoa: "",
            tahun: new Date().getFullYear().toString(),
        });

        onWillStart(async () => {
            // Load Chart.js library dulu
            await loadBundle("web.chartjs_lib");

            // Ambil params dari action props (tahun dikirim dari action_open_monthly_diagram)
            const params = this.props.action?.params || {};
            if (params.tahun) {
                this.state.tahun = params.tahun;
            }
            await this._loadCoaOptions();
            await this._loadChartData();
        });

        onMounted(() => {
            setTimeout(() => this._renderChart(), 300);
        });

        // Event listener untuk resize window
        useExternalListener(window, 'resize', () => {
            this._renderChart();
        });
    }

    /**
     * Helper: format number ke format Rupiah
     */
    _formatRupiah(value) {
        if (!value && value !== 0) return "Rp 0";
        return "Rp " + Number(value).toLocaleString("id-ID");
    }

    /**
     * Helper: format angka untuk sumbu Y (compact)
     */
    _formatCompact(value) {
        if (!value && value !== 0) return "0";
        const abs = Math.abs(value);
        if (abs >= 1000000000000) {
            return "Rp " + (value / 1000000000000).toFixed(2) + " T";
        }
        if (abs >= 1000000000) {
            return "Rp " + (value / 1000000000).toFixed(1) + " M";
        }
        if (abs >= 1000000) {
            return "Rp " + (value / 1000000).toFixed(0) + " Jt";
        }
        if (abs >= 1000) {
            return "Rp " + (value / 1000).toFixed(0) + " Rb";
        }
        return "Rp " + value;
    }

    async _loadCoaOptions() {
        try {
            const coas = await this.orm.searchRead(
                "sif.coa",
                [],
                ["id", "code", "name", "display_name"],
                { order: "code asc", limit: 500 }
            );
            this.state.coaOptions = [
                { id: "", display_name: "-- Semua COA --" },
                ...coas.map((c) => ({
                    id: String(c.id),
                    display_name: c.display_name || `[${c.code}] ${c.name}`,
                })),
            ];
        } catch (e) {
            console.warn("Gagal memuat COA:", e);
            this.state.coaOptions = [{ id: "", display_name: "-- Semua COA --" }];
        }
    }

    async _loadChartData() {
        this.state.isLoading = true;
        this.state.error = false;

        try {
            const tahun = this.state.tahun;
            let domain = [["rka_id.tahun", "=", tahun]];
            if (this.state.selectedCoa) {
                domain.push(["rka_id.account_id", "=", parseInt(this.state.selectedCoa)]);
            }

            const monthNames = [
                "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
                "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
            ];

            const months = await this.orm.searchRead(
                "sif.rka.budget.month",
                domain,
                ["month", "budget_amount", "realisasi"],
                { order: "month asc" }
            );

            // Init all months
            const monthMap = {};
            for (let i = 1; i <= 12; i++) {
                const key = String(i).padStart(2, "0");
                monthMap[key] = {
                    month: key,
                    label: monthNames[i - 1],
                    budget: 0,
                    realisasi: 0,
                };
            }

            // Aggregate by month
            for (const m of months) {
                if (monthMap[m.month]) {
                    monthMap[m.month].budget += m.budget_amount || 0;
                    monthMap[m.month].realisasi += m.realisasi || 0;
                }
            }

            const labels = [];
            const budgetData = [];
            const realisasiData = [];

            for (let i = 1; i <= 12; i++) {
                const key = String(i).padStart(2, "0");
                labels.push(monthMap[key].label);
                budgetData.push(monthMap[key].budget);
                realisasiData.push(monthMap[key].realisasi);
            }

            this.state.labels = labels;
            this.state.budgetData = budgetData;
            this.state.realisasiData = realisasiData;
            this.state.isLoading = false;

            // Render chart after DOM ready
            setTimeout(() => this._renderChart(), 100);
        } catch (e) {
            console.error("Gagal memuat data chart:", e);
            this.state.error = true;
            this.state.isLoading = false;
        }
    }

    _renderChart() {
        const canvas = this.canvasRef.el;
        if (!canvas) return;

        const ctx = canvas.getContext("2d");

        // Destroy existing chart
        if (SifRkaBarChartAction.chart) {
            SifRkaBarChartAction.chart.destroy();
            SifRkaBarChartAction.chart = null;
        }

        if (!this.state.labels || this.state.labels.length === 0) return;

        const self = this;
        const formatRupiah = (v) => this._formatRupiah(v);
        const formatCompact = (v) => this._formatCompact(v);

        SifRkaBarChartAction.chart = new Chart(ctx, {
            type: "bar",
            data: {
                labels: this.state.labels,
                datasets: [
                    {
                        label: "Anggaran / Pendapatan",
                        data: this.state.budgetData,
                        backgroundColor: "rgba(41, 98, 255, 0.85)",
                        borderColor: "rgba(41, 98, 255, 1)",
                        borderWidth: 1,
                        borderRadius: 4,
                        barPercentage: 0.35,
                        categoryPercentage: 0.7,
                    },
                    {
                        label: "Realisasi / Pengeluaran",
                        data: this.state.realisasiData,
                        backgroundColor: "rgba(255, 159, 0, 0.85)",
                        borderColor: "rgba(255, 159, 0, 1)",
                        borderWidth: 1,
                        borderRadius: 4,
                        barPercentage: 0.35,
                        categoryPercentage: 0.7,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: "index",
                    intersect: false,
                },
                plugins: {
                    title: {
                        display: true,
                        text: `Anggaran vs Realisasi per Bulan - Tahun ${this.state.tahun}`,
                        font: { size: 18, weight: "bold" },
                        color: "#2c3e50",
                        padding: { bottom: 20 },
                    },
                    legend: {
                        display: true,
                        position: "top",
                        labels: {
                            usePointStyle: true,
                            padding: 20,
                            font: { size: 13 },
                        },
                    },
                    tooltip: {
                        enabled: true,
                        mode: "index",
                        intersect: false,
                        backgroundColor: "rgba(0, 0, 0, 0.85)",
                        titleFont: { size: 14, weight: "bold" },
                        bodyFont: { size: 13 },
                        padding: 14,
                        cornerRadius: 8,
                        callbacks: {
                            title(items) {
                                return `Bulan ${items[0].label}`;
                            },
                            label(item) {
                                const label = item.dataset.label || "";
                                return ` ${label}: ${formatRupiah(item.raw)}`;
                            },
                            afterBody(items) {
                                const idx = items[0].dataIndex;
                                const budget = items[0].chart.data.datasets[0].data[idx];
                                const realisasi = items[0].chart.data.datasets[1].data[idx];
                                const sisa = budget - realisasi;
                                const pct = budget > 0
                                    ? ((realisasi / budget) * 100).toFixed(2)
                                    : "0.00";
                                return [
                                    "─────────────────",
                                    `Sisa Anggaran: ${formatRupiah(sisa)}`,
                                    `Persentase Terserap: ${pct}%`,
                                ];
                            },
                        },
                    },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback(value) {
                                return formatCompact(value);
                            },
                        },
                        grid: {
                            color: "rgba(0, 0, 0, 0.06)",
                        },
                    },
                    x: {
                        grid: {
                            display: false,
                        },
                    },
                },
                // Hanya hover/tooltip — tidak ada klik navigasi
                onClick: undefined,
            },
        });
    }

    async _openMonthlyDetail(month) {
        const monthNames = [
            "Januari", "Februari", "Maret", "April", "Mei", "Juni",
            "Juli", "Agustus", "September", "Oktober", "November", "Desember",
        ];
        const monthIdx = parseInt(month) - 1;
        const monthName = monthNames[monthIdx] || month;

        let domain = [
            ["rka_id.tahun", "=", this.state.tahun],
            ["month", "=", month],
        ];
        if (this.state.selectedCoa) {
            domain.push(["rka_id.account_id", "=", parseInt(this.state.selectedCoa)]);
        }

        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Detail Anggaran - ${monthName} ${this.state.tahun}`,
            res_model: "sif.rka.budget.month",
            view_mode: "list,form",
            domain: domain,
            target: "new",
            context: {
                search_default_group_account: 1,
            },
        });
    }

    async onFilterCoa(ev) {
        this.state.selectedCoa = ev.target.value;
        await this._loadChartData();
    }

    async onFilterTahun(ev) {
        this.state.tahun = ev.target.value;
        await this._loadChartData();
    }

    /**
     * Alias untuk kompatibilitas dengan template yang memanggil onNavHome
     */
    onNavHome() {
        this.navigateToDashboard();
    }

    navigateToDashboard() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Dashboard RKA",
            res_model: "sif.rka.dashboard.view",
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    navigateToRkaTahunan() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "RKA Tahunan",
            res_model: "sif.rka.budget",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }
}

// Register as client action
registry.category("actions").add("sif_rka.bar_chart_action", SifRkaBarChartAction);

export default SifRkaBarChartAction;