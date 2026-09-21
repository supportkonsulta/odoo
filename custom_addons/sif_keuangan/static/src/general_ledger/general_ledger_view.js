/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { translate, getActiveLang } from "../i18n";

export class GeneralLedgerView extends Component {
    static template = "sif_keuangan.GeneralLedgerView";

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
        const initialPartnerId = actionParams.partner_id || "";

        this.state = useState({
            filters: {
                date_from: initialDateFrom,
                date_to: initialDateTo,
                target_move: initialTargetMove,
                search: initialSearch,
                unit_name: initialUnitName,
                partner_id: initialPartnerId,
                lang: getActiveLang(),
            },
            searchQuery: initialSearch,
            unfoldedAccounts: {},
            data: {
                company_name: "PT Konsulta Semen Gresik",
                date_from: initialDateFrom,
                date_to: initialDateTo,
                date_from_display: "01/01/" + year,
                date_to_display: "31/12/" + year,
                target_move: initialTargetMove,
                unit_name: initialUnitName,
                units: [],
                partners: [],
                accounts: [],
                grand_total: {
                    total_debit: 0,
                    total_debit_formatted: "Rp 0,00",
                    total_credit: 0,
                    total_credit_formatted: "Rp 0,00",
                    difference: 0,
                    difference_formatted: "Rp 0,00",
                    is_balanced: true,
                },
            },
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

    get filteredAccounts() {
        if (!this.state.data || !this.state.data.accounts) return [];
        const q = (this.state.searchQuery || "").toLowerCase().trim();
        if (!q) return this.state.data.accounts;
        return this.state.data.accounts.filter(acc =>
            (acc.name && acc.name.toLowerCase().includes(q)) ||
            (acc.code && acc.code.toLowerCase().includes(q)) ||
            (acc.full_name && acc.full_name.toLowerCase().includes(q)) ||
            (acc.lines && acc.lines.some(l =>
                (l.name && l.name.toLowerCase().includes(q)) ||
                (l.partner_name && l.partner_name.toLowerCase().includes(q)) ||
                (l.ref && l.ref.toLowerCase().includes(q))
            ))
        );
    }

    async loadData() {
        this.state.loading = true;
        try {
            const queryFilters = {
                ...this.state.filters,
                lang: getActiveLang(),
            };
            const result = await this.orm.call(
                "sif.general.ledger",
                "get_general_ledger_data",
                [queryFilters]
            );
            this.state.data = result;

            // Default buka seluruh akun agar langsung terlihat
            if (result.accounts && result.accounts.length > 0) {
                result.accounts.forEach(acc => {
                    this.state.unfoldedAccounts[acc.id] = true;
                });
            }
        } catch (err) {
            console.error("Error loading General Ledger data:", err);
            this.notification.add(this.t("gl.empty_title"), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    toggleAccount(accountId) {
        this.state.unfoldedAccounts[accountId] = !this.state.unfoldedAccounts[accountId];
    }

    unfoldAll() {
        if (this.state.data && this.state.data.accounts) {
            this.state.data.accounts.forEach(acc => {
                this.state.unfoldedAccounts[acc.id] = true;
            });
        }
    }
    expandAll() { this.unfoldAll(); }

    foldAll() {
        this.state.unfoldedAccounts = {};
    }
    collapseAll() { this.foldAll(); }

    async onUnitChange(ev) {
        this.state.filters.unit_name = ev.target.value;
        await this.loadData();
    }

    async onPartnerChange(ev) {
        this.state.filters.partner_id = ev.target.value;
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
        } else if (preset === "last_month") {
            const prevMonth = month === 0 ? 11 : month - 1;
            const prevYear = month === 0 ? year - 1 : year;
            const mStr = String(prevMonth + 1).padStart(2, "0");
            const lastDay = new Date(prevYear, prevMonth + 1, 0).getDate();
            this.state.filters.date_from = `${prevYear}-${mStr}-01`;
            this.state.filters.date_to = `${prevYear}-${mStr}-${String(lastDay).padStart(2, "0")}`;
        } else if (preset === "last_year") {
            this.state.filters.date_from = `${year - 1}-01-01`;
            this.state.filters.date_to = `${year - 1}-12-31`;
        }
        if (preset !== "custom") {
            await this.loadData();
        }
    }

    async onCustomDateFromChange(ev) {
        this.state.customDateFrom = ev.target.value;
        this.state.filters.date_from = ev.target.value;
        if (this.state.filters.date_from && this.state.filters.date_to) {
            await this.loadData();
        }
    }

    async onCustomDateToChange(ev) {
        this.state.customDateTo = ev.target.value;
        this.state.filters.date_to = ev.target.value;
        if (this.state.filters.date_from && this.state.filters.date_to) {
            await this.loadData();
        }
    }

    async onTargetMoveChange(ev) {
        this.state.filters.target_move = ev.target.value;
        await this.loadData();
    }

    openJournalEntry(entryId) {
        if (!entryId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sif.jurnal.entry",
            res_id: entryId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async onResetSearch() {
        this.state.searchQuery = "";
        this.state.filters.search = "";
        this.state.filters.unit_name = "";
        this.state.filters.partner_id = "";
        this.state.datePreset = "this_year";
        const today = new Date();
        const year = today.getFullYear();
        this.state.filters.date_from = `${year}-01-01`;
        this.state.filters.date_to = `${year}-12-31`;
        this.state.customDateFrom = `${year}-01-01`;
        this.state.customDateTo = `${year}-12-31`;
        await this.loadData();
    }

    onExportPDF() {
        const queryParams = new URLSearchParams({
            date_from: this.state.filters.date_from || "",
            date_to: this.state.filters.date_to || "",
            target_move: this.state.filters.target_move || "posted",
            search: this.state.searchQuery || "",
            unit_name: this.state.filters.unit_name || "",
            partner_id: this.state.filters.partner_id || "",
            lang: getActiveLang(),
        });
        window.location.href = `/sif_keuangan/export_general_ledger_pdf?${queryParams.toString()}`;
    }
    downloadPdf() { this.onExportPDF(); }

    onExportXLSX() {
        const queryParams = new URLSearchParams({
            date_from: this.state.filters.date_from || "",
            date_to: this.state.filters.date_to || "",
            target_move: this.state.filters.target_move || "posted",
            search: this.state.searchQuery || "",
            unit_name: this.state.filters.unit_name || "",
            partner_id: this.state.filters.partner_id || "",
            lang: getActiveLang(),
        });
        window.location.href = `/sif_keuangan/export_general_ledger_xlsx?${queryParams.toString()}`;
    }
    downloadXlsx() { this.onExportXLSX(); }
}

registry.category("actions").add("sif_keuangan.GeneralLedgerView", GeneralLedgerView);
registry.category("actions").add("sif_keuangan.general_ledger", GeneralLedgerView);
