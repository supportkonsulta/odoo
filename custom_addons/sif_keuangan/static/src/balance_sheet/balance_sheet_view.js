/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { translate, getActiveLang } from "../i18n";

export class BalanceSheetView extends Component {
    static template = "sif_keuangan.BalanceSheetView";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        const today = new Date();
        const year = today.getFullYear();
        const actionParams = this.props.action?.params || {};
        const initialSearch = actionParams.search || "";
        const initialDateFrom = actionParams.date_from || `${year}-01-01`;
        const initialDateTo = actionParams.date_to || `${year}-12-31`;
        const initialTargetMove = actionParams.target_move || "posted";
        const initialUnitName = actionParams.unit_name || "";

        this.state = useState({
            filters: {
                date_from: initialDateFrom,
                date_to: initialDateTo,
                comparison_type: "none",
                comparison_date: `${year - 1}-12-31`,
                target_move: initialTargetMove,
                unit_name: initialUnitName,
                search: initialSearch,
                lang: getActiveLang(),
            },
            searchQuery: initialSearch,
            selectedUnitName: initialUnitName,
            comparisonMode: "none",
            customComparisonDate: `${year - 1}-12-31`,
            customDateFrom: initialDateFrom,
            customDateTo: initialDateTo,
            unfolded: {
                assets: true,
                current_assets: true,
                bank_and_cash: true,
                receivables: true,
                other_current_assets: true,
                prepayments: true,
                fixed_assets: true,
                non_current_assets: true,
                liabilities: true,
                current_liabilities: true,
                general_current: true,
                credit_card: true,
                payables: true,
                non_current_liabilities: true,
                equity: true,
                direct_equity: true,
                earnings: true,
            },
            data: null,
            loading: true,
            datePreset: initialSearch ? "custom" : "this_year",
            customDateFrom: initialDateFrom,
            customDateTo: initialDateTo,
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    t(key, params = {}) {
        return translate(key, params);
    }

    async loadData() {
        this.state.loading = true;
        try {
            const filters = {
                ...this.state.filters,
                lang: getActiveLang(),
            };
            const result = await this.orm.call(
                "sif.balance.sheet",
                "get_balance_sheet_data",
                [filters]
            );
            this.state.data = result;
        } catch (err) {
            console.error("Error loading Balance Sheet data:", err);
            this.notification.add(this.t("bs.title") + " error.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    toggleSection(sectionKey) {
        this.state.unfolded[sectionKey] = !this.state.unfolded[sectionKey];
    }

    unfoldAll() {
        Object.keys(this.state.unfolded).forEach(k => {
            this.state.unfolded[k] = true;
        });
    }
    expandAll() { this.unfoldAll(); }

    foldAll() {
        Object.keys(this.state.unfolded).forEach(k => {
            this.state.unfolded[k] = false;
        });
    }
    collapseAll() { this.foldAll(); }

    async onUnitChange(ev) {
        this.state.selectedUnitName = ev.target.value;
        this.state.filters.unit_name = ev.target.value;
        await this.loadData();
    }

    async onDatePresetChange(ev) {
        const preset = ev.target.value;
        this.state.datePreset = preset;
        const today = new Date();
        const year = today.getFullYear();
        const month = today.getMonth();

        if (preset === "this_year") {
            this.state.filters.date_from = `${year}-01-01`;
            this.state.filters.date_to = `${year}-12-31`;
        } else if (preset === "this_month") {
            const mStr = String(month + 1).padStart(2, "0");
            const lastDay = new Date(year, month + 1, 0).getDate();
            this.state.filters.date_from = `${year}-${mStr}-01`;
            this.state.filters.date_to = `${year}-${mStr}-${String(lastDay).padStart(2, "0")}`;
        } else if (preset === "this_quarter") {
            const qStartMonth = Math.floor(month / 3) * 3;
            const qEndMonth = qStartMonth + 2;
            const qStartStr = String(qStartMonth + 1).padStart(2, "0");
            const qEndStr = String(qEndMonth + 1).padStart(2, "0");
            const lastDay = new Date(year, qEndMonth + 1, 0).getDate();
            this.state.filters.date_from = `${year}-${qStartStr}-01`;
            this.state.filters.date_to = `${year}-${qEndStr}-${String(lastDay).padStart(2, "0")}`;
        } else if (preset === "last_month") {
            const prevMonth = month === 0 ? 11 : month - 1;
            const prevYear = month === 0 ? year - 1 : year;
            const mStr = String(prevMonth + 1).padStart(2, "0");
            const lastDay = new Date(prevYear, prevMonth + 1, 0).getDate();
            this.state.filters.date_from = `${prevYear}-${mStr}-01`;
            this.state.filters.date_to = `${prevYear}-${mStr}-${String(lastDay).padStart(2, "0")}`;
        } else if (preset === "last_year") {
            const prevYear = year - 1;
            this.state.filters.date_from = `${prevYear}-01-01`;
            this.state.filters.date_to = `${prevYear}-12-31`;
        }

        if (preset !== "custom") {
            await this.loadData();
        }
    }

    async onCustomDateFromChange(ev) {
        this.state.customDateFrom = ev.target.value;
        this.state.filters.date_from = ev.target.value;
        await this.loadData();
    }

    async onCustomDateToChange(ev) {
        this.state.customDateTo = ev.target.value;
        this.state.filters.date_to = ev.target.value;
        await this.loadData();
    }

    async onComparisonModeChange(ev) {
        const mode = ev.target.value;
        this.state.comparisonMode = mode;
        this.state.filters.comparison_type = mode;
        if (mode === "custom") {
            this.state.filters.comparison_date = this.state.customComparisonDate;
        }
        await this.loadData();
    }

    async onCustomComparisonDateChange(ev) {
        this.state.customComparisonDate = ev.target.value;
        this.state.filters.comparison_date = ev.target.value;
        await this.loadData();
    }

    async onTargetMoveChange(ev) {
        this.state.filters.target_move = ev.target.value;
        await this.loadData();
    }

    openGeneralLedger(accountCode) {
        if (!accountCode) return;
        this.action.doAction({
            type: "ir.actions.client",
            tag: "sif_keuangan.general_ledger",
            params: {
                search: accountCode,
                date_to: this.state.filters.date_to,
                target_move: this.state.filters.target_move,
                unit_name: this.state.filters.unit_name,
            },
        });
    }

    onExportPDF() {
        const { date_from, date_to, comparison_type, comparison_date, target_move, unit_name, search } = this.state.filters;
        const queryParams = new URLSearchParams({
            date_from: date_from || "",
            date_to: date_to || "",
            comparison_type: comparison_type || "none",
            comparison_date: comparison_date || "",
            target_move: target_move || "posted",
            unit_name: unit_name || "",
            search: search || "",
            lang: getActiveLang(),
        });
        window.location.href = `/sif_keuangan/export_balance_sheet_pdf?${queryParams.toString()}`;
    }
    downloadPdf() { this.onExportPDF(); }

    onExportXLSX() {
        const { date_from, date_to, comparison_type, comparison_date, target_move, unit_name, search } = this.state.filters;
        const queryParams = new URLSearchParams({
            date_from: date_from || "",
            date_to: date_to || "",
            comparison_type: comparison_type || "none",
            comparison_date: comparison_date || "",
            target_move: target_move || "posted",
            unit_name: unit_name || "",
            search: search || "",
            lang: getActiveLang(),
        });
        window.location.href = `/sif_keuangan/export_balance_sheet_xlsx?${queryParams.toString()}`;
    }
    downloadXlsx() { this.onExportXLSX(); }
}

registry.category("actions").add("sif_keuangan.balance_sheet", BalanceSheetView);
registry.category("actions").add("sif_keuangan.BalanceSheetView", BalanceSheetView);
