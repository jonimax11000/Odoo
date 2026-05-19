from odoo import models, fields


class CookastAILog(models.Model):
    _name = "cookast.ai.log"
    _description = "Log de consultas IA Cookast"
    _order = "create_date desc"

    config_id = fields.Many2one(
        "cookast.ai.config",
        string="Configuración IA",
        required=True,
        ondelete="cascade",
    )
    prompt = fields.Text(string="Prompt enviado")
    response = fields.Text(string="Respuesta recibida")
    model_used = fields.Char(string="Modelo utilizado")
    tokens = fields.Integer(string="Tokens generados")
    duration = fields.Float(string="Duración (s)")
    create_date = fields.Datetime(
        string="Fecha de consulta", default=fields.Datetime.now
    )
