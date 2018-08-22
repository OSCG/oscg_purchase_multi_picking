# -*- coding: utf-8 -*-
from odoo import  api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError
from datetime import datetime, timedelta
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, float_compare
import math


class StoreOrder(models.Model):
    _name = 'store.order'
    _inherit = ['mail.thread','mail.activity.mixin']
    _description = 'Store order to HQ for purchasing product'

    def _default_pos_id(self):
        user = self.env.user
        pos_id = self.env['pos.config'].search(['|','|',('crm_team_id','=',False),
                                                ('crm_team_id.user_id','=',user.id),
                                                ('crm_team_id.member_ids','=',user.id)],limit=1)
        return pos_id

    def _default_name(self):
        pos_id = self._default_pos_id()
        name = pos_id and pos_id.name or _('New')
        return name

    name = fields.Char(string='Order Reference', required=True, copy=False, readonly=True,
                       states={'draft': [('readonly', False)],'pending':[('readonly', False)]}, index=True, default=lambda s:s._default_name())
    pos_id = fields.Many2one('pos.config',string='POS/Store',required=True, readonly=True,
                       states={'draft': [('readonly', False)],'pending':[('readonly', False)]},default=_default_pos_id)
    date_order = fields.Datetime(string='Order Date', required=True, readonly=True, index=True,
                                 states={'draft': [('readonly', False)],'pending':[('readonly', False)]},
                                 copy=False, default=fields.Datetime.now)
    user_id = fields.Many2one('res.users',string='Applicant Name', readonly=True,
                       states={'draft': [('readonly', False)],'pending':[('readonly', False)]}, index=True, default=lambda self:self.env.user)
    order_line = fields.One2many('store.order.line', 'order_id', string='Order Lines', readonly=True,
                       states={'draft': [('readonly', False)],'pending':[('readonly', False)]}, copy=True, auto_join=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('approve', 'Approved'),
        ('cancel', 'Canceled'),
    ], string='State', readonly=True, copy=False, index=True, track_visibility='onchange',
        default='draft')
    delivery_count = fields.Integer('Pickings',compute='_compute_delivery')
    purchase_count = fields.Integer(u'Purchases', compute='_compute_delivery')
    picking_ids = fields.One2many('stock.picking',compute='_compute_delivery')
    purchase_ids = fields.One2many('purchase.order',compute='_compute_delivery')
    procurement_group_id = fields.Many2one('procurement.group', 'Procurement Group', copy=False)
    picking_policy = fields.Selection([
        ('direct', 'Deliver each product when available'),
        ('one', 'Deliver all products at once')],
        string='Picking Policy', required=True, readonly=True, default='direct',
        states={'draft': [('readonly', False)],'pending':[('readonly', False)]})
    partner_shipping_id = fields.Many2one('res.partner', string='Shipping Address', readonly=True,
                                          states={'draft': [('readonly', False)],'pending':[('readonly', False)]}, help="Delivery address for current sales order.")
    confirmation_date = fields.Datetime(string='Confirm Date', readonly=True, index=True, help="Date on which the sales order is confirmed.", oldname="date_confirm")
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env['res.company']._company_default_get('sale.order'))


    def _compute_delivery(self):
        for order in self:
            moves = self.env['stock.move'].search([('store_line_id','in',order.order_line.ids)])
            purchase_lines = order.order_line.mapped('purchase_line_id')
            self.picking_ids = self.env['stock.picking'].browse(sorted(list(set([m.picking_id.id for m in moves]))))
            self.purchase_ids = self.env['purchase.order'].browse(sorted(list(set([p.order_id.id for p in purchase_lines]))))
            self.delivery_count = len(self.picking_ids.ids)
            self.purchase_count = len(self.purchase_ids.ids)

    def action_view_delivery(self):
        return {
            "name": u"Pickings",
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            'view_mode': 'tree,form,',
            # "search_view_id": self.env.ref('swr_sale.swr_sale_cargo_search_view').id,
            'target': 'current',
            'views': [(self.env.ref('stock.vpicktree').id, 'tree'),
                      (self.env.ref('stock.view_picking_form').id, 'form')],
            'domain':[('id','in',self.picking_ids.ids)]

        }

    def action_view_purchase(self):
        return {
            "name": u"Purchases",
            "type": "ir.actions.act_window",
            "res_model": "purchase.order",
            'view_mode': 'tree,form,',
            # "search_view_id": self.env.ref('swr_sale.swr_sale_cargo_search_view').id,
            'target': 'current',
            'views': [(self.env.ref('purchase.purchase_order_tree').id, 'tree'),
                      (self.env.ref('purchase.purchase_order_form').id, 'form')],
            'domain':[('id','in',self.purchase_ids.ids)]

        }

    @api.model
    def create(self, vals):
        if vals.get('name', _("New")) in[_("New"),self.env['pos.config'].browse(vals.get('pos_id')).name]:
            pos = self.env['pos.config'].browse(vals.get('pos_id')).name
            seq = self.env['ir.sequence'].next_by_code('store.order') or _('New')
            vals['name'] = pos + seq
        result = super(StoreOrder, self).create(vals)
        return result

    def button_apply(self):
        for order in self:
            order.write({
                'state': 'pending'
            })
        action_res = self.env.ref('pos_stock.check_vendor_limits').with_context(
            active_model='store.order', active_id=self.id).run()

    def button_return(self):
        for order in self:
            order.write({
                'state': 'draft'
            })


    def button_approve(self):
        self.write({
            'state': 'approve',
            'confirmation_date': fields.Datetime.now()
        })
        for order in self:
            location_id = order.pos_id and order.pos_id.stock_location_id or False
            order.order_line._action_launch_procurement_rule(location_id)


    def button_cancel(self):
        for order in self:
            order.write({
                'state': 'cancel'
            })


    def generate_order_line_by_product_categ(self,categ_list=None):
        for order in self:
            if order.order_line:
                order.order_line.unlink()
            # line_obj = self.env['store.order.line']
            products = self.env['product.product'].search([('categ_id','child_of',categ_list)])
            vals = []
            for product in products:
                # new_line = line_obj.new({'product_id': product.id,
                #                          'product_uom': product.uom_id.id,
                #                          'price_unit': product.seller_ids and product.seller_ids[0].price
                #               or product.standard_price or product.lst_price or 0.0,
                #                          'seller_id': product.seller_ids and product.seller_ids[0].name.id or False})
                # order.order_line += new_line
                seller = False
                if product.seller_ids:
                    sellers_region = product.seller_ids.filtered(
                        lambda s: s.region_code and (self.pos_id.region_code in [code.strip() for code in s.region_code.split("/")]))
                    sellers_pos = product.seller_ids.filtered(
                        lambda s: s.pos_code and (self.pos_id.pos_code in [code.strip() for code in s.pos_code.split("/")]))
                    seller = sellers_pos and sellers_pos[0] or (sellers_region and sellers_region[0]) or False
                vals.append((0, 0, {'product_id': product.id,
                                         'product_uom': product.uom_id.id,
                                         'price_unit': seller and seller.price or product.standard_price
                                                       or product.lst_price or 0.0,
                                         'seller_id': seller and seller.name.id or False}))
            order.write({
                'order_line': vals
            })
        return


    @api.onchange('pos_id')
    def onchange_pos_config(self):
        if not self.pos_id:
            self.update({
                'name': _('New')
            })
            return
        self.update({
            'name': self.pos_id.name
        })




