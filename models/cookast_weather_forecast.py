from odoo import models, fields, api, _
import logging
import requests
from datetime import date, timedelta

_logger = logging.getLogger(__name__)


class CookastWeatherForecast(models.Model):
    _name = 'cookast.weather.forecast'
    _description = 'Previsión meteorológica diaria por local'
    _rec_name = 'date'
    _order = 'date desc'

    local_id = fields.Many2one(
        'cookast.local', string='Local', required=True, index=True, ondelete='cascade'
    )
    date = fields.Date(string='Fecha', required=True, index=True)

    # Datos de Open-Meteo (diarios)
    temp_min = fields.Float(string='Temp. mín (°C)')
    temp_max = fields.Float(string='Temp. máx (°C)')
    rain_mm = fields.Float(string='Lluvia (mm/día)')
    wind_kmh = fields.Float(string='Viento máx (km/h)')
    weather_condition = fields.Char(string='Estado del cielo')

    # Factor de ajuste para Cookast (porcentaje: ej. -11 significa -11%)
    weather_factor = fields.Float(
        string='Ajuste demanda (%)',
        default=0.0,
        help='Porcentaje de ajuste sobre la previsión base. '
             'Ejemplo: -11% significa que el clima reduce la demanda un 11% respecto a la media histórica.',
    )

    _sql_constraints = [
        ('unique_local_date', 'UNIQUE(local_id, date)',
         'Ya existe una previsión meteorológica para este local y fecha.')
    ]

    # -------------------------------------------------------------------------
    # CRON: fetch diario de Open-Meteo (gratis, sin API key)
    # -------------------------------------------------------------------------
    @api.model
    def _cron_fetch_weather_forecast(self):
        """Obtiene previsión a 7 días para todos los locales con coordenadas."""
        locals_with_coords = self.env['cookast.local'].search([
            ('latitude', '!=', 0.0), ('longitude', '!=', 0.0)
        ])
        if not locals_with_coords:
            _logger.info("No hay locales con coordenadas para obtener previsiones.")
            return

        today = date.today()
        end_date = today + timedelta(days=6)

        for loc in locals_with_coords:
            self._fetch_and_store_forecast(loc, today, end_date)

    @api.model
    def _fetch_and_store_forecast(self, local, start_date, end_date):
        url = 'https://api.open-meteo.com/v1/forecast'
        params = {
            'latitude': local.latitude,
            'longitude': local.longitude,
            'daily': 'temperature_2m_max,temperature_2m_min,precipitation_sum,'
                     'wind_speed_10m_max,weathercode',
            'timezone': 'auto',
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
        }
        headers = {'User-Agent': 'CookastWeather/1.0 (contact@apuntserp.es)'}
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            _logger.error("Error fetching weather for local %s: %s", local.name, e)
            return

        daily = data.get('daily', {})
        if not daily:
            return

        for i, date_str in enumerate(daily['time']):
            forecast_date = fields.Date.to_date(date_str)
            vals = {
                'local_id': local.id,
                'date': forecast_date,
                'temp_min': daily['temperature_2m_min'][i],
                'temp_max': daily['temperature_2m_max'][i],
                'rain_mm': daily['precipitation_sum'][i],
                'wind_kmh': daily['wind_speed_10m_max'][i] or 0.0,
                'weather_condition': self._weather_code_to_text(daily['weathercode'][i]),
            }
            # Calcular factor meteorológico usando umbrales
            vals['weather_factor'] = self._compute_weather_factor(vals)

            existing = self.search([
                ('local_id', '=', local.id),
                ('date', '=', forecast_date),
            ], limit=1)
            if existing:
                existing.write(vals)
            else:
                self.create(vals)

    def _weather_code_to_text(self, code):
        mapping = {
            0: 'Despejado', 1: 'Parcialmente nublado', 2: 'Nublado', 3: 'Cubierto',
            45: 'Niebla', 48: 'Niebla helada',
            51: 'Llovizna ligera', 53: 'Llovizna moderada', 55: 'Llovizna densa',
            61: 'Lluvia ligera', 63: 'Lluvia moderada', 65: 'Lluvia intensa',
            80: 'Chubascos ligeros', 81: 'Chubascos moderados', 82: 'Chubascos violentos',
            95: 'Tormenta', 96: 'Tormenta granizo lig.', 99: 'Tormenta granizo int.',
        }
        return mapping.get(code, 'Desconocido')

    # -------------------------------------------------------------------------
    # Cálculo del factor de ajuste (%)
    # -------------------------------------------------------------------------
    @api.model
    def _compute_weather_factor(self, vals):
        """Devuelve un porcentaje (ej. -11.0) basado en temp, lluvia y viento."""
        temp_max = vals.get('temp_max', 20)
        temp_min = vals.get('temp_min', 10)
        rain = vals.get('rain_mm', 0)
        wind = vals.get('wind_kmh', 0)
        factor = 0.0

        # Calor extremo (>35 °C) : -8 a -15 %
        if temp_max >= 35:
            factor -= 8 + (temp_max - 35) * 0.5

        # Frío intenso (máx < 8 °C y mín < 2 °C)
        if temp_max < 8 and temp_min < 2:
            factor -= 5

        # Viento fuerte (>40 km/h) : -5 a -10 %
        if wind > 40:
            factor -= 5 + min(wind - 40, 20) * 0.25

        # Lluvia intensa (>10 mm/día) : -6 a -12 %
        if rain > 10:
            factor -= 6 + min(rain - 10, 20) * 0.3

        # Clima ideal (templado, seco, poco viento) : +3 a +8 %
        if 18 <= temp_max <= 25 and temp_min >= 10 and rain < 2 and wind < 20:
            factor += 5

        # Acotar entre -25 y +15 %
        factor = max(-25.0, min(15.0, factor))
        return round(factor, 1)

    # -------------------------------------------------------------------------
    # Acción manual desde el menú (force refresh)
    # -------------------------------------------------------------------------
    def action_manual_refresh(self):
        """Actualiza las previsiones para los locales con coordenadas (forzado desde UI)."""
        self._cron_fetch_weather_forecast()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Previsiones actualizadas'),
                'message': _('Se han refrescado los datos meteorológicos de los locales.'),
                'type': 'success',
                'sticky': False,
            }
        }