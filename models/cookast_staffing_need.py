# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import math
from odoo.exceptions import ValidationError


class CookastStaffingNeed(models.Model):
    _name = 'cookast.staffing.need'
    _description = 'Necesidad de personal por turno'
    _rec_name = 'display_name'
    _order = 'forecast_id'
    
    # ── Relación principal ────────────────────────────────────────────────────
    forecast_id = fields.Many2one(
        'cookast.forecast',
        string='Previsión',
        required=True,
        ondelete='cascade',
        index=True,
    )
    display_name = fields.Char(
        string='Descripción',
        compute='_compute_display_name',
        store=True,
    )
    
    # ── Datos del turno (relacionados) ────────────────────────────────────────
    date = fields.Date(related='forecast_id.date', store=True)
    shift = fields.Selection(related='forecast_id.shift', store=True)
    local_id = fields.Many2one(related='forecast_id.local_id', store=True)
    forecast_revenue = fields.Monetary(related='forecast_id.forecast_revenue', store=True)
    currency_id = fields.Many2one(related='forecast_id.currency_id')
    
    # ── Cálculo de personal necesario ─────────────────────────────────────────
    total_persons = fields.Integer(
        string='Total personas',
        compute='_compute_staffing',
        store=True,
    )
    responsible_qty = fields.Integer(
        string='Responsables (R)',
        compute='_compute_staffing',
        store=True,
    )
    senior_qty = fields.Integer(
        string='Senior (S)',
        compute='_compute_staffing',
        store=True,
    )
    junior_qty = fields.Integer(
        string='Junior (J)',
        compute='_compute_staffing',
        store=True,
    )
    
    # ── Coste estimado ────────────────────────────────────────────────────────
    estimated_cost = fields.Monetary(
        string='Coste estimado (€)',
        currency_field='currency_id',
        compute='_compute_estimated_cost',
        store=True,
    )
    
    # ── Nivel de tensión del turno ────────────────────────────────────────────
    stress_level = fields.Selection([
        ('low', 'Bajo'),
        ('medium', 'Medio'),
        ('high', 'Alto'),
        ('critical', 'Crítico'),
    ], string='Nivel de tensión', compute='_compute_stress_level', store=True)
    
    # ── Planificaciones generadas ─────────────────────────────────────────────
    shift_plan_ids = fields.One2many(
        'cookast.shift.plan',
        'staffing_need_id',
        string='Asignaciones generadas',
    )
    
    _sql_constraints = [
        ('unique_staffing_need', 'UNIQUE(forecast_id)',
         'Ya existe una necesidad de personal para esta previsión.'),
    ]

    @api.constrains('forecast_id')
    def _check_unique_staffing_need(self):
        for rec in self:
            duplicate = self.search([
                ('forecast_id', '=', rec.forecast_id.id),
                ('id', '!=', rec.id),
            ])
            if duplicate:
                raise ValidationError((
                    'Ya existe una necesidad de personal para esta previsión.'
                ))
    
    # ── Computes ──────────────────────────────────────────────────────────────
    @api.depends('forecast_id', 'forecast_id.display_name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"Personal: {rec.forecast_id.display_name or '—'}"
    
    @api.depends('forecast_revenue')
    def _compute_staffing(self):
        """Calcula el personal necesario basado en forecast_revenue."""
        config = self.env['cookast.forecast.config'].search([('active', '=', True)], limit=1)
        ratio = config.ratio_eur_per_person if config else 375.0
        
        for rec in self:
            revenue = rec.forecast_revenue or 0.0
            
            if revenue <= 0:
                rec.total_persons = 0
                rec.responsible_qty = 0
                rec.senior_qty = 0
                rec.junior_qty = 0
                continue
            
            # Total personas: ceil(revenue / ratio), mínimo 2, máximo 9
            total = max(2, min(9, math.ceil(revenue / ratio)))
            rec.total_persons = total
            
            # Siempre 1 responsable si total >= 2
            resp = 1 if total >= 2 else 0
            rec.responsible_qty = resp
            
            # Resto se distribuye: 60% senior, 40% junior (redondeo)
            remaining = total - resp
            senior = math.ceil(remaining * 0.6)
            junior = remaining - senior
            
            rec.senior_qty = senior
            rec.junior_qty = junior
    
    @api.depends('responsible_qty', 'senior_qty', 'junior_qty')
    def _compute_estimated_cost(self):
        """Coste estimado usando costes medios por nivel."""
        # Costes medios por nivel (podrían venir de configuración)
        avg_cost_resp = 16.50
        avg_cost_senior = 12.50
        avg_cost_junior = 10.50
        hours_per_shift = 5.0  # Duración estándar del turno
        
        for rec in self:
            cost = (
                rec.responsible_qty * avg_cost_resp * hours_per_shift +
                rec.senior_qty * avg_cost_senior * hours_per_shift +
                rec.junior_qty * avg_cost_junior * hours_per_shift
            )
            rec.estimated_cost = cost
    
    @api.depends('total_persons')
    def _compute_stress_level(self):
        """Clasifica el turno según la cantidad de personal necesario."""
        for rec in self:
            total = rec.total_persons
            if total >= 7:
                rec.stress_level = 'critical'
            elif total >= 5:
                rec.stress_level = 'high'
            elif total >= 3:
                rec.stress_level = 'medium'
            else:
                rec.stress_level = 'low'
    
    # ── Helpers ────────────────────────────────────────────────────────────────
    def _get_week_bounds(self, ref_date):
        """Devuelve (lunes, domingo) de la semana ISO de ref_date."""
        from datetime import timedelta
        monday = ref_date - timedelta(days=ref_date.weekday())
        sunday = monday + timedelta(days=6)
        return monday, sunday

    def _get_weekly_hours_map(self, employee_ids, ref_date):
        """
        Devuelve un dict {employee_id: horas_planificadas_esta_semana}
        para los empleados indicados, en la semana ISO de ref_date.
        """
        monday, sunday = self._get_week_bounds(ref_date)
        plans = self.env['cookast.shift.plan'].search([
            ('employee_id', 'in', employee_ids),
            ('date', '>=', monday),
            ('date', '<=', sunday),
        ])
        hours_map = {}
        for plan in plans:
            hours_map[plan.employee_id.id] = (
                hours_map.get(plan.employee_id.id, 0.0) + plan.planned_hours
            )
        return hours_map

    def _filter_by_weekly_capacity(self, employees, hours_map, shift_hours):
        """
        Filtra empleados que aún tienen capacidad semanal para asumir
        shift_hours horas adicionales.
        """
        return employees.filtered(
            lambda e: (
                hours_map.get(e.id, 0.0) + shift_hours
                <= (e.cookast_max_weekly_hours or 40.0)
            )
        )

    # ── Métodos de acción ─────────────────────────────────────────────────────
    def action_generate_shift_plans(self):
        """
        Genera registros en cookast.shift.plan asignando empleados disponibles
        según el nivel necesario (R/S/J).
        Respeta las horas máximas semanales de cada empleado.
        """
        self.ensure_one()
        
        forecast_date = self.forecast_id.date
        shift_hours = 5.0  # Horas estándar por turno
        
        # 1) Eliminar asignaciones previas ANTES de calcular nada
        self.shift_plan_ids.unlink()
        
        # 2) Empleados que ya tienen turno en este día + turno concreto
        #    (excluimos los que acabamos de borrar, ya no existen)
        busy_employee_ids = self.env['cookast.shift.plan'].search([
            ('date', '=', forecast_date),
            ('shift', '=', self.forecast_id.shift),
        ]).mapped('employee_id.id')
        
        # 3) Buscar empleados disponibles por nivel (no ocupados en este turno)
        employees_resp = self.env['hr.employee'].search([
            ('cookast_level', '=', 'responsible'),
            ('id', 'not in', busy_employee_ids),
        ])
        employees_senior = self.env['hr.employee'].search([
            ('cookast_level', '=', 'senior'),
            ('id', 'not in', busy_employee_ids),
        ])
        employees_junior = self.env['hr.employee'].search([
            ('cookast_level', '=', 'junior'),
            ('id', 'not in', busy_employee_ids),
        ])
        
        # 4) Calcular horas semanales ya planificadas (estado limpio)
        all_candidate_ids = (employees_resp | employees_senior | employees_junior).ids
        hours_map = self._get_weekly_hours_map(all_candidate_ids, forecast_date)
        
        # 5) Filtrar por capacidad semanal
        employees_resp = self._filter_by_weekly_capacity(
            employees_resp, hours_map, shift_hours
        )
        employees_senior = self._filter_by_weekly_capacity(
            employees_senior, hours_map, shift_hours
        )
        employees_junior = self._filter_by_weekly_capacity(
            employees_junior, hours_map, shift_hours
        )
        
        # Control de empleados ya asignados en esta ejecución
        assigned_employees = set()
        
        def _assign(pool, qty, role):
            """Asigna hasta qty empleados del pool con el rol indicado."""
            for _i in range(qty):
                available = pool.filtered(lambda e: e.id not in assigned_employees)
                if available:
                    employee = available[0]
                    assigned_employees.add(employee.id)
                    # Actualizar hours_map para la siguiente iteración
                    hours_map[employee.id] = (
                        hours_map.get(employee.id, 0.0) + shift_hours
                    )
                    self.env['cookast.shift.plan'].create({
                        'forecast_id': self.forecast_id.id,
                        'staffing_need_id': self.id,
                        'employee_id': employee.id,
                        'role': role,
                        'planned_hours': shift_hours,
                    })
        
        _assign(employees_resp, self.responsible_qty, 'chef')
        _assign(employees_senior, self.senior_qty, 'waiter')
        _assign(employees_junior, self.junior_qty, 'runner')
        
        # Mensaje de resultado
        total_needed = self.responsible_qty + self.senior_qty + self.junior_qty
        total_assigned = len(assigned_employees)
        
        # Invalidar caché para que el One2many se actualice
        self.invalidate_recordset(['shift_plan_ids'])
        
        if total_assigned < total_needed:
            message = _('Solo se pudieron asignar %(assigned)d de %(needed)d empleados. '
                       'Puede que no haya suficientes empleados disponibles o que '
                       'algunos superen sus horas máximas semanales.') % {
                'assigned': total_assigned,
                'needed': total_needed,
            }
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Advertencia'),
                    'message': message,
                    'type': 'warning',
                    'sticky': True,
                    'next': {
                        'type': 'ir.actions.act_window',
                        'res_model': 'cookast.staffing.need',
                        'res_id': self.id,
                        'view_mode': 'form',
                        'target': 'current',
                    },
                },
            }
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'cookast.staffing.need',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }