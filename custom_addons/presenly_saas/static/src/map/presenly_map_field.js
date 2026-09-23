/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useState, useRef } from "@odoo/owl";
import { loadCSS, loadJS } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { formatDateTime } from "@web/views/fields/formatters";
import { _t } from "@web/core/l10n/translation";

const LEAFLET_BASE = "/presenly_saas/static/lib/leaflet";

// Warna dipakai konsisten di penanda, lingkaran radius, dan legenda, supaya
// pembaca tidak perlu mencocokkan bentuk dengan teks.
const WARNA_USER = "#714b67";
const WARNA_KANTOR = "#0d6efd";

let leafletPromise = null;

/**
 * Muat Leaflet saat pertama dibutuhkan, lewat tag script biasa.
 *
 * Leaflet 1.9.4 adalah pustaka UMD: berkasnya menetapkan `window.L` saat
 * dijalankan. Kalau dimasukkan lewat daftar `assets` di manifest, Odoo
 * menggabungkannya sebagai modul dan penetapan itu tidak sampai ke halaman —
 * sudah diperiksa: penanda `window.L` milik Leaflet tidak ada di bundel yang
 * dihasilkan. `loadJS` menghasilkan tag script biasa, sehingga UMD berjalan
 * sebagaimana rancangannya; cara yang sama dipakai Odoo core untuk `pdfjs`.
 */
function loadLeaflet() {
    if (window.L) {
        return Promise.resolve(window.L);
    }
    if (!leafletPromise) {
        loadCSS(`${LEAFLET_BASE}/leaflet.css`);
        leafletPromise = loadJS(`${LEAFLET_BASE}/leaflet.js`)
            .then(() => {
                if (!window.L) {
                    throw new Error("Leaflet loaded but did not publish window.L");
                }
                return window.L;
            })
            .catch((error) => {
                leafletPromise = null;
                throw error;
            });
    }
    return leafletPromise;
}

/** Ikon pin bawaan, dengan alamat eksplisit karena CSS-nya digabung Odoo. */
function pinIcon(L, warna) {
    return L.divIcon({
        className: "o_presenly_pin",
        html: `<span style="background:${warna}"></span>`,
        iconSize: [18, 18],
        iconAnchor: [9, 9],
        popupAnchor: [0, -10],
    });
}

/**
 * Tampilkan titik presensi dan kantornya pada satu peta.
 *
 * `options` menentukan field mana yang dibaca; semuanya WAJIB dideklarasikan di
 * arch view, karena `record.data` hanya memuat field yang ada di view:
 *
 *   {
 *     'lon_field': 'check_in_longitude',
 *     'radius_field': 'check_in_allowed_radius_meters',
 *     'label_field': 'location_name',
 *     'person_field': 'employee_name',
 *     'time_field': 'check_in_time',
 *     'point_label': 'Check-in',
 *     'office_lat_field': 'office_latitude',
 *     'office_lon_field': 'office_longitude',
 *     'office_radius_field': 'office_radius_meters',
 *   }
 *
 * Kalau field kantor tidak diberikan, titiknya sendiri dianggap kantor —
 * dipakai di form Lokasi Kerja, yang memang menggambarkan kantornya.
 */
export class PresenlyMapField extends Component {
    static template = "presenly_saas.MapField";
    // `options` WAJIB dideklarasikan di sini. `standardFieldProps` tidak
    // memuatnya, sedangkan `extractProps` di pendaftaran bawah mengirimkannya.
    // Prop yang tidak ada di skema membuat OWL menolak komponennya, dan karena
    // komponen ini dipasang di dalam form, kegagalannya ikut menjatuhkan
    // seluruh halaman dengan galat yang tidak menyebut penyebabnya:
    //
    //   TypeError: this.child.mount is not a function
    //
    // Widget core yang memakai `options` mendeklarasikannya sendiri; lihat
    // `property_definition_selection.js`.
    static props = {
        ...standardFieldProps,
        options: { type: Object, optional: true },
    };

