# -*- coding: utf-8 -*-
from odoo import models, api

class MailMessage(models.Model):
    _inherit = 'mail.message'

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        try:
            bot_user = self.env.ref('cookast_ai.bot_user', raise_if_not_found=False)
            channel = self.env.ref('cookast_ai.channel_ai_assistant', raise_if_not_found=False)
        except Exception:
            bot_user = None
            channel = None

        if bot_user and channel:
            for msg in messages:
                # Verificar si es en el canal del bot y no es un mensaje del propio bot
                if msg.model == 'discuss.channel' and msg.res_id == channel.id and msg.author_id.id != bot_user.partner_id.id:
                    # En Odoo 19, procesarlo directamente (sincrónico). 
                    # Podríamos usar env.cr.postcommit.add pero el bot requiere enviar mensaje, mejor procesar directamente
                    self.env['cookast.ai.bot.engine']._handle_message(msg)
                    
        return messages
