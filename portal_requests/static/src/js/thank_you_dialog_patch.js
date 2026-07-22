/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ThankYouDialog } from "@sign/dialogs/thank_you_dialog";

// AICIA (reunión 22/07/2026): el envío por correo del documento firmado está
// desactivado para las aprobaciones de documentos (ver sign_request_inherit.
// _send_completed_documents). El mensaje por defecto del diálogo de firma
// ("You will get the signed document by email.") es, por tanto, incorrecto.
// Lo sustituimos por un mensaje neutro cuando no se pasa un mensaje explícito.
patch(ThankYouDialog.prototype, {
    setup() {
        super.setup();
        if (!this.props.message) {
            this.message = _t("El documento se ha firmado correctamente.");
        }
    },
});
