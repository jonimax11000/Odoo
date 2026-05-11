# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import math
from datetime import timedelta
from odoo.exceptions import ValidationError

import logging
_logger = logging.getLogger(__name__)


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
    planning_slot_ids = fields.One2many(
        related='forecast_id.planning_slot_ids',
        readonly=False,
    )
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
        avg_cost_resp = 16.50
        avg_cost_senior = 12.50
        avg_cost_junior = 10.50
        hours_per_shift = 5.0

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

    # ══════════════════════════════════════════════════════════════════════════
    # HELPERS DE DISPONIBILIDAD Y EQUIDAD
    # ══════════════════════════════════════════════════════════════════════════

    def _get_week_bounds(self, ref_date):
        """Devuelve (lunes, domingo) de la semana ISO de ref_date."""
        monday = ref_date - timedelta(days=ref_date.weekday())
        sunday = monday + timedelta(days=6)
        return monday, sunday

    def _get_weekly_hours_map(self, employee_ids, ref_date):
        """
        Devuelve un dict {employee_id: horas_planificadas_esta_semana}
        para los empleados indicados, en la semana ISO de ref_date.
        """
        monday, sunday = self._get_week_bounds(ref_date)
        plans = self.env['shift.planning.slot'].search([
            ('employee_id', 'in', employee_ids),
            ('start_datetime', '>=', monday),
            ('start_datetime', '<=', sunday),
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

    def _get_absent_employee_ids(self, target_date):
        """
        Devuelve un conjunto de IDs de empleados que tienen una ausencia
        aprobada (hr.leave) que cubre target_date.
        Soporta los módulos hr_holidays / time_off de Odoo 17+.
        """
        absent_ids = set()

        # Verificar si el módulo hr_holidays está instalado
        if 'hr.leave' not in self.env:
            return absent_ids

        try:
            leaves = self.env['hr.leave'].search([
                ('state', 'in', ['validate', 'validate1']),
                ('date_from', '<=', fields.Datetime.to_datetime(target_date).replace(
                    hour=23, minute=59, second=59)),
                ('date_to', '>=', fields.Datetime.to_datetime(target_date).replace(
                    hour=0, minute=0, second=0)),
            ])
            absent_ids = set(leaves.mapped('employee_id.id'))
        except Exception as e:
            _logger.warning('No se pudieron obtener ausencias de hr.leave: %s', e)

        return absent_ids

    # ── Sistema de puntuación de equidad ─────────────────────────────────────

    # Ventana de análisis histórico para calcular la carga de turnos
    _FAIRNESS_WEEKS_LOOKBACK = 6   # semanas hacia atrás para analizar carga

    # Penalizaciones (se suman al score: mayor score = menos prioritario)
    _PENALTY_SAME_WEEKDAY_SHIFT = 15   # mismo día semana + mismo turno (ej: 3er martes noche)
    _PENALTY_CONSECUTIVE_DAYS = 10     # días consecutivos trabajados (por día extra)
    _PENALTY_HEAVY_LOAD = 5            # empleados con > 60% de turnos posibles cubiertos

    def _build_fairness_scores(self, employees, target_date, shift):
        """
        Calcula una puntuación de equidad para cada empleado.
        Menor puntuación = más prioritario para asignar.
        """
        if not employees:
            return {}

        employee_ids = employees.ids
        today = target_date
        lookback_start = today - timedelta(weeks=self._FAIRNESS_WEEKS_LOOKBACK)
        weekday = today.weekday()  # 0=lunes, 6=domingo

        # ── Obtener todos los turnos históricos relevantes en una sola query ──
        past_plans = self.env['shift.planning.slot'].search([
            ('employee_id', 'in', employee_ids),
            ('start_datetime', '>=', lookback_start),
            ('start_datetime', '<', today),
        ])

        # Indexar por empleado
        plans_by_emp = {}  # {emp_id: [shift_plan, ...]}
        for plan in past_plans:
            plans_by_emp.setdefault(plan.employee_id.id, []).append(plan)

        # ── Máximo de turnos posibles en la ventana (referencia para carga) ──
        # Nº de semanas * 2 turnos/día * 7 días (aproximación superior)
        max_possible_shifts = self._FAIRNESS_WEEKS_LOOKBACK * 2 * 7

        scores = {}
        for emp in employees:
            emp_plans = plans_by_emp.get(emp.id, [])
            score = 0.0

            # ── Criterio 1: repetición mismo día-semana + mismo turno ──────
            def check_shift(p):
                if getattr(p, 'cookast_forecast_id', False):
                    return p.cookast_forecast_id.shift == shift
                return ('lunch' if p.start_datetime.hour < 17 else 'dinner') == shift

            same_weekday_same_shift = sum(
                1 for p in emp_plans
                if p.start_datetime.date().weekday() == weekday and check_shift(p)
            )
            score += same_weekday_same_shift * self._PENALTY_SAME_WEEKDAY_SHIFT

            # ── Criterio 2: días consecutivos justo antes de target_date ───
            worked_dates = sorted({p.start_datetime.date() for p in emp_plans}, reverse=True)
            consecutive = 0
            check_date = today - timedelta(days=1)
            for d in worked_dates:
                if d == check_date:
                    consecutive += 1
                    check_date -= timedelta(days=1)
                elif d < check_date:
                    break
            if consecutive > 0:
                score += consecutive * self._PENALTY_CONSECUTIVE_DAYS

            # ── Criterio 3: carga global de turnos en la ventana ────────────
            total_shifts = len(emp_plans)
            load_ratio = total_shifts / max_possible_shifts if max_possible_shifts else 0
            if load_ratio > 0.6:
                score += self._PENALTY_HEAVY_LOAD

            scores[emp.id] = score

        return scores

    def _sort_by_fairness(self, employees, target_date, shift):
        """
        Ordena los empleados poniendo primero a los que tienen
        menor puntuación de equidad (= han trabajado menos recientemente,
        no tienen el mismo patrón repetitivo, no están cargados).
        """
        scores = self._build_fairness_scores(employees, target_date, shift)
        return employees.sorted(key=lambda e: scores.get(e.id, 0.0))

    # ══════════════════════════════════════════════════════════════════════════
    # MÉTODO PRINCIPAL DE GENERACIÓN DE ASIGNACIONES
    # ══════════════════════════════════════════════════════════════════════════

    def action_generate_shift_plans(self):
        """
        Genera registros en shift.planning.slot (huecos sin asignar)
        según la cantidad de personal necesario por nivel.
        """
        self.ensure_one()

        Skill = self.env['shift.skill'].sudo()
        skill_resp = Skill.search([('name', '=', 'Responsable')], limit=1)
        if not skill_resp:
            skill_resp = Skill.create({'name': 'Responsable', 'color': 2})
            
        skill_senior = Skill.search([('name', '=', 'Senior')], limit=1)
        if not skill_senior:
            skill_senior = Skill.create({'name': 'Senior', 'color': 4})
            
        skill_junior = Skill.search([('name', '=', 'Junior')], limit=1)
        if not skill_junior:
            skill_junior = Skill.create({'name': 'Junior', 'color': 6})
            
        import pytz
        from datetime import datetime, time

        user_tz = pytz.timezone(self.env.user.tz or 'UTC')
        forecast_date = self.forecast_id.date
        shift_type = self.forecast_id.shift
        
        if shift_type == 'lunch':
            start_hour, end_hour = 11, 16
        else:
            start_hour, end_hour = 19, 24
            
        start_dt_local = user_tz.localize(datetime.combine(forecast_date, time(start_hour, 0)))
        start_dt_utc = start_dt_local.astimezone(pytz.UTC).replace(tzinfo=None)
        
        if end_hour == 24:
            end_dt_local = user_tz.localize(datetime.combine(forecast_date, time(23, 59, 59)))
        else:
            end_dt_local = user_tz.localize(datetime.combine(forecast_date, time(end_hour, 0)))
        end_dt_utc = end_dt_local.astimezone(pytz.UTC).replace(tzinfo=None)
        
        # 1. Clean previous slots from this staffing need
        self.env['shift.planning.slot'].search([('cookast_forecast_id', '=', self.forecast_id.id)]).unlink()
        
        # 2. Get absent and busy employees
        absent_ids = self._get_absent_employee_ids(forecast_date)
        
        busy_employee_ids = set(self.env['shift.planning.slot'].search([
            ('start_datetime', '<', end_dt_utc),
            ('end_datetime', '>', start_dt_utc),
        ]).mapped('employee_id.id'))
        
        excluded_ids = list(absent_ids | busy_employee_ids)

        # 3. Get candidates
        local = self.forecast_id.local_id
        if local:
            local.employee_ids._sync_cookast_level_skills()
        local_employee_ids = local.employee_ids.ids if local else []

        employees_resp = self.env['hr.employee'].search([
            ('id', 'not in', excluded_ids),
            ('id', 'in', local_employee_ids),
            ('shift_skill_ids', 'in', skill_resp.ids)
        ])
        
        employees_senior = self.env['hr.employee'].search([
            ('id', 'not in', excluded_ids),
            ('id', 'in', local_employee_ids),
            ('shift_skill_ids', 'in', skill_senior.ids),
            ('id', 'not in', employees_resp.ids)
        ])
        
        employees_junior = self.env['hr.employee'].search([
            ('id', 'not in', excluded_ids),
            ('id', 'in', local_employee_ids),
            ('shift_skill_ids', 'in', skill_junior.ids),
            ('id', 'not in', (employees_resp | employees_senior).ids)
        ])
        
        # 4. Filter by weekly capacity
        all_candidate_ids = (employees_resp | employees_senior | employees_junior).ids
        hours_map = self._get_weekly_hours_map(all_candidate_ids, forecast_date)
        shift_hours = (end_dt_utc - start_dt_utc).total_seconds() / 3600.0

        employees_resp = self._filter_by_weekly_capacity(employees_resp, hours_map, shift_hours)
        employees_senior = self._filter_by_weekly_capacity(employees_senior, hours_map, shift_hours)
        employees_junior = self._filter_by_weekly_capacity(employees_junior, hours_map, shift_hours)

        # 5. Sort by fairness
        sorted_resp = list(self._sort_by_fairness(employees_resp, forecast_date, shift_type))
        sorted_senior = list(self._sort_by_fairness(employees_senior, forecast_date, shift_type))
        sorted_junior = list(self._sort_by_fairness(employees_junior, forecast_date, shift_type))
        
        Slot = self.env['shift.planning.slot']
        slots_to_create = []
        company_id = self.env.company.id
        
        def _add_slots(qty, skill, role_name, candidate_list):
            for i in range(qty):
                emp_id = False
                if candidate_list:
                    emp = candidate_list.pop(0)
                    emp_id = emp.id
                    
                slots_to_create.append({
                    'name': f'Turno {self.forecast_id.shift} - {role_name}',
                    'employee_id': emp_id,
                    'start_datetime': start_dt_utc,
                    'end_datetime': end_dt_utc,
                    'company_id': company_id,
                    'cookast_forecast_id': self.forecast_id.id,
                    'required_skill_ids': [(4, skill.id)],
                    'state': 'published',
                })

        _add_slots(self.responsible_qty, skill_resp, 'Responsable', sorted_resp)
        _add_slots(self.senior_qty, skill_senior, 'Senior', sorted_senior)
        _add_slots(self.junior_qty, skill_junior, 'Junior', sorted_junior)
        
        if slots_to_create:
            Slot.create(slots_to_create)

        return True