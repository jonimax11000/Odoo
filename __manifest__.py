{
    'name': 'Cookast Connector',
    'version': '19.0.3.0.0',
    'category': 'Operations/Foodservice',
    'summary': 'Integración con Cookast: Previsiones, Compras y Personal',
    'description': """...""",
    'author': 'Apunts Informática',
    'website': 'https://apuntsinformatica.apuntserp.es/',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'point_of_sale',
        'purchase',
        'sale_management',
        'hr',
        'hr_holidays',
        'stock',
        'mrp',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/local_views.xml',
        'views/cookast_menu.xml',
        'views/dashboard_views.xml',
        'views/forecast_kpi_views.xml',
        'views/employee_views.xml',
        'views/shift_plan_views.xml',
        'views/purchase_views.xml',
        'views/forecast_config_views.xml',
        'views/staffing_kpi_views.xml',      # ← antes
        'views/staffing_need_views.xml',    # ← después
        'views/mrp_bom_views.xml',
        'views/cookast_bom_views.xml',
        'views/ai_placeholder.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'cookast/static/src/css/kpi_dashboard.css',
        ],
        'point_of_sale.assets': [
            'cookast/static/src/css/pos_stock_error.css',
            'cookast/static/src/xml/cookast_pos_stock_dialog.xml',
            'cookast/static/src/js/cookast_pos_stock.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}