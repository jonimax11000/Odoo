from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta

class ShiftAutoAssignWizard(models.TransientModel):
    _name = 'shift.auto.assign.wizard'
    _description = 'Auto Assign Shifts Wizard'

    start_date = fields.Date(string='Start Date', required=True, default=fields.Date.context_today)
    end_date = fields.Date(string='End Date', required=True, default=lambda self: fields.Date.today() + timedelta(days=7))
    employee_ids = fields.Many2many('hr.employee', string='Employees', default=lambda self: self.env['hr.employee'].search([]))

    def action_auto_assign(self):
        self.ensure_one()
        # Find all unassigned slots in the date range
        slots = self.env['shift.planning.slot'].search([
            ('employee_id', '=', False),
            ('start_datetime', '>=', self.start_date),
            ('start_datetime', '<=', self.end_date),
        ], order='start_datetime asc')

        if not slots:
            raise UserError(_("No unassigned shifts found in the selected range."))

        assigned_count = 0
        for slot in slots:
            # Candidate employees
            candidates = []
            for emp in self.employee_ids:
                # 1. Check Skills
                if slot.required_skill_ids:
                    if not all(skill in emp.shift_skill_ids for skill in slot.required_skill_ids):
                        continue
                
                # 2. Check Overlaps
                overlap = self.env['shift.planning.slot'].search_count([
                    ('employee_id', '=', emp.id),
                    ('start_datetime', '<', slot.end_datetime),
                    ('end_datetime', '>', slot.start_datetime),
                ])
                if overlap > 0:
                    continue

                # 3. Check Leaves
                leave = self.env['hr.leave'].search_count([
                    ('employee_id', '=', emp.id),
                    ('state', '=', 'validate'),
                    ('date_from', '<', slot.end_datetime),
                    ('date_to', '>', slot.start_datetime),
                ])
                if leave > 0:
                    continue

                # 4. Calculate weekly hours score (Fairness)
                # Week boundaries
                start_of_week = slot.start_datetime - timedelta(days=slot.start_datetime.weekday())
                start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
                end_of_week = start_of_week + timedelta(days=7)

                week_slots = self.env['shift.planning.slot'].search([
                    ('employee_id', '=', emp.id),
                    ('start_datetime', '>=', start_of_week),
                    ('start_datetime', '<', end_of_week),
                ])
                planned_hours = sum(week_slots.mapped('planned_hours'))
                
                # Check max hours limit
                if (planned_hours + slot.planned_hours) > emp.shift_max_weekly_hours:
                    continue

                # Score: lower is better (less loaded)
                score = planned_hours / (emp.shift_max_weekly_hours or 40.0)
                candidates.append((emp, score))

            if candidates:
                # Sort by score ascending (Equity)
                candidates.sort(key=lambda x: x[1])
                best_emp = candidates[0][0]
                slot.write({'employee_id': best_emp.id})
                assigned_count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Auto-assignment Complete'),
                'message': _('Successfully assigned %d shifts.') % assigned_count,
                'type': 'success',
                'sticky': False,
            }
        }
