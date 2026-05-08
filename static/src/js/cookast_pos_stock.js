/** @odoo-module **/
/**
 * cookast_pos_stock.js
 *
 * Bloqueo de ventas en el TPV cuando faltan ingredientes en stock.
 *
 * Parchea el PaymentScreen de Odoo 19 POS para interceptar la validación
 * del pedido y llamar al backend antes de procesar el pago.
 *
 * Si algún ingrediente (o producto simple) no tiene suficiente stock
 * en el almacén del local, se muestra un diálogo de error y se impide
 * el pago hasta que se corrija el pedido.
 */

import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.notification = useService("notification");
    },

    /**
     * Intercepta la validación del pedido.
     * Primero comprueba stock; si hay problemas, muestra el error y bloquea.
     */
    async validateOrder(isForceValidate) {
        const order = this.pos.get_order();
        if (!order) {
            return super.validateOrder(isForceValidate);
        }

        // Construir lista de líneas para enviar al backend
        const lines = order.get_orderlines()
            .filter(line => line.get_quantity() > 0)
            .map(line => ({
                product_id: line.get_product().id,
                qty: line.get_quantity(),
            }));

        if (lines.length === 0) {
            return super.validateOrder(isForceValidate);
        }

        const configId = this.pos.config.id;

        try {
            const result = await this.orm.call(
                "pos.order",
                "check_ingredients_availability",
                [lines, configId],
                {}
            );

            if (!result.ok && result.errors && result.errors.length > 0) {
                // Construir mensaje de error detallado
                this._showStockError(result.errors);
                return;   // Bloquear: no llamar al super
            }
        } catch (e) {
            // Si el RPC falla (e.g., timeout), loguear y dejar pasar
            // para no bloquear el TPV por un error de comunicación
            console.warn("[Cookast] Error al verificar stock de ingredientes:", e);
        }

        // Todo OK → flujo normal de validación
        return super.validateOrder(isForceValidate);
    },

    /**
     * Muestra el diálogo de error de stock con todos los ingredientes
     * que faltan, indicando cantidad disponible vs necesaria.
     */
    _showStockError(errors) {
        // Agrupar errores por producto padre
        const byProduct = {};
        for (const err of errors) {
            const key = err.product;
            if (!byProduct[key]) byProduct[key] = [];
            byProduct[key].push(err);
        }

        // Construir líneas de texto del mensaje
        const lines = [];
        for (const [product, errs] of Object.entries(byProduct)) {
            for (const err of errs) {
                if (err.is_ingredient) {
                    lines.push(
                        `• ${product} → ${err.ingredient}: ` +
                        `${_t("necesario")} ${err.needed} ${err.uom}, ` +
                        `${_t("disponible")} ${err.available} ${err.uom}`
                    );
                } else {
                    lines.push(
                        `• ${err.ingredient}: ` +
                        `${_t("necesario")} ${err.needed} ${err.uom}, ` +
                        `${_t("disponible")} ${err.available} ${err.uom}`
                    );
                }
            }
        }

        const message = lines.join("\n");

        // Usar el sistema de notificaciones del POS (popup nativo)
        this.pos.env.services.dialog.add(CookastStockErrorDialog, {
            title: _t("❌ Stock insuficiente — Venta bloqueada"),
            message: message,
        });
    },
});


/**
 * Diálogo de error de stock personalizado.
 * Muestra la lista de ingredientes sin stock con formato claro.
 */
import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class CookastStockErrorDialog extends Component {
    static template = "cookast.StockErrorDialog";
    static components = { Dialog };
    static props = {
        title: String,
        message: String,
        close: Function,
    };
}
