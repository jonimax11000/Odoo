# -*- coding: utf-8 -*-
import json, re, pytz
from datetime import datetime, time, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class CookastStaffingNeed(models.Model):
    _inherit = "cookast.staffing.need"

    def _build_ai_staffing_prompt(self):
        """
        Prepara los mismos candidatos filtrados y ordenados que el método manual,
        y construye un prompt para que la IA solo decida la combinación óptima.
        """
        self.ensure_one()
        forecast = self.forecast_id
        if not forecast:
            raise UserError(_("No hay previsión asociada."))

        local = forecast.local_id
        target_date = forecast.date
        shift_type = forecast.shift

        # ── Replicar lógica de filtrado del método manual ─────────────────
        # 1. Skills
        Skill = self.env["shift.skill"].sudo()
        skill_resp = Skill.search([("name", "=", "Responsable")], limit=1)
        if not skill_resp:
            skill_resp = Skill.create({"name": "Responsable", "color": 2})
        skill_senior = Skill.search([("name", "=", "Senior")], limit=1)
        if not skill_senior:
            skill_senior = Skill.create({"name": "Senior", "color": 4})
        skill_junior = Skill.search([("name", "=", "Junior")], limit=1)
        if not skill_junior:
            skill_junior = Skill.create({"name": "Junior", "color": 6})

        # 2. Sincronizar skills de los empleados del local
        if local:
            local.employee_ids._sync_cookast_level_skills()
        local_employee_ids = local.employee_ids.ids if local else []

        # 3. Absencias y solapamientos
        absent_ids = self._get_absent_employee_ids(target_date)
        user_tz = pytz.timezone(self.env.user.tz or "UTC")
        if shift_type == "lunch":
            start_hour, end_hour = 11, 16
        else:
            start_hour, end_hour = 19, 24

        start_dt_local = user_tz.localize(
            datetime.combine(target_date, time(start_hour, 0))
        )
        start_dt_utc = start_dt_local.astimezone(pytz.UTC).replace(tzinfo=None)
        if end_hour == 24:
            end_dt_local = user_tz.localize(
                datetime.combine(target_date, time(23, 59, 59))
            )
        else:
            end_dt_local = user_tz.localize(
                datetime.combine(target_date, time(end_hour, 0))
            )
        end_dt_utc = end_dt_local.astimezone(pytz.UTC).replace(tzinfo=None)

        busy_ids = set(
            self.env["shift.planning.slot"]
            .search(
                [
                    ("start_datetime", "<", end_dt_utc),
                    ("end_datetime", ">", start_dt_utc),
                ]
            )
            .mapped("employee_id.id")
        )
        excluded_ids = list(absent_ids | busy_ids)

        # 4. Candidatos por nivel (solo del local, no ausentes ni ocupados)
        employees_resp = self.env["hr.employee"].search(
            [
                ("id", "not in", excluded_ids),
                ("id", "in", local_employee_ids),
                ("shift_skill_ids", "in", skill_resp.ids),
            ]
        )
        employees_senior = self.env["hr.employee"].search(
            [
                ("id", "not in", excluded_ids),
                ("id", "in", local_employee_ids),
                ("shift_skill_ids", "in", skill_senior.ids),
                ("id", "not in", employees_resp.ids),
            ]
        )
        employees_junior = self.env["hr.employee"].search(
            [
                ("id", "not in", excluded_ids),
                ("id", "in", local_employee_ids),
                ("shift_skill_ids", "in", skill_junior.ids),
                ("id", "not in", (employees_resp | employees_senior).ids),
            ]
        )

        # 5. Capacidad semanal
        all_candidate_ids = (employees_resp | employees_senior | employees_junior).ids
        hours_map = self._get_weekly_hours_map(all_candidate_ids, target_date)
        shift_hours = (end_dt_utc - start_dt_utc).total_seconds() / 3600.0

        employees_resp = self._filter_by_weekly_capacity(
            employees_resp, hours_map, shift_hours
        )
        employees_senior = self._filter_by_weekly_capacity(
            employees_senior, hours_map, shift_hours
        )
        employees_junior = self._filter_by_weekly_capacity(
            employees_junior, hours_map, shift_hours
        )

        # 6. Equidad (ordenar por fairness score)
        sorted_resp = list(
            self._sort_by_fairness(employees_resp, target_date, shift_type)
        )
        sorted_senior = list(
            self._sort_by_fairness(employees_senior, target_date, shift_type)
        )
        sorted_junior = list(
            self._sort_by_fairness(employees_junior, target_date, shift_type)
        )

        # ── Construir el prompt para la IA ─────────────────────────────
        def emp_info(emp):
            weekly = hours_map.get(emp.id, 0.0)
            max_h = emp.cookast_max_weekly_hours or 40.0
            return (
                f"{emp.name} (coste={emp.cookast_hourly_cost:.2f}€/h, "
                f"horas esta semana={weekly:.1f}/{max_h}, "
                f"disponible={max_h - weekly:.1f}h)"
            )

        lines = []
        lines.append(f"Turno: {shift_type} del {target_date} en {local.name}.")
        lines.append(f"Duración estimada: {shift_hours:.1f}h.")
        lines.append(
            f"Necesidades: Responsables={self.responsible_qty}, Senior={self.senior_qty}, Junior={self.junior_qty} (Total={self.total_persons})."
        )
        lines.append(
            "Empleados disponibles (ya filtrados por ausencias, solapamientos y capacidad semanal, ordenados por equidad):"
        )
        if sorted_resp:
            lines.append("Responsables:")
            for emp in sorted_resp:
                lines.append("  - " + emp_info(emp))
        if sorted_senior:
            lines.append("Senior:")
            for emp in sorted_senior:
                lines.append("  - " + emp_info(emp))
        if sorted_junior:
            lines.append("Junior:")
            for emp in sorted_junior:
                lines.append("  - " + emp_info(emp))

        lines.append(
            "\nElige la combinación óptima que minimice el coste total y asigne a los empleados con mejor equidad (los primeros de cada lista)."
        )
        lines.append(
            "Respuesta ÚNICAMENTE con un JSON array de objetos con 'employee' (nombre exacto) y 'role' (Responsable, Senior, Junior)."
        )
        lines.append("No asignes más empleados de los necesarios.")
        lines.append("JSON:")

        return "\n".join(lines)

    def action_ai_generate_shift_plans(self):
        """Genera asignaciones usando IA y crea los shift.planning.slot."""
        self.ensure_one()
        if "cookast.ai.config" not in self.env:
            raise UserError(_("El módulo Cookast AI no está configurado."))

        ai_config = self.env["cookast.ai.config"]._get_active_config()
        prompt = self._build_ai_staffing_prompt()
        response = ai_config._query_ai(prompt)

        match = re.search(r"\[.*\]", response, re.DOTALL)
        if not match:
            raise UserError(
                _("La IA no devolvió un JSON válido.\nRespuesta: %s") % response
            )

        try:
            assignments = json.loads(match.group())
        except json.JSONDecodeError:
            raise UserError(
                _("La IA devolvió un JSON mal formado.\nRespuesta: %s") % response
            )

        if not isinstance(assignments, list):
            raise UserError(
                _("La IA no devolvió una lista de asignaciones.\nRespuesta: %s")
                % response
            )

        forecast = self.forecast_id
        employee_obj = self.env["hr.employee"]
        skill_obj = self.env["shift.skill"]

        # Horarios del turno (mismos que en el método manual)
        user_tz = pytz.timezone(self.env.user.tz or "UTC")
        target_date = forecast.date
        shift_type = forecast.shift
        if shift_type == "lunch":
            start_hour, end_hour = 11, 16
        else:
            start_hour, end_hour = 19, 24
        start_dt_local = user_tz.localize(
            datetime.combine(target_date, time(start_hour, 0))
        )
        start_dt_utc = start_dt_local.astimezone(pytz.UTC).replace(tzinfo=None)
        if end_hour == 24:
            end_dt_local = user_tz.localize(
                datetime.combine(target_date, time(23, 59, 59))
            )
        else:
            end_dt_local = user_tz.localize(
                datetime.combine(target_date, time(end_hour, 0))
            )
        end_dt_utc = end_dt_local.astimezone(pytz.UTC).replace(tzinfo=None)

        company_id = self.env.company.id
        slots_to_create = []

        for assign in assignments:
            emp_name = assign.get("employee", "")
            role = assign.get("role", "")
            if not emp_name or not role:
                continue

            employee = employee_obj.search([("name", "=", emp_name)], limit=1)
            if not employee:
                _logger.warning(
                    "Empleado '%s' no encontrado en la asignación IA.", emp_name
                )
                continue

            skill = skill_obj.search([("name", "=", role)], limit=1)
            if not skill:
                skill = skill_obj.create({"name": role})

            slots_to_create.append(
                {
                    "name": f"Turno {forecast.shift} - {role} (IA)",
                    "employee_id": employee.id,
                    "start_datetime": start_dt_utc,
                    "end_datetime": end_dt_utc,
                    "company_id": company_id,
                    "cookast_forecast_id": forecast.id,
                    "required_skill_ids": [(4, skill.id)],
                    "state": "published",
                }
            )

        if not slots_to_create:
            raise UserError(
                _(
                    "No se pudo crear ninguna asignación a partir de la respuesta de la IA."
                )
            )

        self.env["shift.planning.slot"].create(slots_to_create)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Asignaciones generadas con IA"),
                "message": _("Se crearon %d asignaciones correctamente.")
                % len(slots_to_create),
                "type": "success",
            },
        }
