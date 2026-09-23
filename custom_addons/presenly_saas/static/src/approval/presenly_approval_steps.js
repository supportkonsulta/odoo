/** @odoo-module **/

/**
 * Widget tampilan langkah persetujuan.
 *
 * Odoo menampilkan One2many sebagai tabel: satu baris per level, tanpa penanda
 * urutan dan tanpa kaitan antar barisnya. Untuk alur persetujuan, tabel itu
 * menyembunyikan justru hal yang dicari pembaca — langkah mana yang sudah
 * lewat, langkah mana yang sedang berjalan, dan langkah mana yang belum
 * tersentuh. Widget ini menggambarnya sebagai rangkaian langkah bernomor yang
 * tersambung.
 *
 * Datanya tetap dibaca dari field One2many-nya (`approval_step_ids`), dan daftar
 * `<list>` di dalam arch field itu tetap ada: Odoo memakai subview tersebut untuk
 * menentukan field anak mana yang perlu dimuat. Yang diganti hanya tampilannya.
 */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { formatDateTime } from "@web/views/fields/formatters";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/** Warna dan label per status langkah. Kuncinya sama dengan Selection di Python. */
const TAMPILAN = {
    approved: { label: "Approved", keadaaan: "approved" },
    rejected: { label: "Rejected", keadaaan: "rejected" },
    pending: { label: "Pending", keadaaan: "todo" },
    unknown: { label: "Unknown", keadaaan: "todo" },
};

export class PresenlyApprovalSteps extends Component {
    static template = "presenly_saas.ApprovalSteps";
    static props = { ...standardFieldProps };

    /** Semua langkah, sudah diurutkan dan sudah siap digambar. */
    get steps() {
        const daftar = this.props.record.data[this.props.name];
        const records = (daftar && daftar.records) || [];
        const levelSekarang = this.props.record.data.approval_current_level || 0;

        return [...records]
            // Urutan level ditentukan di sini, bukan dari urutan pemuatan: peta
            // alur harus terbaca dari atas ke bawah.
            .sort((a, b) => (a.data.level || 0) - (b.data.level || 0))
            .map((record) => this._langkah(record.data, levelSekarang));
    }

    _langkah(data, levelSekarang) {
        const level = data.level || 0;
        const status = data.step_status || "";
        const sudahDiputus = Boolean(data.acted_by_name);
        // Langkah yang sedang berjalan: level yang ditunjuk alurnya, dan belum
        // diputus. Dipisahkan dari status `pending` biasa, karena langkah setelah
        // yang sedang berjalan juga `pending` tetapi belum tersentuh.
        const sedangBerjalan =
            level === levelSekarang && !sudahDiputus && status !== "rejected";

        let keadaan = status === "approved" || status === "rejected" ? status : "todo";
        if (sedangBerjalan) {
            keadaan = "current";
        }

        return {
            level,
            keadaan,
            label: this._label(status),
            siapa: data.approver_label || "",
            keterangan: this._keterangan(data, sedangBerjalan, sudahDiputus),
        };
    }

    _label(status) {
        const tampilan = TAMPILAN[status];
        // Status yang tidak dikenal tidak diberi label: lebih baik kosong daripada
        // menyebutnya "Pending" padahal artinya belum tentu itu.
        return tampilan ? _t(tampilan.label) : "";
    }

    _keterangan(data, sedangBerjalan, sudahDiputus) {
        const waktu = data.acted_at ? formatDateTime(data.acted_at) : "";
        let teks = "";

        if (sudahDiputus) {
            teks = waktu
                ? _t("Decided by %s on %s", data.acted_by_name, waktu)
                : _t("Decided by %s", data.acted_by_name);
        } else if (sedangBerjalan) {
            teks = _t("Waiting for a decision");
        } else if (data.step_status === "pending") {
            teks = _t("Not reached yet");
        }

        if (data.rejection_reason) {
            const alasan = _t("Reason: %s", data.rejection_reason);
            teks = teks ? `${teks} · ${alasan}` : alasan;
        }
        return teks;
    }
}

registry.category("fields").add("presenly_approval_steps", {
    component: PresenlyApprovalSteps,
    supportedTypes: ["one2many"],
});
