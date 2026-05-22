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
    provider = fields.Selection([
        ('ollama', 'Ollama (Local)'),
        ('openai', 'OpenAI'),
        ('deepseek', 'DeepSeek'),
        ('anthropic', 'Anthropic'),
        ('google', 'Google Gemini')
    ], string="Proveedor de IA", default='ollama', required=True)
    
    api_key = fields.Char(string="API Key", help="Clave de acceso para proveedores externos")
    endpoint = fields.Char(
        string="Endpoint API",
        default="http://localhost:11434",
        help="URL base para Ollama o endpoints personalizados. Dejar vacío si se usa proveedor estándar.",
    )
    model_name = fields.Char(
        string="Modelo",
        default="llama3.1:8b",
        required=True,
        help="Nombre del modelo (ej. llama3.1:8b, gpt-4o-mini, claude-3-haiku-20240307, gemini-1.5-flash)",
    )
    temperature = fields.Float(
        string="Temperatura", default=0.1, help="0 = determinista, 1 = creativo"
    )
    max_tokens = fields.Integer(string="Máx. tokens de respuesta", default=300)
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
                    "provider": "ollama",
                    "endpoint": "http://172.23.0.1:11434",
                    "model_name": "llama3.1:8b",
                    "temperature": 0.1,
                    "max_tokens": 300,
                }
            )
        return config

    def _build_ai_payload(self, prompt):
        """Construye el payload, url y headers según el proveedor."""
        url = ""
        headers = {'Content-Type': 'application/json'}
        payload = {}
        
        if self.provider == 'ollama':
            url = f"{self.endpoint.rstrip('/')}/api/generate"
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                },
            }
        elif self.provider in ['openai', 'deepseek']:
            url = "https://api.openai.com/v1/chat/completions" if self.provider == 'openai' else "https://api.deepseek.com/v1/chat/completions"
            headers['Authorization'] = f"Bearer {self.api_key or ''}"
            payload = {
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
        elif self.provider == 'anthropic':
            url = "https://api.anthropic.com/v1/messages"
            headers['x-api-key'] = self.api_key or ''
            headers['anthropic-version'] = '2023-06-01'
            payload = {
                "model": self.model_name,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "messages": [{"role": "user", "content": prompt}]
            }
        elif self.provider == 'google':
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key or ''}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": self.temperature,
                    "maxOutputTokens": self.max_tokens,
                }
            }
            
        return url, headers, payload

    def _query_ai(self, prompt):
        """Envía un prompt al modelo configurado y devuelve la respuesta (texto)."""
        config = self if self.ids else self._get_active_config()
        
        url, headers, payload = config._build_ai_payload(prompt)
        
        try:
            _logger.info("Cookast AI: consultando proveedor %s (modelo %s)...", config.provider, config.model_name)
            start = fields.Datetime.now()
            resp = requests.post(url, json=payload, headers=headers, timeout=120)
            
            if resp.status_code != 200:
                _logger.error("Error AI API: %s - %s", resp.status_code, resp.text)
                
            resp.raise_for_status()
            data = resp.json()
            
            response_text = ""
            tokens_used = 0
            
            if config.provider == 'ollama':
                response_text = data.get("response", "")
                tokens_used = data.get("eval_count", 0)
            elif config.provider in ['openai', 'deepseek']:
                response_text = data.get('choices', [{}])[0].get('message', {}).get('content', '')
                tokens_used = data.get('usage', {}).get('completion_tokens', 0)
            elif config.provider == 'anthropic':
                content = data.get('content', [])
                if content:
                    response_text = content[0].get('text', '')
                tokens_used = data.get('usage', {}).get('output_tokens', 0)
            elif config.provider == 'google':
                candidates = data.get('candidates', [])
                if candidates:
                    parts = candidates[0].get('content', {}).get('parts', [])
                    if parts:
                        response_text = parts[0].get('text', '')
                tokens_used = data.get('usageMetadata', {}).get('candidatesTokenCount', 0)
                
            duration = (fields.Datetime.now() - start).total_seconds()
            
            self.env["cookast.ai.log"].create(
                {
                    "config_id": config.id,
                    "prompt": prompt,
                    "response": response_text,
                    "model_used": config.model_name,
                    "tokens": tokens_used,
                    "duration": duration,
                }
            )
            return response_text
            
        except Exception as e:
            _logger.error("Cookast AI: error de conexión con %s: %s", config.provider, e)
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
            raise UserError(_("Error al conectar con la API de IA (%s):\n%s") % (config.provider, str(e)))

    def action_test_connection(self):
        """Botón de prueba desde la configuración."""
        self.ensure_one()
        response = self._query_ai("Responde exactamente con la palabra 'OK'")
        if "OK" in response:
            raise UserError(_("Conexión exitosa.\nRespuesta: %s") % response)
        else:
            raise UserError(_("Respuesta recibida:\n%s") % response)
