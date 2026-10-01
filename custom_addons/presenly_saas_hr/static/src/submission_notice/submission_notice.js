/** @odoo-module **/

import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ErrorDialog, WarningDialog } from "@web/core/errors/error_dialogs";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

/**
 * Kabar pengajuan yang bergerak, dan keputusan yang menjelaskan dirinya.
 *
 * Dua hal dikerjakan berkas ini:
 *
 * 1. **Kabar dari bus.** Pengajuan bisa diputuskan di aplikasi, dan cermin di
 *    Odoo baru mengetahuinya saat ditarik. Ketika tarikan itu menulis perubahan
 *    status atau level, penerimanya dikabari lewat bus.
 *
 * 2. **Dialog keputusan.** Tombol Approve/Reject bisa ditolak server, dan
 *    penolakan itu harus terbaca - bukan toast yang menghilang sendiri.
 *
 * Dialognya memakai dialog **bawaan Odoo** sesuai tingkatannya: `AlertDialog`
 * untuk pemberitahuan, `WarningDialog` untuk peringatan, `ErrorDialog` untuk
 * galat. Bentuk, ukuran huruf, dan tombolnya sudah dikenal pengguna, dan tidak ada
 * yang perlu dirawat di sini.
 *
 * ## Kapan layarnya disegarkan sendiri
 *
 * Hanya ketika yang sedang dibuka **record itu sendiri**. Pengguna lain yang
 * kebetulan membuka daftar tidak diganggu: memuat ulang daftar membuang posisi
 * gulir dan pencariannya, dan itu kerugian yang tidak sebanding dengan kabar yang
 * bisa dilihat kapan saja. Formulir cermin juga hanya-baca, jadi memuat ulangnya
 * tidak mungkin membuang isian siapa pun - dan sesudah disegarkan, tombol
 * Approve/Reject yang sudah tidak berhak muncul kembali hilang dengan sendirinya,
 * karena keadaannya dihitung ulang dari level yang baru.
 */

const NOTICE_DIALOGS = {
    alert: AlertDialog,
    warning: WarningDialog,
    error: ErrorDialog,
};

function reloadCurrentView(action) {
    // Aksi `reload` bawaan memuat ulang tampilan yang sedang terbuka.
    action.doAction({ type: "ir.actions.client", tag: "reload" });
}

/** Apakah yang dibuka pengguna adalah record yang dikabarkan? */
function isOpenRecord(action, data) {
    const controller = action.currentController;
    const props = controller && controller.props;
    if (!props || props.resModel !== data.model) {
        return false;
    }
    // `resId` hanya ada pada formulir. Daftar sengaja tidak ikut disegarkan.
    return props.resId === data.id;
}

function describeSubmission(data) {
    const baris = [
        _t("Status: %(status)s", { status: data.status || _t("unknown") }),
    ];
    if (data.total_levels) {
        baris.push(_t("Current level: %(level)s of %(total)s", {
            level: data.level || 0,
            total: data.total_levels,
        }));
    }
    if (data.waiting_for) {
        baris.push(_t("Waiting for: %(name)s", { name: data.waiting_for }));
    }
    return _t("%(name)s changed in Presenly.", {
        name: data.res_name || _t("This request"),
    }) + "\n\n" + baris.join("\n") + "\n\n"
        + _t("The screen has been refreshed, so the status and the buttons now "
             + "show the current state.");
}

/** Tampilkan pesan dengan dialog bawaan sesuai tingkatannya. */
export function showNotice(dialog, { title, body, kind }) {
    const Dialog = NOTICE_DIALOGS[kind] || AlertDialog;
    if (Dialog === AlertDialog) {
        // `AlertDialog` menyebut isinya `body`; dua yang lain `message`.
        dialog.add(Dialog, { title, body, confirmLabel: _t("Close") });
    } else {
        dialog.add(Dialog, { title, message: body });
    }
}

export const presenlySaasNoticeService = {
    dependencies: ["bus_service", "dialog", "action"],

    start(env, { bus_service, dialog, action }) {
        bus_service.subscribe("presenly_saas_submission", (data) => {
            if (!isOpenRecord(action, data)) {
                return;
            }
            // Disegarkan lebih dulu, lalu dijelaskan: begitu dialognya ditutup,
            // layar di belakangnya sudah keadaan yang baru.
            reloadCurrentView(action);
            showNotice(dialog, {
                title: _t("Request updated in Presenly"),
                body: describeSubmission(data),
                kind: "warning",
            });
        });
    },
};

registry.category("services").add("presenly_saas_notice", presenlySaasNoticeService);

/**
 * Aksi klien yang dipakai server untuk menampilkan hasil keputusan.
 *
 * Tombol Approve/Reject mengirim keputusan; jawabannya bisa diterima, ditolak
 * server, atau tidak perlu dikirim sama sekali karena levelnya sudah bergerak.
 * Ketiganya perlu kalimat yang terbaca, dan layarnya disegarkan supaya yang
 * terlihat bukan keadaan yang baru saja dibantah server.
 */
export function presenlySaasNoticeAction(env, action) {
    const params = action.params || {};
    if (params.reload) {
        reloadCurrentView(env.services.action);
    }
    showNotice(env.services.dialog, {
        title: params.title || _t("Presenly"),
        body: params.body || "",
        kind: params.kind || "warning",
    });
}

registry.category("actions").add("presenly_saas.notice", presenlySaasNoticeAction);