    /**
     * Tangkap galat di dalam komponen ini.
     *
     * Widget ini melakukan hal yang paling mudah gagal di seluruh modul:
     * memuat pustaka dari jaringan, menggambar DOM, dan memanggil server ubin.
     * Tanpa penanganan di sini, satu kegagalan membuat OWL membuang seluruh
     * pohon komponen — halaman form hilang, dan pesannya tidak menyebut widget
     * mana penyebabnya. Sekarang galatnya tampil di kotak peta itu sendiri.
     */
    onError(error) {
        this.state.error = `The map could not be displayed (${error.message}).`;
        return true;
    }

    setup() {
        this.mapRef = useRef("map");
        this.map = null;
        this.layer = null;
        this.state = useState({ error: null, tileErrors: 0, zoomed: null });
        onMounted(() => this.renderMap());
        onWillUnmount(() => {
            if (this.map) {
                this.map.remove();
                this.map = null;
            }
        });
    }

    _angka(nama) {
        const value = nama ? this.props.record.data[nama] : null;
        return typeof value === "number" && value !== 0 ? value : null;
    }

    get latitude() {
        return this._angka(this.props.name);
    }

    get longitude() {
        return this._angka(this.props.options?.lon_field);
    }

    get radius() {
        const value = this._angka(this.props.options?.radius_field);
        return value && value > 0 ? value : null;
    }

    get label() {
        const nama = this.props.options?.label_field;
        return nama ? this.props.record.data[nama] || "" : "";
    }

    get person() {
        const nama = this.props.options?.person_field;
        return nama ? this.props.record.data[nama] || "" : "";
    }

    /**
     * Waktu presensi dalam format yang dibaca orang, bukan ISO mentah.
     *
     * `record.data` mengembalikan nilai apa adanya dari server, jadi di sini
     * nilainya diratakan dulu memakai formatter Odoo supaya zona waktu dan
     * bahasa pengguna ikut berlaku. Nilai yang tidak bisa dibaca tetap
     * ditampilkan apa adanya: lebih baik mentah daripada hilang.
     */
    get waktu() {
        const nama = this.props.options?.time_field;
        const mentah = nama ? this.props.record.data[nama] : null;
        if (!mentah) {
            return "";
        }
        try {
            const dirapikan = formatDateTime(mentah);
            return dirapikan && !dirapikan.includes("Invalid") ? dirapikan : String(mentah);
        } catch {
            return String(mentah);
        }
    }

    get pointLabel() {
        return this.props.options?.point_label || "Check-in";
    }

    get hasCoordinates() {
        return this.latitude !== null && this.longitude !== null;
    }

    /** Kantor dari field tersendiri; kalau tidak ada, titik ini sendiri kantornya. */
    get officeCoordinates() {
        const options = this.props.options || {};
        if (!options.office_lat_field) {
            return this.hasCoordinates ? [this.latitude, this.longitude] : null;
        }
        const lat = this._angka(options.office_lat_field);
        const lon = this._angka(options.office_lon_field);
        return lat !== null && lon !== null ? [lat, lon] : null;
    }

    get officeRadius() {
        const options = this.props.options || {};
        if (!options.office_radius_field) {
            return this.radius;
        }
        const value = this._angka(options.office_radius_field);
        return value && value > 0 ? value : null;
    }

    /** Kantor dipisah dari titik kalau koordinatnya berbeda. */
    get punyaDuaTitik() {
        const kantor = this.officeCoordinates;
        if (!kantor || !this.hasCoordinates) {
            return false;
        }
        return kantor[0] !== this.latitude || kantor[1] !== this.longitude;
    }

    /** Titik presensi jatuh di lokasi kantornya sendiri. */
    get atOffice() {
        return this.hasCoordinates && Boolean(this.officeCoordinates) && !this.punyaDuaTitik;
    }

    get officeNotMirrored() {
        return Boolean(this.props.options?.office_lat_field) && !this.officeCoordinates;
    }

