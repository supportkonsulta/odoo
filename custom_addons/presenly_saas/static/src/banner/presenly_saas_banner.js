import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const STORAGE_PREFIX = "presenly_saas_banner_dismissed";
const SUBSCRIPTION_ACTION = "presenly_saas.action_presenly_saas_open_subscription";

/**
 * Subscription notice for the backend.
 *
 * It reads one payload at boot and stays quiet otherwise: a status notice must
 * never turn into a source of errors, so a failed call is logged and hidden
 * rather than surfaced. The severity, and the reason it is showing, come from
 * the server so the wording stays in one place.
 */
export class PresenlySaasBanner extends Component {
    static template = "presenly_saas.Banner";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            payload: null,
            dismissed: false,
        });

        onWillStart(async () => {
            await this.loadPayload();
        });
    }

    async loadPayload() {
        let payload = null;
        try {
            payload = await this.orm.call(
                "presenly.saas.subscription",
                "get_banner_payload",
                []
            );
        } catch (error) {
            console.warn(
                "[presenly_saas] subscription banner unavailable, staying hidden",
                error
            );
        }
        this.state.payload = payload;
        this.state.dismissed = this._isDismissed(this._dismissKey());
    }

    _dismissKey() {
        const payload = this.state.payload;
        if (!payload || !payload.visible) {
            return false;
        }
        return [
            STORAGE_PREFIX,
            payload.tenant_code || "-",
            payload.status,
            payload.state_source,
            payload.severity,
        ].join(":");
    }

    _isDismissed(key) {
        if (!key) {
            return false;
        }
        try {
            return window.sessionStorage.getItem(key) === "1";
        } catch {
            return false;
        }
    }

    dismiss() {
        const key = this._dismissKey();
        if (key) {
            try {
                window.sessionStorage.setItem(key, "1");
            } catch {
                // Private mode and locked-down browsers: dismissing stays local.
            }
        }
        this.state.dismissed = true;
    }

    async openDetails() {
        try {
            await this.action.doAction(SUBSCRIPTION_ACTION);
        } catch (error) {
            console.warn("[presenly_saas] could not open the subscription page", error);
        }
    }

    get visible() {
        return Boolean(this.state.payload?.visible) && !this.state.dismissed;
    }

    get severityClass() {
        return this.state.payload?.severity === "danger" ? "danger" : "warning";
    }

    get hasDetails() {
        return Boolean(this.state.payload?.is_manager);
    }

    get openLabel() {
        return _t("Open subscription");
    }

    get dismissLabel() {
        return _t("Dismiss subscription notice");
    }

    get message() {
        const payload = this.state.payload;
        if (!payload) {
            return "";
        }
        if (payload.state_source === "unreachable") {
            return _t("The Presenly SaaS server has never confirmed this subscription.");
        }
        if (payload.state_source === "cached") {
            return _t(
                "Not confirmed by the Presenly SaaS server since %s. Last reported status: %s.",
                payload.last_sync_at ? payload.last_sync_at.slice(0, 10) : "-",
                payload.status_label
            );
        }
        if (payload.status === "expired" || payload.status === "suspended") {
            return _t("This subscription is %s.", payload.status_label.toLowerCase());
        }
        if (payload.status === "trial") {
            return _t("Trial ends in %s day(s).", payload.days_remaining);
        }
        return _t("Subscription renews in %s day(s).", payload.days_remaining);
    }
}

registry.category("main_components").add("presenly_saas.Banner", {
    Component: PresenlySaasBanner,
});