class StoreOrderLine(models.Model):
    _name = 'store.order.line'
    _inherit = ['mail.thread']
    _description = u'Store order line to HQ for purchasing product'

    order_id = fields.Many2one('store.order', string='Order Reference', required=True,
                               ondelete='cascade', index=True, copy=False)
    name = fields.Text(string='Description')
    product_id = fields.Many2one('product.product',string='Product')
    product_uom_qty = fields.Float(string='Quantity', digits=dp.get_precision('Product Unit of Measure'), required=True, default=0.0)
    product_uom = fields.Many2one('product.uom', string='Unit of Measure', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('approve', 'Approved'),
        ('cancel', 'Canceled'),
    ], string='State',related='order_id.state', readonly=True, copy=False, store=True,
        default='draft')
    route_id = fields.Many2one('stock.location.route', string='Route',
                               domain=[('sale_selectable', '=', True)], ondelete='restrict')
    move_ids = fields.One2many('stock.move', 'store_line_id', string='Stock Move')
    purchase_line_id = fields.Many2one('purchase.order.line', string='Purchase Line Ref',copy=False)
    price_unit = fields.Float('Unit Price', required=True, digits=dp.get_precision('Product Price'), default=0.0)
    seller_id = fields.Many2one('res.partner', 'Seller')
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env['res.company']._company_default_get('sale.order'))


    @api.multi
    def _prepare_procurement_values(self, group_id=False):
        """ Prepare specific key for moves or other components that will be created from a procurement rule
        comming from a sale order line. This method could be override in order to add other custom key that could
        be used in move/po creation.
        """
        values = {}
        self.ensure_one()
        date_planned = datetime.strptime(self.order_id.confirmation_date,
                                         DEFAULT_SERVER_DATETIME_FORMAT)
        values.update({
            'company_id': self.order_id.company_id,
            'group_id': group_id,
            'sale_line_id': self.id if self._name == 'sale.order.line' else False,
            'date_planned': date_planned.strftime(DEFAULT_SERVER_DATETIME_FORMAT),
            'route_ids': self.route_id,
            'warehouse_id': self.order_id.pos_id.stock_location_id.get_warehouse() or self.env.user.location_id.get_warehouse() or False,
            'partner_dest_id': self.order_id.partner_shipping_id,
            'store_line_id': self.id if self._name == 'store.order.line' else False,
            'partner_id': self.seller_id or False
            # 'pos_id': self.order_id.pos_id.id
        })
        return values

    @api.multi
    def _action_launch_procurement_rule(self,user_location=None):
        """
        Launch procurement group run method with required/custom fields genrated by a
        sale order line. procurement group will launch '_run_move', '_run_buy' or '_run_manufacture'
        depending on the sale order line product rule.
        """
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        errors = []
        for line in self:
            # seller = line.product_id.seller_ids.filtered(lambda s: s.name.id == line.seller_id.id)
            # purchase_amount = seller.price * line.product_uom_qty
            # if float_compare(purchase_amount,seller.min_amount, precision_digits=precision) == -1:
            #     raise UserError(u"未达到%s的最低订货值，最低订购数量为%d"%(line.product_id.name,math.ceil(seller.min_amount/seller.price)))
            # 检查是否达到最低订货量的逻辑
            if line.state != 'approve' or not line.product_id.type in ('consu', 'product'):
                continue
            qty = 0.0
            for move in line.move_ids.filtered(lambda r: r.state != 'cancel'):
                qty += move.product_qty
            if float_compare(qty, line.product_uom_qty, precision_digits=precision) >= 0:
                continue

            group_id = line.order_id.procurement_group_id
            if not group_id:
                group_id = self.env['procurement.group'].create({
                    'name': line.order_id.name, 'move_type': line.order_id.picking_policy,
                    'store_id': line.order_id.id,
                    'partner_id': line.order_id.partner_shipping_id.id,
                })
                line.order_id.procurement_group_id = group_id
            else:
                # In case the procurement group is already created and the order was
                # cancelled, we need to update certain values of the group.
                updated_vals = {}
                if group_id.partner_id != line.order_id.partner_shipping_id:
                    updated_vals.update({'partner_id': line.order_id.partner_shipping_id.id})
                if group_id.move_type != line.order_id.picking_policy:
                    updated_vals.update({'move_type': line.order_id.picking_policy})
                if updated_vals:
                    group_id.write(updated_vals)

            values = line._prepare_procurement_values(group_id=group_id)
            product_qty = line.product_uom_qty - qty
            try:
                self.env['procurement.group'].with_context(store_order=True).run(line.product_id, product_qty, line.product_uom,
                                                                                 user_location,
                                                  line.name or "", line.order_id.name, values)
            except UserError as error:
                errors.append(error.name)
        if errors:
            raise UserError('\n'.join(errors))
        return True

    @api.onchange('product_id')
    def _onchange_product_id(self):
        msg = _('Please set on product')
        missing_fileds = []
        if self.product_id:
            if not (self.product_id.uom_po_id.id or self.product_id.uom_id.id):
                missing_fileds.append('Unit of Measure')
            if not self.product_id.seller_ids:
                missing_fileds.append('Seller')
            if not (self.product_id.seller_ids and self.product_id.seller_ids[0].price
                              or self.product_id.standard_price or self.product_id.lst_price):
                missing_fileds.append('Unit Price')
            if missing_fileds:
                msg = msg + u','.join(missing_fileds)
                return {
                    'warning': {'title': "Validation Warning", 'message': msg},
                }
            if self.product_id.seller_ids:
                sellers_region = self.product_id.seller_ids.filtered(
                    lambda s: s.region_code and (self.order_id.pos_id.region_code in [code.strip() for code in s.region_code.split("/")]))
                sellers_pos = self.product_id.seller_ids.filtered(
                    lambda s: s.pos_code and (self.order_id.pos_id.pos_code in [code.strip() for code in s.pos_code.split("/")]))
                seller = sellers_pos and sellers_pos[0] or (sellers_region and sellers_region[0]) or False
            self.update({
                'product_uom': self.product_id.uom_po_id.id or self.product_id.uom_id.id,
                'price_unit': seller and seller.price
                              or self.product_id.standard_price or self.product_id.lst_price or 0.0,
                'seller_id': seller and seller.name.id or False
            })
            return {
                'domain': {'seller_id': [('id', 'in', sellers_region.mapped('name.id'))]},
            }
        else:
            self.update({
                'product_uom': False,
                'price_unit': False,
                'seller_id': False
            })
            return {
                'domain': {
                    'seller_id': [('id', 'in', [])]},
            }


    @api.onchange('seller_id')
    def _onchange_seller(self):
        if self.seller_id and self.product_id:
            sellers_region = self.product_id.seller_ids.filtered(
                lambda s: s.name.id == self.seller_id.id and s.region_code and (self.order_id.pos_id.region_code in [code.strip() for code in s.region_code.split("/")]))
            sellers_pos = self.product_id.seller_ids.filtered(
                lambda s: s.name.id == self.seller_id.id and s.pos_code and (self.order_id.pos_id.pos_code in [code.strip() for code in s.pos_code.split("/")]))
            seller = sellers_pos and sellers_pos[0] or (sellers_region and sellers_region[0]) or False
            self.update({
                'price_unit': seller and seller.price or 0.0,
            })
        else:
            self.update({
                'price_unit': False,
            })

    @api.multi
    def write(self, vals):
        for line in self:
            if line.order_id.state == 'pending':
                if vals.get('product_uom_qty'):
                    line.order_id.message_post(body="Product  " + line.product_id.name_get()[0][1] +":Ordered Quantity"
                                               + str(line.product_uom_qty) + "➞"
                                               + str(vals.get('product_uom_qty')))
        return super(StoreOrderLine, self).write(vals)