    /** Ada yang bisa digambar: titik presensi, kantor, atau keduanya. */
    get punyaPeta() {
        return this.hasCoordinates || Boolean(this.officeCoordinates);
    }

    /**
     * Mode ringkas: tanpa tombol pintasan, dan petanya lebih pendek.
     *
     * Dipakai di form yang memuat dua peta sekaligus, mis. log presensi yang
     * punya titik masuk dan titik keluar.
     */
    get compact() {
        return Boolean(this.props.options?.compact);
    }

    /**
     * Tombol pintasan ditampilkan atau tidak.
     *
     * Ditulis sebagai getter, bukan sebagai `t-if="punyaPeta and not compact"`:
     * ekspresi di templat OWL adalah JavaScript, dan `not` bukan operatornya.
     * Salah tulis di situ tidak memunculkan galat yang menyebut barisnya, hanya
     * "Failed to compile template" — dan satu form penuh ikut mati.
     */
    get punyaPintasan() {
        return this.punyaPeta && !this.compact;
    }

    /**
     * Baris legenda kantor, disusun di sini dan bukan di templat.
     *
     * Templat hanya memasang satu simpul `t-out` per elemen bersyarat: bentuk
     * yang menaruh teks bercampur `<t t-out>` membuat OWL gagal memasang widget
     * ini di bundel produksi (lihat catatan di `presenly_map_field.xml`).
     *
     * Karena rangkaiannya terjadi saat berjalan, `_t()` dipakai supaya teksnya
     * tetap bisa diterjemahkan; nama kantor masuk sebagai argumen, bukan
     * menjadi bagian kalimat yang diterjemahkan.
     */
    get legendOffice() {
        if (!this.officeCoordinates) {
            return "";
        }
        const nama = this.label ? `: ${this.label}` : "";
        const radius = this.officeRadius ? _t(" · allowed radius %s m", this.officeRadius) : "";
        return _t("Office%s%s", nama, radius);
    }

    /** Baris legenda titik presensi; kosong kalau memang tidak ada yang bisa dikatakan. */
    get legendPoint() {
        if (!this.hasCoordinates) {
            return "";
        }
        // Sejalan dengan penanda di peta: penanda titik hanya digambar kalau
        // letaknya memang berbeda dari kantor. Keterangannya tetap ditampilkan
        // kalau membawa sesuatu yang tidak ada di baris kantor — waktunya, atau
        // orangnya. Tanpa syarat ini, peta yang menggambar satu penanda kantor
        // tetap mencantumkan legenda titik berwarna kedua.
        if (!this.punyaDuaTitik && !this.waktu && !this.person) {
            return "";
        }
        const bagian = [this.pointLabel];
        if (this.person) {
            bagian.push(this.person);
        }
        if (this.waktu) {
            bagian.push(this.waktu);
        }
        const teks = bagian.join(" · ");
        return this.atOffice ? _t("%s (at the office location)", teks) : teks;
    }

    get coordinatesText() {
        if (!this.hasCoordinates) {
            return "";
        }
        return `${this.latitude.toFixed(6)}, ${this.longitude.toFixed(6)}`;
    }

    get openStreetMapUrl() {
        if (!this.hasCoordinates) {
            return "";
        }
        return `https://www.openstreetmap.org/?mlat=${this.latitude}&mlon=${this.longitude}#map=16/${this.latitude}/${this.longitude}`;
    }

    /**
     * Field pendamping yang disebut di `options` tapi tidak dimuat view ini.
     *
     * `record.data` hanya memuat field yang dideklarasikan di arch form, jadi
     * field yang lupa dicantumkan terbaca sebagai kosong: peta tampil tanpa
     * penanda, tanpa galat. Keadaan itu dilaporkan supaya bisa diperbaiki.
     */
    get missingFields() {
        const options = this.props.options || {};
        return [
            options.lon_field,
            options.radius_field,
            options.label_field,
            options.person_field,
            options.time_field,
            options.office_lat_field,
            options.office_lon_field,
            options.office_radius_field,
        ].filter((nama) => nama && !(nama in this.props.record.data));
    }

