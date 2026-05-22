# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import json
import re
import logging
from datetime import timedelta

_logger = logging.getLogger(__name__)

class CookastAiPriceRecommendation(models.TransientModel):
    _name = 'cookast.ai.price.recommendation'
    _description = 'AI Price Recommendation Wizard'

    local_id = fields.Many2one('cookast.local', string='Local (opcional)')
    product_ids = fields.Many2many('product.product', string='Productos (opcional)')
    recommendation_lines = fields.One2many(
        'cookast.ai.price.recommendation.line',
        'wizard_id',
        string='Recomendaciones'
    )

    def action_generate(self):
        self.ensure_one()
        # 1. Fetch active AI config
        ai_config = self.env['cookast.ai.config'].search([('active', '=', True)], limit=1)
        if not ai_config:
            raise UserError(_("No hay una configuración de IA activa."))

        # 2. Gather data
        domain = [('sale_ok', '=', True)]
        if self.product_ids:
            domain.append(('id', 'in', self.product_ids.ids))
        products = self.env['product.product'].search(domain)

        if not products:
            raise UserError(_("No se encontraron productos de venta para analizar."))

        today = fields.Date.context_today(self)
        end_date = today + timedelta(days=7)

        forecast_domain = [('date', '>=', today), ('date', '<=', end_date)]
        if self.local_id:
            forecast_domain.append(('local_id', '=', self.local_id.id))
        
        forecasts = self.env['cookast.forecast'].search(forecast_domain)
        total_revenue = sum(forecasts.mapped('forecast_revenue'))

        weather_info = ""
        if 'cookast.weather.forecast' in self.env:
            weathers = self.env['cookast.weather.forecast'].search([
                ('date', '>=', today), ('date', '<=', end_date)
            ])
            if weathers:
                temps = weathers.mapped('temp_max')
                avg_temp = sum(temps) / len(temps) if temps else 0
                weather_info = f"Previsión meteorológica media de los próximos 7 días: {avg_temp:.1f}ºC."

        products_data = []
        for product in products:
            cost = product.standard_price
            # If mrp is installed and cookast_unit_cost exists
            if hasattr(product, 'bom_ids') and product.bom_ids:
                active_boms = product.bom_ids.filtered(lambda b: b.active)
                if active_boms and hasattr(active_boms[0], 'cookast_unit_cost'):
                    cost = active_boms[0].cookast_unit_cost

            if cost <= 0:
                continue

            price = product.list_price
            margin = ((price - cost) / price * 100) if price > 0 else 0

            products_data.append({
                'id': product.id,
                'name': product.display_name,
                'price': price,
                'cost': cost,
                'margin': margin,
            })

        if not products_data:
            raise UserError(_("Ningún producto analizado tiene coste configurado (>0)."))

        # 3. Build prompt
        local_name = self.local_id.name if self.local_id else "Todos los locales"
        prompt = self._build_recommendation_prompt(products_data, local_name, total_revenue, weather_info)

        # 4. Query AI
        try:
            response = ai_config._query_ai(prompt)
        except Exception as e:
            raise UserError(_("Error consultando a la IA: %s") % str(e))

        # 5. Parse response
        parsed_data = self._parse_recommendations(response, products_data)

        # Populate lines
        self.recommendation_lines = [(5, 0, 0)] # Clear existing
        lines_vals = []
        for p_data in parsed_data:
            lines_vals.append((0, 0, {
                'product_id': p_data['product_id'],
                'current_price': p_data['current_price'],
                'current_cost': p_data['current_cost'],
                'current_margin': p_data['current_margin'],
                'suggested_price': p_data['suggested_price'],
                'reason': p_data['reason'],
                'apply': True,
            }))
        self.recommendation_lines = lines_vals

        return {
            'type': 'ir.actions.act_window',
            'name': _('Recomendación de precios'),
            'res_model': 'cookast.ai.price.recommendation',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _build_recommendation_prompt(self, products_data, local_name, total_revenue, weather_info):
        products_str = ""
        for p in products_data:
            products_str += f"- ID: {p['id']} | Name: {p['name']} | Current Price: {p['price']} | Cost: {p['cost']} | Margin: {p['margin']:.2f}%\n"

        prompt = f"""You are a professional restaurant pricing consultant.
Analyze the following products for the location: {local_name}.
Predicted revenue for the next 7 days: {total_revenue}€.
{weather_info}

Products data:
{products_str}

Return ONLY a JSON array with the following exact structure, no markdown formatting outside the JSON, no extra text:
[
  {{
    "id": 123,
    "product_name": "Name",
    "current_price": 10.50,
    "suggested_price": 11.00,
    "reason": "Corto motivo en español de la recomendación"
  }}
]

Important rules:
- Provide a realistic suggested_price based on margin and demand. If no change is needed, suggested_price can be equal to current_price.
- The reason must be short and in Spanish.
- Return ONLY valid JSON array."""
        return prompt

    def _parse_recommendations(self, response, products_data):
        # find JSON array
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if not match:
            raise UserError(_("La IA no devolvió un JSON válido. Respuesta: %s") % response)
        
        try:
            json_data = json.loads(match.group())
        except Exception as e:
            raise UserError(_("Error al parsear el JSON de la IA: %s") % str(e))

        product_map = {p['id']: p for p in products_data}
        results = []
        for item in json_data:
            p_id = item.get('id')
            if p_id in product_map:
                p_info = product_map[p_id]
                s_price = item.get('suggested_price')
                if s_price is None:
                    s_price = p_info['price']
                results.append({
                    'product_id': p_id,
                    'current_price': p_info['price'],
                    'current_cost': p_info['cost'],
                    'current_margin': p_info['margin'],
                    'suggested_price': s_price,
                    'reason': item.get('reason', ''),
                })
        return results

    def action_apply(self):
        self.ensure_one()
        updated_count = 0
        for line in self.recommendation_lines.filtered('apply'):
            # Update product list_price
            line.product_id.list_price = line.suggested_price
            updated_count += 1
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Precios actualizados'),
                'message': _('Se actualizaron los precios de %d productos.') % updated_count,
                'type': 'success',
            }
        }

class CookastAiPriceRecommendationLine(models.TransientModel):
    _name = 'cookast.ai.price.recommendation.line'
    _description = 'AI Price Recommendation Line'

    wizard_id = fields.Many2one('cookast.ai.price.recommendation', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Producto', readonly=True)
    current_price = fields.Float(string='Precio Actual', readonly=True)
    current_cost = fields.Float(string='Coste', readonly=True)
    current_margin = fields.Float(string='Margen (%)', readonly=True)
    suggested_price = fields.Float(string='Precio Sugerido')
    reason = fields.Text(string='Motivo', readonly=True)
    apply = fields.Boolean(string='Aplicar', default=False)
