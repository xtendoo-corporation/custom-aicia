from odoo import fields, models, api, _

class ReportCertificateExtension(models.Model):
    _inherit = "report.certificate"

    user_ids = fields.One2many(
        string="Usuarios autorizados",
        comodel_name="res.users",
        inverse_name="certificate_id",  # Este campo deberá crearse en res.users
        help="Usuarios autorizados para utilizar este certificado",
    )
