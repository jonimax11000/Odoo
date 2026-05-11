from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta, time
import pytz

class ShiftPlanningWizard(models.TransientModel):
    _name = 'shift.planning.wizard'
    _description = 'Shift Planning Wizard'

    template_id = fields.Many2one('shift.template', string='Shift Template', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    
    start_date = fields.Date(string='Start Date', required=True, default=fields.Date.context_today)
    end_date = fields.Date(string='End Date', required=True)
    
    # Weekdays to repeat
    repeat_mon = fields.Boolean(string='Monday', default=True)
    repeat_tue = fields.Boolean(string='Tuesday', default=True)
    repeat_wed = fields.Boolean(string='Wednesday', default=True)
    repeat_thu = fields.Boolean(string='Thursday', default=True)
    repeat_fri = fields.Boolean(string='Friday', default=True)
    repeat_sat = fields.Boolean(string='Saturday', default=False)
    repeat_sun = fields.Boolean(string='Sunday', default=False)

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for record in self:
            if record.start_date > record.end_date:
                raise ValidationError(_("The start date must be before or equal to the end date."))

    def action_generate_shifts(self):
        self.ensure_one()
        current_date = self.start_date
        
        # User timezone or UTC
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')
        
        slots_to_create = []
        
        while current_date <= self.end_date:
            weekday = current_date.weekday()
            
            # Check if we should create a shift for this weekday
            is_valid_day = False
            if weekday == 0 and self.repeat_mon: is_valid_day = True
            elif weekday == 1 and self.repeat_tue: is_valid_day = True
            elif weekday == 2 and self.repeat_wed: is_valid_day = True
            elif weekday == 3 and self.repeat_thu: is_valid_day = True
            elif weekday == 4 and self.repeat_fri: is_valid_day = True
            elif weekday == 5 and self.repeat_sat: is_valid_day = True
            elif weekday == 6 and self.repeat_sun: is_valid_day = True
            
            if is_valid_day:
                # Convert float time to hours and minutes
                start_hour = int(self.template_id.start_time)
                start_minute = int((self.template_id.start_time - start_hour) * 60)
                
                end_hour = int(self.template_id.end_time)
                end_minute = int((self.template_id.end_time - end_hour) * 60)
                
                # Create localized datetime and convert to UTC
                start_dt_local = user_tz.localize(datetime.combine(current_date, time(start_hour, start_minute)))
                start_dt_utc = start_dt_local.astimezone(pytz.UTC).replace(tzinfo=None)
                
                if self.template_id.end_time < self.template_id.start_time:
                    # crosses midnight
                    end_date_time = current_date + timedelta(days=1)
                else:
                    end_date_time = current_date
                    
                end_dt_local = user_tz.localize(datetime.combine(end_date_time, time(end_hour, end_minute)))
                end_dt_utc = end_dt_local.astimezone(pytz.UTC).replace(tzinfo=None)
                
                slots_to_create.append({
                    'name': self.template_id.name,
                    'employee_id': self.employee_id.id,
                    'start_datetime': start_dt_utc,
                    'end_datetime': end_dt_utc,
                    'job_id': self.template_id.job_id.id,
                    'project_id': self.template_id.project_id.id,
                    'company_id': self.template_id.company_id.id,
                    'state': 'draft',
                })
                
            current_date += timedelta(days=1)
            
        if slots_to_create:
            self.env['shift.planning.slot'].create(slots_to_create)
            
        return {'type': 'ir.actions.act_window_close'}
