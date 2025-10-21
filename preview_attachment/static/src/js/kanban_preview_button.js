/**
 * Botón de previsualización PDF en kanban para ir.attachment
 * GitHub Copilot - siguiendo agents.md
 */
odoo.define('preview_attachment.kanban_preview_button', [
    'web.core',
    'web.KanbanRecord',
    'web.Dialog',
    'web.rpc',
], function (require) {
    "use strict";
    var core = require('web.core');
    var KanbanRecord = require('web.KanbanRecord');
    var Dialog = require('web.Dialog');
    var rpc = require('web.rpc');

    KanbanRecord.include({
        events: Object.assign({}, KanbanRecord.prototype.events, {
            'click .o_kanban_attachment_preview': '_onPreviewAttachment',
        }),
        _onPreviewAttachment: function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            var self = this;
            var recordId = this.record.id.raw_value;
            // Llama al método preview_attachment para obtener la acción
            this._rpc({
                model: 'ir.attachment',
                method: 'preview_attachment',
                args: [[recordId]],
            }).then(function (action) {
                if (action) {
                    self.do_action(action);
                } else {
                    Dialog.alert(self, 'No se puede previsualizar este adjunto.');
                }
            });
        },
    });
});