    /** Daftar field yang tidak terbaca, sudah dirangkai untuk ditampilkan. */
    get missingFieldsText() {
        return this.missingFields.join(", ");
    }

    async renderMap() {
        if (!this.hasCoordinates) {
            return;
        }
        let L;
        try {
            L = await loadLeaflet();
        } catch (error) {
            this.state.error = `The map library could not be loaded (${error.message}).`;
            return;
        }
        if (!this.mapRef.el) {
            return;
        }

        const pusat = this.officeCoordinates || [this.latitude, this.longitude];
        this.map = L.map(this.mapRef.el, { center: pusat, zoom: 15, scrollWheelZoom: false });
        this.layer = L.layerGroup().addTo(this.map);

        const tiles = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        });
        tiles.on("tileerror", () => {
            this.state.tileErrors += 1;
        });
        tiles.addTo(this.map);

        // --- kantor: penanda berbeda + lingkaran radius yang diizinkan ---
        if (this.officeCoordinates) {
            const radius = this.officeRadius;
            L.marker(this.officeCoordinates, { icon: pinIcon(L, WARNA_KANTOR), zIndexOffset: 100 })
                .addTo(this.layer)
                .bindPopup(this._popupKantor(radius));
            if (radius) {
                L.circle(this.officeCoordinates, {
                    radius,
                    color: WARNA_KANTOR,
                    weight: 1,
                    fillColor: WARNA_KANTOR,
                    fillOpacity: 0.08,
                }).addTo(this.layer);
            }
        }

        // --- titik presensi ---
        if (this.hasCoordinates && (this.punyaDuaTitik || !this.officeCoordinates)) {
            L.marker([this.latitude, this.longitude], { icon: pinIcon(L, WARNA_USER) })
                .addTo(this.layer)
                .bindPopup(this._popupTitik());
        }

        this.map.fitBounds(L.latLngBounds(this._semuaTitik()), { padding: [30, 30] });
        setTimeout(() => this.map && this.map.invalidateSize(), 200);
    }

    _popupKantor(radius) {
        const nama = this.label || "Office";
        return `<strong>Office: ${nama}</strong>${radius ? `<br/>Allowed radius: ${radius} m` : ""}`;
    }

    _popupTitik() {
        const baris = [`<strong>${this.pointLabel}</strong>`];
        if (this.person) {
            baris.push(this.person);
        }
        if (this.waktu) {
            baris.push(this.waktu);
        }
        if (this.label) {
            baris.push(this.label);
        }
        return baris.join("<br/>");
    }

    _semuaTitik() {
        const titik = [];
        if (this.hasCoordinates) {
            titik.push([this.latitude, this.longitude]);
        }
        if (this.officeCoordinates) {
            titik.push(this.officeCoordinates);
        }
        return titik;
    }

    // ------------------------------------------------------------------
    // Tombol pintasan
    // ------------------------------------------------------------------
    keTitik(koordinat) {
        if (koordinat && this.map) {
            this.map.setView(koordinat, this.officeRadius && koordinat === this.officeCoordinates ? 15 : 17);
            this.state.zoomed = koordinat === this.officeCoordinates ? "office" : "user";
        }
    }

    keKantor() {
        this.keTitik(this.officeCoordinates);
    }

    keUser() {
        this.keTitik(this.hasCoordinates ? [this.latitude, this.longitude] : null);
    }

    reset() {
        if (this.map && this.layer) {
            const L = window.L;
            this.map.fitBounds(L.latLngBounds(this._semuaTitik()), { padding: [30, 30] });
            this.state.zoomed = null;
        }
    }
}

registry.category("fields").add("presenly_map", {
    component: PresenlyMapField,
    supportedTypes: ["float"],
    extractProps: ({ options }) => ({ options }),
});
