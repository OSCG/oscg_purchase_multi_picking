# -*- coding: utf-8 -*-
from odoo import api, models, fields, _
import odoo.addons.decimal_precision as dp
from odoo.exceptions import ValidationError, UserError
import xlrd
import xlwt
import xlsxwriter
import io
import base64
from datetime import datetime

class StoreOrderProductImport(models.TransientModel):
    """
    通过选择产品的销售点类别，在门店订货中批量导入产品
    """
    _name = "store.order.product.import"
    _description = u"Batch-import product for store order lines"

    product_categ = fields.Many2many('product.category',string='Import by Product Category')

    def confirm_import(self):
        context = dict(self._context or {})
        store_order_id = (context.get('active_ids'))[0]
        store_order_obj = self.env['store.order'].browse(store_order_id)
        store_order_obj.generate_order_line_by_product_categ(categ_list=self.product_categ.ids)
        return True



