# -*- coding: utf-8 -*-
# models/cookast_local.py
# Modelo central de Gestión Multilocal Cookast.
# Representa un local/sucursal de la franquicia (ej: "HUNDRED El Palmar").
# Al crear un local, se auto-crea un stock.warehouse con código único,
# lo que garantiza stock 100% independiente por sucursal.

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
import requests
import time

_logger = logging.getLogger(__name__)


class CookastLocal(models.Model):
    _name = 'cookast.local'
    _description = 'Local / Sucursal de Franquicia Cookast'
    _rec_name = 'name'
    _order = 'sequence, name'

    # ── Identificación ────────────────────────────────────────────────────────
    name = fields.Char(
        string='Nombre del local',
        required=True,
        help='Ej: HUNDRED El Palmar, HUNDRED Avenida…',
    )
    short_code = fields.Char(
        string='Código corto',
        size=5,
        required=True,
        help='Código de 3-5 letras que se usará para el almacén (ej: HEP, HAV). '
             'Solo letras mayúsculas, sin espacios. No editable una vez guardado.',
    )
    active = fields.Boolean(string='Activo', default=True)
    sequence = fields.Integer(string='Secuencia', default=10)
    color = fields.Integer(string='Color', default=0)
    phone = fields.Char(string='Teléfono')
    email = fields.Char(string='Email')
    notes = fields.Text(string='Notas internas')

    # ── Dirección ─────────────────────────────────────────────────────────────
    street = fields.Char(string='Calle')
    street2 = fields.Char(string='Calle 2')
    zip = fields.Char(string='C.P.')
    city = fields.Char(string='Ciudad')
    state_id = fields.Many2one('res.country.state', string='Provincia', domain="[('country_id', '=', country_id)]")
    country_id = fields.Many2one('res.country', string='País', default=lambda self: self.env.company.country_id)

    # ── Almacén y Stock ───────────────────────────────────────────────────────
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Almacén',
        readonly=True,
        help='Almacén de Odoo asociado a este local. '
             'Se crea automáticamente al guardar el local por primera vez.',
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Ubicación de stock',
        readonly=True,
        help='Ubicación principal de inventario de este local. '
             'Deriva del almacén creado automáticamente.',
    )

    # ── Geolocalización ───────────────────────────────────────────────────────
    latitude = fields.Float(string='Latitud', digits=(9, 6))
    longitude = fields.Float(string='Longitud', digits=(9, 6))

    # ── Personal ──────────────────────────────────────────────────────────────
    manager_id = fields.Many2one(
        'hr.employee',
        string='Manager del local',
        domain=[('cookast_level', '=', 'responsible')],
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        'cookast_local_employee_rel',
        'local_id',
        'employee_id',
        string='Empleados asignados',
        help='Empleados que trabajan habitualmente en este local. '
             'Un empleado puede estar en varios locales (franquicia).',
    )

    # ── TPVs (Terminales Punto de Venta) ──────────────────────────────────────
    pos_config_ids = fields.One2many(
        'pos.config',
        'cookast_local_id',
        string='Terminales TPV',
    )

    # ── Estadísticas (computed) ───────────────────────────────────────────────
    forecast_count = fields.Integer(
        string='Previsiones',
        compute='_compute_stats',
    )
    employee_count = fields.Integer(
        string='Empleados',
        compute='_compute_stats',
    )
    pos_count = fields.Integer(
        string='TPVs',
        compute='_compute_stats',
    )
    last_forecast_date = fields.Date(
        string='Última previsión',
        compute='_compute_stats',
    )

    @api.depends('employee_ids', 'pos_config_ids')
    def _compute_stats(self):
        for local in self:
            forecasts = self.env['cookast.forecast'].search([
                ('local_id', '=', local.id),
            ])
            local.forecast_count = len(forecasts)
            local.employee_count = len(local.employee_ids)
            local.pos_count = len(local.pos_config_ids)
            dates = forecasts.mapped('date')
            local.last_forecast_date = max(dates) if dates else False

    # ── Constraints ───────────────────────────────────────────────────────────
    _sql_constraints = [
        ('unique_short_code', 'UNIQUE(short_code)',
         'Ya existe un local con este código corto. Usa uno diferente.'),
        ('unique_name', 'UNIQUE(name)',
         'Ya existe un local con este nombre.'),
    ]

    @api.constrains('short_code')
    def _check_short_code(self):
        for local in self:
            if not local.short_code:
                continue
            if not local.short_code.isalpha():
                raise ValidationError(_(
                    'El código corto "%s" solo puede contener letras (sin espacios ni números).'
                ) % local.short_code)

    # ── CRUD: auto-crear warehouse al crear el local ─────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('warehouse_id'):
                code = (vals.get('short_code') or vals.get('name', '')[:5]).upper()
                existing = self.env['stock.warehouse'].search([('code', '=', code)], limit=1)
                if existing:
                    suffix = 1
                    while existing:
                        new_code = f"{code[:4]}{suffix}"
                        existing = self.env['stock.warehouse'].search(
                            [('code', '=', new_code)], limit=1
                        )
                        suffix += 1
                    code = new_code

                _logger.info("Cookast: creando warehouse '%s' (código: %s) para el local '%s'",
                             vals.get('name'), code, vals.get('name'))
                warehouse = self.env['stock.warehouse'].create({
                    'name': vals.get('name'),
                    'code': code,
                    'company_id': self.env.company.id,
                })
                vals['warehouse_id'] = warehouse.id
                vals['location_id'] = warehouse.lot_stock_id.id
                if code != (vals.get('short_code') or '').upper():
                    vals['short_code'] = code

        return super().create(vals_list)

    # ── Acciones rápidas (smart buttons) ─────────────────────────────────────
    def action_view_forecasts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Previsiones — %s') % self.name,
            'res_model': 'cookast.forecast',
            'view_mode': 'graph,pivot,list,form',
            'domain': [('local_id', '=', self.id)],
            'context': {'default_local_id': self.id},
        }

    def action_view_employees(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Empleados — %s') % self.name,
            'res_model': 'hr.employee',
            'view_mode': 'kanban,list,form',
            'domain': [('cookast_local_ids', 'in', self.id)],
            'context': {'default_cookast_local_ids': [(4, self.id)]},
        }

    def action_view_pos(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('TPVs — %s') % self.name,
            'res_model': 'pos.config',
            'view_mode': 'list,form',
            'domain': [('cookast_local_id', '=', self.id)],
            'context': {'default_cookast_local_id': self.id},
        }

    def action_view_stock(self):
        """Abre el inventario del almacén de este local."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Inventario — %s') % self.name,
            'res_model': 'stock.quant',
            'view_mode': 'list',
            'domain': [('location_id', 'child_of', self.location_id.id)],
            'context': {
                'default_location_id': self.location_id.id,
                'search_default_internal_loc': 1,
                'inventory_mode': True,
                'no_at_date': True,
            },
        }

    # ── GEOLOCALIZACIÓN ───────────────────────────────────────────────────────

    def action_geocode(self):
        """
        Obtiene las coordenadas GPS usando el servicio gratuito Nominatim (OSM).
        Respeta la política de uso: 1 petición por segundo y User-Agent identificado.
        """
        geocoded = 0
        skipped = 0

        PLACEHOLDERS = {'calle 2...', 'calle 2', 'calle2...', 'calle2',
                        'street 2...', 'street2...', '...', 'n/a', '-', ''}

        for record in self:
            street_parts = []
            if record.street and record.street.strip().lower() not in PLACEHOLDERS:
                street_parts.append(record.street.strip())
            if record.street2 and record.street2.strip().lower() not in PLACEHOLDERS:
                street_parts.append(record.street2.strip())

            addr_parts = []
            if street_parts:
                addr_parts.append(", ".join(street_parts))
            if record.city and record.city.strip():
                addr_parts.append(record.city.strip())
            if record.zip and record.zip.strip():
                addr_parts.append(record.zip.strip())
            if record.state_id and record.state_id.name.strip():
                addr_parts.append(record.state_id.name.strip())
            if record.country_id and record.country_id.name.strip():
                addr_parts.append(record.country_id.name.strip())
            elif self.env.company.country_id and self.env.company.country_id.name.strip():
                addr_parts.append(self.env.company.country_id.name.strip())

            address = ", ".join(addr_parts)
            _logger.info("Geocoding local '%s': dirección construida = '%s'", record.name, address)

            if not address or len(addr_parts) < 2:
                _logger.warning("Geocoding omitido para '%s': dirección insuficiente (partes: %s)", record.name, addr_parts)
                skipped += 1
                continue

            result = self._try_geocode(address)

            if not result and record.zip:
                addr_no_zip = [p for p in addr_parts if p.strip() != record.zip.strip()]
                address_no_zip = ", ".join(addr_no_zip)
                _logger.info("Reintentando sin CP para '%s': %s", record.name, address_no_zip)
                result = self._try_geocode(address_no_zip)

            if not result and len(addr_parts) >= 2:
                address_short = ", ".join(addr_parts[:2])
                _logger.info("Reintentando solo calle+ciudad para '%s': %s", record.name, address_short)
                result = self._try_geocode(address_short)

            if result:
                record.write({
                    'latitude': result['lat'],
                    'longitude': result['lon'],
                })
                geocoded += 1
                _logger.info("✓ Geolocalizado '%s': lat=%s, lon=%s", record.name, result['lat'], result['lon'])
            else:
                _logger.warning("✗ Sin resultados para '%s' tras todos los intentos", record.name)
                skipped += 1

            if len(self) > 1:
                time.sleep(1.5)

        if geocoded > 0 and skipped == 0:
            title = _('Geolocalización completada')
            message = _('Se geolocalizaron correctamente %d local(es).') % geocoded
            notif_type = 'success'
        elif geocoded > 0 and skipped > 0:
            title = _('Geolocalización parcial')
            message = _('%d local(es) geolocalizados, %d omitido(s). Revise los logs para más detalles.') % (geocoded, skipped)
            notif_type = 'warning'
        else:
            title = _('Geolocalización sin resultados')
            message = _(
                'No se pudo geolocalizar ningún local.\n\n'
                'Verifique que:\n'
                '• La dirección es real y tiene calle + ciudad\n'
                '• El servidor tiene acceso a internet\n'
                '• La librería "requests" está instalada en el contenedor Odoo\n\n'
                'Revise los logs del servidor para más detalles.'
            )
            notif_type = 'danger'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': skipped > 0,
            }
        }

    @api.model
    def _try_geocode(self, address):
        """
        Intenta geolocalizar una dirección con Nominatim.
        Retorna {'lat': float, 'lon': float} o None si falla.
        """
        import sys

        try:
            import requests
            _logger.info("→ requests disponible, versión: %s", requests.__version__)
        except ImportError as e:
            _logger.error("✗ requests NO ESTÁ INSTALADO en el entorno Odoo: %s", e)
            _logger.error("  Instálelo con: pip3 install requests")
            return None

        try:
            params = {
                'q': address,
                'format': 'json',
                'limit': 1,
                'accept-language': 'es',
            }
            headers = {
                'User-Agent': 'Cookast/1.0 (apuntserp@apuntserp.es)',
            }

            _logger.info("→ Llamando a Nominatim: %s", address)
            response = requests.get(
                'https://nominatim.openstreetmap.org/search',
                params=params,
                headers=headers,
                timeout=15,
            )

            _logger.info("← Nominatim HTTP %s", response.status_code)

            if response.status_code != 200:
                _logger.error("✗ Nominatim devolvió HTTP %s: %s", response.status_code, response.text[:300])
                return None

            data = response.json()
            _logger.info("← Respuesta: %s", str(data)[:300])

            if data and isinstance(data, list) and len(data) > 0:
                result = {'lat': float(data[0]['lat']), 'lon': float(data[0]['lon'])}
                _logger.info("✓ ÉXITO: lat=%s, lon=%s", result['lat'], result['lon'])
                return result

            _logger.warning("✗ Nominatim devolvió lista vacía para: %s", address)
            return None

        except requests.exceptions.Timeout as e:
            _logger.error("✗ Timeout conectando a Nominatim: %s", e)
            return None
        except requests.exceptions.ConnectionError as e:
            _logger.error("✗ Error de conexión a Nominatim: %s", e)
            return None
        except requests.exceptions.RequestException as e:
            _logger.error("✗ Error de requests: %s (tipo: %s)", e, type(e).__name__)
            return None
        except Exception as e:
            _logger.error("✗ Error inesperado: %s (tipo: %s, línea: %s)", e, type(e).__name__, sys.exc_info()[-1].tb_lineno)
            return None