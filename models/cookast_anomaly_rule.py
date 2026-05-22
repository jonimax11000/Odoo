# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import timedelta

class CookastAnomalyRule(models.AbstractModel):
    _inherit = 'cookast.anomaly.rule'

    def _notify_alert(self, alert_record):
        if alert_record.notification_sent:
            return

        # Determine user to assign
        assigned_user = False
        res_model = alert_record.model
        res_id = alert_record.res_id

        if res_model == 'cookast.forecast':
            record = self.env[res_model].browse(res_id)
            if record.exists() and record.local_id and record.local_id.manager_id:
                assigned_user = record.local_id.manager_id
        elif res_model == 'cookast.staffing.need':
            record = self.env[res_model].browse(res_id)
            if record.exists() and record.forecast_id and record.forecast_id.local_id and record.forecast_id.local_id.manager_id:
                assigned_user = record.forecast_id.local_id.manager_id
        elif res_model == 'cookast.material.need':
            record = self.env[res_model].browse(res_id)
            if record.exists() and record.local_id and record.local_id.manager_id:
                assigned_user = record.local_id.manager_id

        if not assigned_user:
            assigned_user = self.env.ref('base.user_admin', raise_if_not_found=False) or self.env.user

        # Create activity
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            # Fallback if mail type is missing
            activity_type = self.env['mail.activity.type'].search([], limit=1)
            
        model_id = self.env['ir.model']._get_id(res_model)
        
        if model_id and activity_type:
            date_str = alert_record.create_date.strftime('%Y-%m-%d') if alert_record.create_date else fields.Date.context_today(self).strftime('%Y-%m-%d')
            summary_text = f"{self.name} anomaly ({date_str})"
                
            self.env['mail.activity'].create({
                'activity_type_id': activity_type.id,
                'user_id': assigned_user.id,
                'res_model_id': model_id,
                'res_id': res_id,
                'summary': summary_text,
                'note': alert_record.message,
                'date_deadline': fields.Date.today() + timedelta(days=1),
            })
            
            # Post chatter message
            record = self.env[res_model].browse(res_id)
            if record.exists() and hasattr(record, 'message_post'):
                record.message_post(body=alert_record.message)
                
        alert_record.notification_sent = True
