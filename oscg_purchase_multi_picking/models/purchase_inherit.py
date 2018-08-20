# -*- coding: utf-8 -*-
from odoo import  api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero, float_compare


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'


    @api.multi
    def _create_picking(self):
        StockPicking = self.env['stock.picking']
        for order in self:
            if any([ptype in ['product', 'consu'] for ptype in order.order_line.mapped('product_id.type')]):
                pickings = order.picking_ids.filtered(lambda x: x.state not in ('done','cancel'))
                if not pickings:
                    res = order._prepare_picking()
                    for r in res:
                        pickings += StockPicking.create(r)
                # else:
                #     picking = pickings[0]
                for picking in pickings:
                    moves = order.order_line._create_stock_moves(picking)
                    moves = moves.filtered(lambda x: x.state not in ('done', 'cancel'))._action_confirm()
                    seq = 0
                    for move in sorted(moves, key=lambda move: move.date_expected):
                        seq += 5
                        move.sequence = seq
                    moves._action_assign()
                    picking.message_post_with_view('mail.message_origin_link',
                        values={'self': picking, 'origin': order},
                        subtype_id=self.env.ref('mail.mt_note').id)
        return True

    @api.model
    def _prepare_picking(self):
        res = []
        for line in self.order_line:
            if not self.group_id:
                self.group_id = self.group_id.create({
                    'name': self.name,
                    'partner_id': self.partner_id.id
                })
            if not self.partner_id.property_stock_supplier.id:
                raise UserError(_("You must set a Vendor Location for this partner %s") % self.partner_id.name)
            if line.picking_type_id.id in [r.get('picking_type_id') for r in res]:
                continue
            else:
                res.append({
                    'picking_type_id': line.picking_type_id and line.picking_type_id.id or self.picking_type_id.id,
                    'partner_id': self.partner_id.id,
                    'date': self.date_order,
                    'origin': self.name,
                    'location_dest_id': line.picking_type_id and line.picking_type_id.default_location_dest_id.id or self._get_destination_location(),
                    'location_id': self.partner_id.property_stock_supplier.id,
                    'company_id': self.company_id.id,
                })
        return res


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    picking_type_id = fields.Many2one('stock.picking.type', 'Operation Type',
                                      help="This will determine operation type of incoming shipment")


    @api.multi
    def _prepare_stock_moves(self, picking):
        """ Prepare the stock moves data for one order line. This function returns a list of
        dictionary ready to be used in stock.move's create()
        """
        self.ensure_one()
        res = []
        if self.product_id.type not in ['product', 'consu']:
            return res
        qty = 0.0
        price_unit = self._get_stock_move_price_unit()
        for move in self.move_ids.filtered(lambda x: x.state != 'cancel' and not x.location_dest_id.usage == "supplier"):
            qty += move.product_qty
        template = {
            'name': self.name or '',
            'product_id': self.product_id.id,
            'product_uom': self.product_uom.id,
            'date': self.order_id.date_order,
            'date_expected': self.date_planned,
            'location_id': self.order_id.partner_id.property_stock_supplier.id,
            'location_dest_id': self.order_id._get_destination_location(),
            'picking_id': picking.id,
            'partner_id': self.order_id.dest_address_id.id,
            'move_dest_ids': [(4, x) for x in self.move_dest_ids.ids],
            'state': 'draft',
            'purchase_line_id': self.id,
            'company_id': self.order_id.company_id.id,
            'price_unit': price_unit,
            'picking_type_id': self.order_id.picking_type_id.id,
            'group_id': self.order_id.group_id.id,
            'origin': self.order_id.name,
            'route_ids': self.order_id.picking_type_id.warehouse_id and [(6, 0, [x.id for x in self.order_id.picking_type_id.warehouse_id.route_ids])] or [],
            'warehouse_id': self.order_id.picking_type_id.warehouse_id.id,
        }
        diff_quantity = self.product_qty - qty
        if float_compare(diff_quantity, 0.0,  precision_rounding=self.product_uom.rounding) > 0:
            template['product_uom_qty'] = diff_quantity
            res.append(template)
        return res

    @api.multi
    def _create_stock_moves(self, picking):
        moves = self.env['stock.move']
        done = self.env['stock.move'].browse()
        for line in self:
            if line.picking_type_id.id == picking.picking_type_id.id or not line.picking_type_id:
                for val in line._prepare_stock_moves(picking):
                    done += moves.create(val)
        return done
