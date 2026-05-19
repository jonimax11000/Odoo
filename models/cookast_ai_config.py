# -*- coding: utf-8 -*-
import logging
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CookastAIConfig(models.Model):
    _name = "cookast.ai.config"
    _description = "Configuración de IA Cookast"
    _rec_name = "name"

    name = fields.Char(string="Nombre", default="Configuración IA", required=True)
    ollama_endpoint = fields.Char(
        string="Endpoint de Ollama",
        default="http://localhost:11434",
        required=True,
        help="URL base del servidor Ollama (ej. http://localhost:11434)",
    )
    model_name = fields.Char(
        string="Modelo",
        default="llama3.1:8b",
        required=True,
        help="Nombre del modelo en Ollama (ej. llama3.1:8b)",
    )
    temperature = fields.Float(
        string="Temperatura", default=0.1, help="0 = determinista, 1 = creativo"
    )
    max_tokens = fields.Integer(string="Máx. tokens de respuesta", default=100)
    active = fields.Boolean(string="Activo", default=True)
    company_id = fields.Many2one(
        "res.company", string="Compañía", default=lambda self: self.env.company
    )

    @api.model
    def _get_active_config(self):
        """Obtiene la configuración activa o la crea con valores predeterminados."""
        config = self.search([("active", "=", True)], limit=1)
        if not config:
            config = self.create(
                {
                    "name": "Configuración IA",
                    "ollama_endpoint": "http://172.23.0.1:11434",
                    "model_name": "llama3.1:8b",
                    "temperature": 0.1,
                    "max_tokens": 100,
                }
            )
        return config

    def _query_ai(self, prompt):
        """Envía un prompt al modelo y devuelve la respuesta (texto)."""
        config = self if self.ids else self._get_active_config()
        url = f"{config.ollama_endpoint.rstrip('/')}/api/generate"
        payload = {
            "model": config.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": config.temperature,
                "num_predict": config.max_tokens,
            },
        }
        try:
            _logger.info("Cookast AI: consultando %s...", config.model_name)
            start = fields.Datetime.now()
            resp = requests.post(url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            response_text = data.get("response", "")
            duration = (fields.Datetime.now() - start).total_seconds()
            self.env["cookast.ai.log"].create(
                {
                    "config_id": config.id,
                    "prompt": prompt,
                    "response": response_text,
                    "model_used": config.model_name,
                    "tokens": data.get("eval_count", 0),
                    "duration": duration,
                }
            )
            return response_text
        except requests.exceptions.RequestException as e:
            _logger.error("Cookast AI: error de conexión: %s", e)
            self.env["cookast.ai.log"].create(
                {
                    "config_id": config.id,
                    "prompt": prompt,
                    "response": f"ERROR: {str(e)}",
                    "model_used": config.model_name,
                    "tokens": 0,
                    "duration": 0,
                }
            )
            raise UserError(_("Error al conectar con Ollama:\n%s") % str(e))

    def action_test_connection(self):
        """Botón de prueba desde la configuración."""
        self.ensure_one()
        response = self._query_ai("Responde exactamente con la palabra 'OK'")
        if "OK" in response:
            raise UserError(_("Conexión exitosa.\nRespuesta: %s") % response)
        else:
            raise UserError(_("Respuesta inesperada: %s") % response)
