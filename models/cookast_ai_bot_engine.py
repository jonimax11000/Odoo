# -*- coding: utf-8 -*-
from odoo import models, api
from odoo.tools import html2plaintext
from markupsafe import Markup
import logging
import html
import re

_logger = logging.getLogger(__name__)

class CookastAIBotEngine(models.AbstractModel):
    _name = 'cookast.ai.bot.engine'
    _description = 'Cookast AI Bot Engine'

    @api.model
    def _handle_message(self, message):
        """Procesa un mensaje de discuss.channel y genera una respuesta de IA"""
        bot_user = self.env.ref('cookast_ai.bot_user', raise_if_not_found=False)
        channel = self.env.ref('cookast_ai.channel_ai_assistant', raise_if_not_found=False)

        if not bot_user or not channel:
            return

        # Evitar bucles infinitos: el bot no se responde a sí mismo
        if message.author_id.id == bot_user.partner_id.id:
            return

        if message.body:
            # Extraer texto plano del HTML (strip HTML tags)
            text = html2plaintext(message.body).strip()
            
            if not text:
                return

            try:
                # Determinar el usuario real que mandó el mensaje
                user_id = message.author_id.user_ids[0].id if message.author_id.user_ids else self.env.uid
                
                # Procesar la consulta usando la lógica existente en cookast_ai_chat
                response = self.env['cookast.ai.chat']._process_query(user_id, text)
                
                # Convertir Markdown a HTML básico de forma segura
                safe_response = html.escape(response)
                safe_response = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', safe_response)
                safe_response = safe_response.replace('\n', '<br/>')
                
                # Publicar la respuesta en el canal como el bot
                channel.with_user(bot_user).message_post(
                    body=Markup(safe_response),
                    author_id=bot_user.partner_id.id,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )
            except Exception as e:
                _logger.error("Error al procesar mensaje de IA: %s", e)
