/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PivotModel } from "@web/views/pivot/pivot_model";
import { PivotRenderer } from "@web/views/pivot/pivot_renderer";

/**
 * Jangan tawarkan kelompok yang sudah dipakai sebagai baris atau kolom pivot.
 *
 * Pivot Odoo mengizinkan kelompok yang sama ditambahkan berulang kali: menunya
 * berisi seluruh pilihan group-by, dan tidak ada yang memeriksa yang sudah
 * dipakai. Akibatnya satu baris bisa dibuka tanpa henti, dan tiap lapisnya hanya
 * mengulang nilai di atasnya — "yusril" di bawah "yusril" di bawah "yusril" —
 * dengan angka yang sama persis di semua lapis. Tidak ada pertanyaan yang
 * dijawab oleh lapisan seperti itu; yang terlihat hanya daftar yang bertambah
 * panjang.
 *
 * Yang dibandingkan **kelompoknya**, bukan kolomnya: `work_date:month` dan
 * `work_date:year` memakai kolom yang sama tetapi menjawab pertanyaan yang
 * berbeda, jadi keduanya tetap boleh dipakai bersama.
 *
 * Tiga tempat diperiksa, dan ketiganya perlu:
 *
 * - `groupByItems` milik renderer menyaring menunya, supaya pilihannya tidak
 *   menawarkan hal yang tidak akan terjadi.
 * - `addGroupBy` milik model menolaknya, karena menu "Custom Group By" memakai
 *   daftar kolomnya sendiri dan tidak lewat penyaringan di atas.
 * - `bisaDibuka` dipakai templat untuk menyembunyikan ikon buka-baris saat
 *   pilihannya memang sudah habis, dan `onHeaderClick` berhenti membuka menu
 *   kosong. Sebelum ini ikonnya selalu ada, dan mengkliknya di lapis terdalam
 *   hanya memunculkan menu yang tidak berisi apa pun.
 *
 * Semuanya gagal dengan aman: apa pun yang tidak dikenali diperlakukan seperti
 * sebelumnya, sehingga pivot tidak bisa rusak karena penjaga ini.
 */

/** Kelompok yang sudah dipakai pada satu sisi, apa adanya — termasuk interval. */
function kelompokTerpakai(metaData, type) {
    const groupBys = type === "col" ? metaData.fullColGroupBys : metaData.fullRowGroupBys;
    if (!Array.isArray(groupBys)) {
        return null;
    }
    return new Set(groupBys.map((groupBy) => String(groupBy)));
}

patch(PivotRenderer.prototype, {
    /** Daftar pilihan Odoo apa adanya, sebelum disaring. */
    get semuaItemKelompok() {
        return super.groupByItems;
    },

    /** Pilihan yang masih tersisa untuk satu sisi. */
    itemKelompokTersisa(type) {
        const items = this.semuaItemKelompok;
        const metaData = this.model && this.model.metaData;
        const terpakai = metaData ? kelompokTerpakai(metaData, type) : null;
        if (!terpakai) {
            return items;
        }
        const hasil = [];
        for (const item of items) {
            if (!item.options) {
                if (!terpakai.has(item.fieldName)) {
                    hasil.push(item);
                }
                continue;
            }
            // Kolom bertanggal: yang disaring pilihan intervalnya, bukan
            // kolomnya — bulan dan tahun pada kolom yang sama sah berdampingan.
            const options = item.options.filter(
                (option) => !terpakai.has(`${item.fieldName}:${option.id}`)
            );
            if (options.length) {
                hasil.push({ ...item, options });
            }
        }
        return hasil;
    },

    /** Masih ada kelompok yang bisa dibuka di sisi ini? */
    bisaDibuka(isXAxis) {
        return this.itemKelompokTersisa(isXAxis ? "col" : "row").length > 0;
    },

    get groupByItems() {
        const info = this.dropdown && this.dropdown.cellInfo;
        if (!info) {
            return this.semuaItemKelompok;
        }
        return this.itemKelompokTersisa(info.type);
    },

    onHeaderClick(ev, cell, isXAxis) {
        // Lapis terdalam tanpa pilihan tersisa: menunya tidak akan berisi apa
        // pun, jadi kliknya tidak perlu membuka apa-apa.
        if (cell.isLeaf && !cell.isFolded && !this.bisaDibuka(isXAxis)) {
            return;
        }
        return super.onHeaderClick(ev, cell, isXAxis);
    },
});

patch(PivotModel.prototype, {
    async addGroupBy(params) {
        const terpakai = this.metaData
            ? kelompokTerpakai(this.metaData, params.type)
            : null;
        const kelompok = params.interval
            ? `${params.fieldName}:${params.interval}`
            : params.fieldName;
        if (terpakai && terpakai.has(kelompok)) {
            return;
        }
        return super.addGroupBy(params);
    },
});
