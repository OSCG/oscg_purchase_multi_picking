# -*- coding: utf-8 -*-
from odoo import  api, fields, models, _


class StockMove(models.Model):
    _inherit = 'stock.move'

    store_line_id = fields.Many2one('store.order.line','Store Order Ref')
