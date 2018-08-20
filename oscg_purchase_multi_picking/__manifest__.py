# -*- coding: utf-8 -*-
{
    'name': "Purchase Order Multi Picking",

    'description': """
        Enable purchase order to generate multiple pickings according to the picking type field of purchase line 
    """,
    'author': "OSCG",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/master/odoo/addons/base/module/module_data.xml
    # for the full list
    'category': 'Inventory',
    'version': '0.0.1',

    # any module necessary for this one to work correctly
    'depends': ['purchase'],

    # always loaded
    'data': [
        'security/purchase_multi_picking_security.xml',
        'views/purchase_inherit_view.xml'
    ],
    'license': 'OPL-1',
    'currency': 'USD',
    'price': 10,
    'support': 'sales@oscg.biz',
    'application':True,
}
