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
        'shift_planner_community',
    ],
   'data': [
        # Security
        'security/ir.model.access.csv',
        'views/cookast_menu.xml',
        
        # Locales
        'views/local_views.xml',
        
        # Dashboard
        'views/dashboard_views.xml',
        'views/forecast_kpi_views.xml',
        'views/forecast_config_views.xml',
        
        # Personal (carpeta primero, luego menús que la usan)
        'views/staffing_need_views.xml',      # ← define menu_cookast_personal_folder
        'views/staffing_kpi_views.xml',       # ← usa menu_cookast_personal_folder
        'views/employee_views.xml',           # ← usa menu_cookast_personal_folder
        'views/shift_plan_views.xml',         # ← usa menu_cookast_personal_folder
        
        # Compras
        'views/purchase_views.xml',
        'views/mrp_bom_views.xml',
        'views/cookast_bom_views.xml',
        
        # IA y otros
        'views/ai_placeholder.xml',
        
        # Datos y cron
        'data/ir_cron_weather.xml',
        
        # Reports
        'reports/reports_styles.xml',
        'reports/cookast_local_report.xml',
        'reports/cookast_forecast_report.xml',
        'reports/cookast_staffing_report.xml',
        'reports/cookast_purchase_report.xml',
        'reports/cookast_material_need_report.xml',
        'reports/cookast_bom_report.xml',
        'reports/cookast_employee_report.xml',
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