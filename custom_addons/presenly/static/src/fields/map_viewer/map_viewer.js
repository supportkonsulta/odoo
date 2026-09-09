import { Component, useRef, useEffect, useState } from "@odoo/owl";
import { loadJS, loadCSS } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
const LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
const OSM_TILE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

/**
 * Presenly Map Viewer
 *
 * Reads a JSON payload from the bound field (presenly_map_data) and renders
 * an interactive Leaflet + OpenStreetMap map:
 *   { markers: [{kind, label, lat, lon, distance_m, mode, radius,
 *                geofence_ready, accuracy_limit_m}], radius_m }
 *
 * Kinds:
 *   office    -> green building icon
 *   check_in  -> blue icon
 *   check_out -> magenta icon
 */
export class PresenlyMapViewer extends Component {
    static template = "presenly.MapViewer";
    static props = { ...standardFieldProps };

    setup() {
        this.mapRef = useRef("map");
        this.leafletMap = null;
        this.markers = [];
        this.circle = null;
        this.line = null;
        this.showRadius = useState({ value: true });
        this.leafletReady = false;
        this.mapData = this._parseData();

        useEffect(
            () => {
                let cancelled = false;
                Promise.all([loadCSS(LEAFLET_CSS), loadJS(LEAFLET_JS)])
                    .then(() => {
                        if (cancelled) {
                            return;
                        }
                        this.leafletReady = true;
                        this._initMap();
                    })
                    .catch((error) => {
                        console.error("Failed to load Leaflet:", error);
                    });
                return () => {
                    cancelled = true;
                    if (this.leafletMap) {
                        this.leafletMap.remove();
                        this.leafletMap = null;
                    }
                };
            },
            () => []
        );

        useEffect(
            () => {
                if (!this.leafletReady || !this.leafletMap) {
                    return;
                }
                this._render();
            },
            () => [this.props.record.data[this.props.name], this.showRadius.value]
        );
    }

    _parseData() {
        const raw = this.props.record.data[this.props.name];
        if (!raw) {
            return { markers: [], radius_m: null };
        }
        try {
            return JSON.parse(raw);
        } catch (error) {
            console.warn("presenly_map_data is not valid JSON:", error);
            return { markers: [], radius_m: null };
        }
    }

    _initMap() {
        if (!this.mapRef.el) {
            return;
        }
        this.leafletMap = L.map(this.mapRef.el, {
            zoom: 15,
            scrollWheelZoom: true,
        });
        this.leafletMap.attributionControl.setPrefix(
            '<a href="https://leafletjs.com" title="A JavaScript library for interactive maps">Leaflet</a>'
        );
        L.tileLayer(OSM_TILE, {
            maxZoom: 19,
            attribution:
                "&copy; <a href='http://www.openstreetmap.org/copyright'>OpenStreetMap</a>",
        }).addTo(this.leafletMap);
        this._render();
        // Fix inaccurate sized map when the tab/column becomes visible later.
        setTimeout(() => this.leafletMap && this.leafletMap.invalidateSize(), 200);
    }

    _iconFor(kind) {
        const color =
            kind === "office" ? "#2e7d32" : kind === "check_in" ? "#1976d2" : "#c2185b";
        return L.divIcon({
            className: "presenly-map-marker",
            html: `<div class="presenly-map-pin" style="background-color:${color}">
                       <i class="fa ${
                           kind === "office" ? "fa-building" : "fa-user"
                       }"></i></div>`,
            iconSize: [30, 30],
            iconAnchor: [15, 15],
            popupAnchor: [0, -16],
        });
    }

    _popupFor(marker) {
        const rows = [`<strong>${marker.label || "Location"}</strong>`];
        rows.push(`<div>${marker.lat.toFixed(6)}, ${marker.lon.toFixed(6)}</div>`);
        if (marker.kind === "office") {
            if (marker.radius) {
                rows.push(`<div>Radius: ${marker.radius} m</div>`);
            }
            if (marker.accuracy_limit_m) {
                rows.push(`<div>GPS accuracy limit: ${marker.accuracy_limit_m} m</div>`);
            }
            if (marker.geofence_ready !== undefined) {
                rows.push(
                    `<div>Geofence ready: ${marker.geofence_ready ? "Yes" : "No"}</div>`
                );
            }
        } else {
            if (marker.mode) {
                const modeLabel =
                    marker.mode === "wfa" ? "Work From Anywhere" : "On-Site";
                rows.push(`<div>Mode: ${modeLabel}</div>`);
            }
            if (marker.distance_m !== undefined && marker.distance_m !== null) {
                rows.push(`<div>Distance from office: ${Math.round(marker.distance_m)} m</div>`);
            }
        }
        return rows.join("");
    }

    _render() {
        if (!this.leafletMap) {
            return;
        }
        this.mapData = this._parseData();
        // Clear previous overlays.
        for (const layer of this.markers) {
            this.leafletMap.removeLayer(layer);
        }
        this.markers = [];
        if (this.circle) {
            this.leafletMap.removeLayer(this.circle);
            this.circle = null;
        }
        if (this.line) {
            this.leafletMap.removeLayer(this.line);
            this.line = null;
        }

        const office = this.mapData.markers.find((m) => m.kind === "office");
        const points = [];
        for (const marker of this.mapData.markers || []) {
            const leafMarker = L.marker([marker.lat, marker.lon], {
                icon: this._iconFor(marker.kind),
            }).addTo(this.leafletMap);
            leafMarker.bindPopup(this._popupFor(marker));
            this.markers.push(leafMarker);
            points.push([marker.lat, marker.lon]);
        }

        // Geofence radius circle around the office.
        if (
            office &&
            (this.mapData.radius_m !== undefined && this.mapData.radius_m !== null) &&
            this.showRadius.value
        ) {
            this.circle = L.circle([office.lat, office.lon], {
                radius: this.mapData.radius_m,
                color: "#2e7d32",
                weight: 2,
                fillColor: "#4caf50",
                fillOpacity: 0.15,
            }).addTo(this.leafletMap);
        }

        // Dashed connector office -> check_in.
        const checkIn = this.mapData.markers.find((m) => m.kind === "check_in");
        if (office && checkIn) {
            this.line = L.polyline(
                [
                    [office.lat, office.lon],
                    [checkIn.lat, checkIn.lon],
                ],
                { color: "#1976d2", weight: 2, dashArray: "6,6", opacity: 0.7 }
            ).addTo(this.leafletMap);
        }

        if (points.length) {
            this.leafletMap.fitBounds(L.latLngBounds(points).pad(0.3), {
                maxZoom: 17,
            });
        } else {
            this.leafletMap.setView([-6.2, 106.8], 6);
        }
        setTimeout(() => this.leafletMap && this.leafletMap.invalidateSize(), 50);
    }
}

export const presenlyMapViewer = {
    component: PresenlyMapViewer,
    extractProps: () => ({ record: false }),
    supportedTypes: ["char", "text"],
};
registry.category("fields").add("presenly_map_viewer", presenlyMapViewer);