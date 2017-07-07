# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.shortcuts import render, HttpResponse
from StringIO import StringIO
from lxml import etree
from tempfile import NamedTemporaryFile
from datetime import datetime
import PyPDF2
import logging
import time
import pdb

logger = logging.getLogger(__name__)

try:
    from PyPDF2 import PdfFileWriter, PdfFileReader
    from PyPDF2.generic import DictionaryObject, DecodedStreamObject,\
        NameObject, createStringObject, ArrayObject
except ImportError:
    logger.debug('Cannot import PyPDF2')

# dummy data
ZUGFERD_LEVEL = 'comfort'
ZUGFERD_FILENAME = 'ZUGFeRD-invoice.xml'
STATE = 'open'
INVOICE = {
    'state': 'open',
    'number': '123456',
    'comment': 'I like Illya because he is perfect guy',
    'type': 'our_invoice',
    'company_id': {
        'name': 'IT Light',
        'vat': '19',
        'partner_id': {
            'zip': '66032',
            'street': 'street A',
            'street2': 'Tower',
            'country_id': 'US',
            'city': 'New York'
        }
    },
    'partner_id': {
        'zip': '66032',
        'street': 'street A',
        'street2': 'Tower',
        'country_id': 'US',
        'city': 'New York'
    },
    'commercial_partner_id': {
        'ref': 'comercial_partner_id_reference',
        'name': 'Big Company',
        'vat': '28'
    },
    'partner_bank_id': {
        'bank_account_link': 'fixed',
        'fixed_journal_id': {
            'bank_account_id': '123457'
        }
    },
    'currency_id': {
        'name': 'eur',
        'decimal_places': 3
    },
    'tax_line_ids': [
        {
            'tax_id': {
                'unece_type_code': '',
                'unece_categ_code': '',
                'amount_type': 'kg'
            },
            'amount': 1,
            'base': 1
        },
        {
            'tax_id': {
                'unece_type_code': '',
                'unece_categ_code': '',
                'amount_type': 'kg'
            },
            'amount': 1,
            'base': 1
        }
    ],
    'payment_mode_id': {
        'note': 'infomation about payment mode',
        'payment_method_id': {
            'unece_code': 'CBFBUY',
            'name': ''
        }
    },
    'payment_term_id': {
        'name': 'paypal'
    },
    'fiscal_position_id': {
        'note': 'information about fiscal postion'
    },
    'date_due': '2017213',
    'amount_untaxed': 235,
    'amount_tax': 120,
    'amount_total': 375,
    'residual': 56,
    'user': {
        'company_Id': ''
    }
}

INVOCE_LINE_IDS = [
    {
        'price_unit': '',
        'quantity': 2,
        'price_subtotal': 3,
        'discount': '',
        'name': 'Item A',
        'product_id': {
            'barcode': '',
            'default_code': '',
            'description_sale': ''
        },
        'invoice_line_tax_ids': {
            'unece_type_code': '',
            'unece_categ_code': '',
            'amount_type': 'percent',
            'amonut': ''
        }
    },
    {
        'price_unit': '',
        'quantity': 2,
        'price_subtotal': 3,
        'discount': '',
        'name': 'Item A',
        'product_id': {
            'barcode': '',
            'default_code': '',
            'description_sale': ''
        },
        'invoice_line_tax_ids': {
            'unece_type_code': '',
            'unece_categ_code': '',
            'amount_type': '',
            'amonut': ''
        }
    }
]

DECIMAL_PLACES = {
    'product_price': '3',
    'discount': '3',
    'product_unit_measure': '2'
}

# root of xml document
root = None

def _add_date(node_name, date_datetime, parent_node, ns):
    """
        add date to xml
        Params:
        "
            node_name: node name to be added
            date_datetime: date value to be added
            parent_node: parent node
            ns: namespace for xml
        "
    """
    date_node = etree.SubElement(parent_node, ns['ram'] + node_name)
    date_node_str = etree.SubElement(
        date_node, ns['udt'] + 'DateTimeString', format='102')
    date_node_str.text = date_datetime

def _add_address_block(partner, parent_node, ns):
    """
        add address to xml
        Params:
        "
            partner: values to be saved
            partner_node: place where partner is saved
            ns: namespace for xml
        "
    """
    address = etree.SubElement(
        parent_node, ns['ram'] + 'PostalTradeAddress')
    if partner['zip']:
        address_zip = etree.SubElement(
            address, ns['ram'] + 'PostcodeCode')
        address_zip.text = partner['zip']
    if partner['street']:
        address_street = etree.SubElement(
            address, ns['ram'] + 'LineOne')
        address_street.text = partner['street']
        if partner['street2']:
            address_street2 = etree.SubElement(
                address, ns['ram'] + 'LineTwo')
            address_street2.text = partner['street2']
    if partner['city']:
        address_city = etree.SubElement(
            address, ns['ram'] + 'CityName')
        address_city.text = partner['city']
    if partner['country_id']:
        address_country = etree.SubElement(
            address, ns['ram'] + 'CountryID')
        address_country.text = partner['country_id']

def compute_all(price_unit, currency=None, quantity=1.0, product=None, partner=None):
    """ 
        Returns all information required to apply taxes (in self + their children in case of a tax goup).
            We consider the sequence of the parent for group of taxes.
                Eg. considering letters as taxes and alphabetic order as sequence :
                [G, B([A, D, F]), E, C] will be computed as [A, D, F, C, E, G]

        RETURN: {
            'total_excluded': 0.0,    # Total without taxes
            'total_included': 0.0,    # Total with taxes
            'taxes': [{               # One dict for each tax in self and their children
                'id': int,
                'name': str,
                'amount': float,
                'sequence': int,
                'account_id': int,
                'refund_account_id': int,
                'analytic': boolean,
            }]
        } 
    """
    if len(self) == 0:
        company_id = self.env.user.company_id
    else:
        company_id = self[0].company_id
    if not currency:
        currency = company_id.currency_id
    taxes = []
    # By default, for each tax, tax amount will first be computed
    # and rounded at the 'Account' decimal precision for each
    # PO/SO/invoice line and then these rounded amounts will be
    # summed, leading to the total amount for that tax. But, if the
    # company has tax_calculation_rounding_method = round_globally,
    # we still follow the same method, but we use a much larger
    # precision when we round the tax amount for each line (we use
    # the 'Account' decimal precision + 5), and that way it's like
    # rounding after the sum of the tax amounts of each line
    prec = currency.decimal_places

    # In some cases, it is necessary to force/prevent the rounding of the tax and the total
    # amounts. For example, in SO/PO line, we don't want to round the price unit at the
    # precision of the currency.
    # The context key 'round' allows to force the standard behavior.
    round_tax = False if company_id.tax_calculation_rounding_method == 'round_globally' else True
    round_total = True
    if 'round' in self.env.context:
        round_tax = bool(self.env.context['round'])
        round_total = bool(self.env.context['round'])

    if not round_tax:
        prec += 5

    base_values = self.env.context.get('base_values')
    if not base_values:
        total_excluded = total_included = base = round(price_unit * quantity, prec)
    else:
        total_excluded, total_included, base = base_values

    # Sorting key is mandatory in this case. When no key is provided, sorted() will perform a
    # search. However, the search method is overridden in account.tax in order to add a domain
    # depending on the context. This domain might filter out some taxes from self, e.g. in the
    # case of group taxes.
    for tax in self.sorted(key=lambda r: r.sequence):
        if tax.amount_type == 'group':
            children = tax.children_tax_ids.with_context(base_values=(total_excluded, total_included, base))
            ret = children.compute_all(price_unit, currency, quantity, product, partner)
            total_excluded = ret['total_excluded']
            base = ret['base'] if tax.include_base_amount else base
            total_included = ret['total_included']
            tax_amount = total_included - total_excluded
            taxes += ret['taxes']
            continue

        tax_amount = tax._compute_amount(base, price_unit, quantity, product, partner)
        if not round_tax:
            tax_amount = round(tax_amount, prec)
        else:
            tax_amount = currency.round(tax_amount)

        if tax.price_include:
            total_excluded -= tax_amount
            base -= tax_amount
        else:
            total_included += tax_amount

        # Keep base amount used for the current tax
        tax_base = base

        if tax.include_base_amount:
            base += tax_amount

        taxes.append({
            'id': tax.id,
            'name': tax.with_context(**{'lang': partner.lang} if partner else {}).name,
            'amount': tax_amount,
            'base': tax_base,
            'sequence': tax.sequence,
            'account_id': tax.account_id.id,
            'refund_account_id': tax.refund_account_id.id,
            'analytic': tax.analytic,
        })

    return {
        'taxes': sorted(taxes, key=lambda k: k['sequence']),
        'total_excluded': currency.round(total_excluded) if round_total else total_excluded,
        'total_included': currency.round(total_included) if round_total else total_included,
        'base': base,
    }

def _add_trade_agreement_block(trade_transaction, ns):
    """
        add Seller and Buyer information to xml
    """
    trade_agreement = etree.SubElement(
        trade_transaction,
        ns['ram'] + 'ApplicableSupplyChainTradeAgreement')
    company = INVOICE['company_id']

    ## Begin seller block
    seller = etree.SubElement(
        trade_agreement, ns['ram'] + 'SellerTradeParty')
    seller_name = etree.SubElement(
        seller, ns['ram'] + 'Name')
    seller_name.text = company['name']
    
    # Only with EXTENDED profile
    # INVOICE['_add_trade_contact_block(
    #    INVOICE['user_id.partner_id or company.partner_id, seller, ns)
    _add_address_block(company['partner_id'], seller, ns)
    if company['vat']:
        seller_tax_reg = etree.SubElement(
            seller, ns['ram'] + 'SpecifiedTaxRegistration')
        seller_tax_reg_id = etree.SubElement(
            seller_tax_reg, ns['ram'] + 'ID', schemeID='VA')
        seller_tax_reg_id.text = company['vat']

    ## Begin buyer block
    buyer = etree.SubElement(
        trade_agreement, ns['ram'] + 'BuyerTradeParty')
    if INVOICE['commercial_partner_id']['ref']:
        buyer_id = etree.SubElement(
            buyer, ns['ram'] + 'ID')
        buyer_id.text = INVOICE['commercial_partner_id']['ref']
    buyer_name = etree.SubElement(
        buyer, ns['ram'] + 'Name')
    buyer_name.text = INVOICE['commercial_partner_id']['name']
    # Only with EXTENDED profile
    # if INVOICE['commercial_partner_id != INVOICE['partner_id:
    #    INVOICE['_add_trade_contact_block(
    #        INVOICE['partner_id, buyer, ns)
    _add_address_block(INVOICE['partner_id'], buyer, ns)
    if INVOICE['commercial_partner_id']['vat']:
        buyer_tax_reg = etree.SubElement(
            buyer, ns['ram'] + 'SpecifiedTaxRegistration')
        buyer_tax_reg_id = etree.SubElement(
            buyer_tax_reg, ns['ram'] + 'ID', schemeID='VA')
        buyer_tax_reg_id.text = INVOICE['commercial_partner_id']['vat']

def _add_trade_delivery_block(trade_transaction, ns):
    """
        add delivery information to xml
        Parms:
        "
            trade_transaction: parent node
        "
    """
    trade_agreement = etree.SubElement(
        trade_transaction,
        ns['ram'] + 'ApplicableSupplyChainTradeDelivery')
    return trade_agreement

def _add_trade_settlement_block(trade_transaction, sign, ns):
    """
        add settlement information to xml
        Parms:
        "
            trade_transaction: parent node
            sign: [1: "invoice", -1: "refund"]
            ns: namespace for xml
        "
    """
    ## Begin payment reference
    inv_currency_name = INVOICE['currency_id']['name']
    prec = INVOICE['currency_id']['decimal_places']
    trade_settlement = etree.SubElement(
        trade_transaction,
        ns['ram'] + 'ApplicableSupplyChainTradeSettlement')
    payment_ref = etree.SubElement(
        trade_settlement, ns['ram'] + 'PaymentReference')
    payment_ref.text = INVOICE['number'] or INVOICE['state']
    invoice_currency = etree.SubElement(
        trade_settlement, ns['ram'] + 'InvoiceCurrencyCode')
    invoice_currency.text = inv_currency_name
    if (
            INVOICE['payment_mode_id'] and
            not INVOICE['payment_mode_id']['payment_method_id']['unece_code']):
        try:
            raise Exception("Missing UNECE code on payment export type '%s'" % INVOICE['payment_mode_id']['payment_method_id']['name'])
        except Exception as error:
            print('caught this error: ' + repr(error))

    if (
            INVOICE['type'] == 'out_invoice' or
            (INVOICE['payment_mode_id'] and
                INVOICE['payment_mode_id']['payment_method_id']['unece_code']
                not in [31, 42])):
        _add_trade_settlement_payment_means_block(trade_settlement, sign, ns)
    tax_basis_total = 0.0

    # add list of tax information to xml
    if INVOICE['tax_line_ids']:
        for tline in INVOICE['tax_line_ids']:
            tax = tline['tax_id']
            if not tax['unece_type_code']:
                try:
                    raise Exception("Missing UNECE Tax Type on tax '%s'" % tax['name'])
                except Exception as error:
                    print('caught this error: ' + repr(error))

            if not tax['unece_categ_code']:
                try:
                    raise Exception("Missing UNECE Tax Category on tax '%s'" % tax['name'])
                except Exception as error:
                    print('caught this error: ' + repr(error))
                
            trade_tax = etree.SubElement(
                trade_settlement, ns['ram'] + 'ApplicableTradeTax')
            amount = etree.SubElement(
                trade_tax, ns['ram'] + 'CalculatedAmount',
                currencyID=inv_currency_name)
            amount.text = unicode(tline['amount'] * sign)
            tax_type = etree.SubElement(
                trade_tax, ns['ram'] + 'TypeCode')
            tax_type.text = tax['unece_categ_code']

            # if (
            #         tax.unece_categ_code != 'S' and
            #         float_is_zero(tax.amount, precision_digits=prec) and
            #         INVOICE['fiscal_position_id'] and
            #         INVOICE['fiscal_position_id']['note']):
            #     exemption_reason = etree.SubElement(
            #         trade_tax, ns['ram'] + 'ExemptionReason')
            #     exemption_reason.text = with_context(
            #         lang=INVOICE['partner_id']['lang'] or 'en_US').\
            #         fiscal_position_id['note']

            base = etree.SubElement(
                trade_tax,
                ns['ram'] + 'BasisAmount', currencyID=inv_currency_name)
            base.text = unicode(tline['base'] * sign)
            tax_basis_total += tline['base']
            tax_categ_code = etree.SubElement(
                trade_tax, ns['ram'] + 'CategoryCode')
            tax_categ_code.text = tax['unece_categ_code']
            if tax['amount_type'] == 'percent':
                percent = etree.SubElement(
                    trade_tax, ns['ram'] + 'ApplicablePercent')
                percent.text = unicode(tax.amount)
    trade_payment_term = etree.SubElement(
        trade_settlement, ns['ram'] + 'SpecifiedTradePaymentTerms')
    trade_payment_term_desc = etree.SubElement(
        trade_payment_term, ns['ram'] + 'Description')
    # The 'Description' field of SpecifiedTradePaymentTerms
    # is a required field, so we must always give a value
    if INVOICE['payment_term_id']:
        trade_payment_term_desc.text = INVOICE['payment_term_id']['name']
    else:
        trade_payment_term_desc.text = 'No specific payment term selected'
    
    # add due date(deadline) of pay
    if INVOICE['date_due']:
        date_due_dt = INVOICE['date_due']
        _add_date('DueDateDateTime', date_due_dt, trade_payment_term, ns)

    sums = etree.SubElement(
        trade_settlement,
        ns['ram'] + 'SpecifiedTradeSettlementMonetarySummation')
    line_total = etree.SubElement(
        sums, ns['ram'] + 'LineTotalAmount', currencyID=inv_currency_name)
    line_total.text = '%0.*f' % (prec, INVOICE['amount_untaxed'] * sign)
    charge_total = etree.SubElement(
        sums, ns['ram'] + 'ChargeTotalAmount',
        currencyID=inv_currency_name)
    charge_total.text = '0.00'
    allowance_total = etree.SubElement(
        sums, ns['ram'] + 'AllowanceTotalAmount',
        currencyID=inv_currency_name)
    allowance_total.text = '0.00'
    tax_basis_total_amt = etree.SubElement(
        sums, ns['ram'] + 'TaxBasisTotalAmount',
        currencyID=inv_currency_name)
    tax_basis_total_amt.text = '%0.*f' % (prec, tax_basis_total * sign)
    tax_total = etree.SubElement(
        sums, ns['ram'] + 'TaxTotalAmount', currencyID=inv_currency_name)
    tax_total.text = '%0.*f' % (prec, INVOICE['amount_tax'] * sign)
    total = etree.SubElement(
        sums, ns['ram'] + 'GrandTotalAmount', currencyID=inv_currency_name)
    total.text = '%0.*f' % (prec, INVOICE['amount_total'] * sign)
    prepaid = etree.SubElement(
        sums, ns['ram'] + 'TotalPrepaidAmount',
        currencyID=inv_currency_name)
    residual = etree.SubElement(
        sums, ns['ram'] + 'DuePayableAmount', currencyID=inv_currency_name)
    prepaid.text = '%0.*f' % (
        prec, (INVOICE['amount_total'] - INVOICE['residual']) * sign)
    residual.text = '%0.*f' % (prec, INVOICE['residual'] * sign)

def _add_trade_settlement_payment_means_block(trade_settlement, sign, ns):
    """
        add settlement payment information to xml
        Params: 
        "
            trade_settlement: place where settlement payment information should be saved
            sign: [1: "invoice", -1: "refund"]
            ns: namespace for xml
        "
    """
    payment_means = etree.SubElement(
        trade_settlement,
        ns['ram'] + 'SpecifiedTradeSettlementPaymentMeans')
    payment_means_code = etree.SubElement(
        payment_means, ns['ram'] + 'TypeCode')
    payment_means_info = etree.SubElement(
        payment_means, ns['ram'] + 'Information')
    if INVOICE['payment_mode_id']:
        payment_means_code.text = INVOICE['payment_mode_id']['payment_method_id']['unece_code']
        payment_means_info.text = INVOICE['payment_mode_id']['note'] or INVOICE['payment_mode_id']['name']
    else:
        payment_means_code.text = '31'  # 31 = Wire transfer
        payment_means_info.text = 'Wire transfer'
        logger.warning(
            'Missing payment mode on invoice ID %d. '
            'Using 31 (wire transfer) as UNECE code as fallback '
            'for payment mean',
            INVOICE['id'])
    if payment_means_code.text in ['31', '42']:
        partner_bank = INVOICE['partner_bank_id']
        if (
                not partner_bank and
                INVOICE['partner_bank_id'] and
                INVOICE['partner_bank_id']['bank_account_link'] == 'fixed' and
                INVOICE['partner_bank_id']['fixed_journal_id']):
            partner_bank = INVOICE['partner_bank_id']['fixed_journal_id']['bank_account_id']
        
        # check if partner has bank and it is international bank
        if partner_bank and partner_bank.acc_type == 'iban':
            payment_means_bank_account = etree.SubElement(
                payment_means,
                ns['ram'] + 'PayeePartyCreditorFinancialAccount')
            iban = etree.SubElement(
                payment_means_bank_account, ns['ram'] + 'IBANID')
            iban.text = partner_bank.sanitized_acc_number
            if partner_bank.bank_bic:
                payment_means_bank = etree.SubElement(
                    payment_means,
                    ns['ram'] +
                    'PayeeSpecifiedCreditorFinancialInstitution')
                payment_means_bic = etree.SubElement(
                    payment_means_bank, ns['ram'] + 'BICID')
                payment_means_bic.text = partner_bank.bank_bic
                if partner_bank.bank_name:
                    bank_name = etree.SubElement(
                        payment_means_bank, ns['ram'] + 'Name')
                    bank_name.text = partner_bank.bank_name

def _add_document_context_block(root, nsmap, ns):
    """
        set the invoice type
        value can be "basic", "comfort" and "expanded"
    """
    doc_ctx = etree.SubElement(root, ns['rsm'] + 'SpecifiedExchangedDocumentContext')
    if INVOICE['state'] not in ('open', 'paid'):
        test_indic = etree.SubElement(doc_ctx, ns['ram'] + 'TestIndicator')
        indic = etree.SubElement(test_indic, ns['udt'] + 'Indicator')
        indic.text = 'true'
    ctx_param = etree.SubElement(doc_ctx, ns['ram'] + 'GuidelineSpecifiedDocumentContextParameter')
    ctx_param_id = etree.SubElement(ctx_param, ns['ram'] + 'ID')
    ctx_param_id.text = '%s:%s' % (nsmap['rsm'], ZUGFERD_LEVEL)

def _add_header_block(root, ns):
    """
        add header information to xml root element
    """
    header_doc = etree.SubElement(
        root, ns['rsm'] + 'HeaderExchangedDocument')
    header_doc_id = etree.SubElement(header_doc, ns['ram'] + 'ID')
    
    # if invoice state is set, then add invoice id
    # else add the state
    if INVOICE['state'] in ('open', 'paid'):
        header_doc_id.text = INVOICE['number']
    else:
        header_doc_id.text = INVOICE['state']
    header_doc_name = etree.SubElement(header_doc, ns['ram'] + 'Name')
    if INVOICE['type'] == 'out_refund':
        header_doc_name.text = 'Refund'
    else:
        header_doc_name.text = 'Invoice'
    
    header_doc_typecode = etree.SubElement(
        header_doc, ns['ram'] + 'TypeCode')
    header_doc_typecode.text = '380'

    # get the today's date and add to root
    date_invoice_dt = time.strftime("%Y%m%d")
    _add_date('IssueDateTime', date_invoice_dt, header_doc, ns)

    # add comment to xml
    if INVOICE['comment']:
        note = etree.SubElement(header_doc, ns['ram'] + 'IncludedNote')
        content_note = etree.SubElement(note, ns['ram'] + 'Content')
        content_note.text = INVOICE['comment']

def _check_xml_schema(xml_string, xsd_file):
    """
        Validate the XML file against the XSD
        Param:
        "
            xml_string: xml string to be checked
            xml_file: sample invoice xml file
        "
    """
    xsd_string = open(xsd_file, 'rb')
    print xsd_string
    # pdb.set_trace()
    xsd_etree_obj = etree.parse(xsd_string)
    official_schema = etree.XMLSchema(xsd_etree_obj)
    
    try:
        t = etree.parse(StringIO(xml_string))
        official_schema.assertValid(t)
    except Exception, e:
        # if the validation of the XSD fails, we arrive here
        logger = logging.getLogger(__name__)
        logger.warning(
            "The XML file is invalid against the XML Schema Definition")
        logger.warning(xml_string)
        logger.warning(e)
        raise (
            "The generated XML file is not valid against the official "
            "XML Schema Definition. The generated XML file and the "
            "full error have been written in the server logs. "
            "Here is the error, which may give you an idea on the "
            "cause of the problem : %s.") % unicode(e)
    return True

def _add_invoice_line_block(trade_transaction, iline, line_number, sign, ns):
    """
        add invoice items into xml
        Params:
        "
            trade_transaction: parent node
            iline: each line of invoice table
            line_number: line number
            sign: [1: "invoice", -1: "refund"]
            ns: namespace for xml
        "
    """
    # deciaml palces for product price
    pp_prec = DECIMAL_PLACES['product_price']
    # deciaml palces for discount price
    disc_prec = DECIMAL_PLACES['discount']
    # deciaml palces for product price
    qty_prec = DECIMAL_PLACES['product_unit_measure']
    inv_currency_name = INVOICE['currency_id']['name']
    line_item = etree.SubElement(
        trade_transaction,
        ns['ram'] + 'IncludedSupplyChainTradeLineItem')
    line_doc = etree.SubElement(
        line_item, ns['ram'] + 'AssociatedDocumentLineDocument')
    etree.SubElement(
        line_doc, ns['ram'] + 'LineID').text = unicode(line_number)
    line_trade_agreement = etree.SubElement(
        line_item,
        ns['ram'] + 'SpecifiedSupplyChainTradeAgreement')
    # convert gross price_unit to tax_excluded value
    taxres = iline.invoice_line_tax_ids.compute_all(iline.price_unit)
    gross_price_val = round(
        taxres['total_excluded'], precision_digits=pp_prec)
    # Use oline.price_subtotal/qty to compute net unit price to be sure
    # to get a *tax_excluded* net unit price
    if float_is_zero(iline['quantity'], precision_digits=qty_prec):
        net_price_val = 0.0
    else:
        net_price_val = round(
            iline['price_subtotal'] / float(iline['quantity']),
            precision_digits=pp_prec)
    gross_price = etree.SubElement(
        line_trade_agreement,
        ns['ram'] + 'GrossPriceProductTradePrice')
    gross_price_amount = etree.SubElement(
        gross_price, ns['ram'] + 'ChargeAmount',
        currencyID=inv_currency_name)
    gross_price_amount.text = unicode(gross_price_val)
    fc_discount = float_compare(
        iline['discount'], 0.0, precision_digits=disc_prec)
    if fc_discount in [-1, 1]:
        trade_allowance = etree.SubElement(
            gross_price, ns['ram'] + 'AppliedTradeAllowanceCharge')
        charge_indic = etree.SubElement(
            trade_allowance, ns['ram'] + 'ChargeIndicator')
        indicator = etree.SubElement(
            charge_indic, ns['udt'] + 'Indicator')
        if fc_discount == 1:
            indicator.text = 'false'
        else:
            indicator.text = 'true'
        actual_amount = etree.SubElement(
            trade_allowance, ns['ram'] + 'ActualAmount',
            currencyID=inv_currency_name)
        actual_amount_val = round(
            gross_price_val - net_price_val, precision_digits=pp_prec)
        actual_amount.text = unicode(abs(actual_amount_val))

    net_price = etree.SubElement(
        line_trade_agreement, ns['ram'] + 'NetPriceProductTradePrice')
    net_price_amount = etree.SubElement(
        net_price, ns['ram'] + 'ChargeAmount',
        currencyID=inv_currency_name)
    net_price_amount.text = unicode(net_price_val)
    line_trade_delivery = etree.SubElement(
        line_item, ns['ram'] + 'SpecifiedSupplyChainTradeDelivery')
    if iline['uom_id'] and iline['uom_id']['unece_code']:
        unitCode = iline['uom_id']['unece_code']
    else:
        unitCode = 'C62'
        if not iline['uom_id']:
            logger.warning(
                "No unit of measure on invoice line '%s', "
                "using C62 (piece) as fallback",
                iline['name'])
        else:
            logger.warning(
                'Missing UNECE Code on unit of measure %s, '
                'using C62 (piece) as fallback',
                iline['uom_id']['name'])
    billed_qty = etree.SubElement(
        line_trade_delivery, ns['ram'] + 'BilledQuantity',
        unitCode=unitCode)
    billed_qty.text = unicode(iline['quantity'] * sign)
    line_trade_settlement = etree.SubElement(
        line_item, ns['ram'] + 'SpecifiedSupplyChainTradeSettlement')
    if iline['invoice_line_tax_id']:
        for tax in iline['invoice_line_tax_ids']:
            trade_tax = etree.SubElement(
                line_trade_settlement,
                ns['ram'] + 'ApplicableTradeTax')
            trade_tax_typecode = etree.SubElement(
                trade_tax, ns['ram'] + 'TypeCode')
            if not tax['unece_type_code']:
                raise UserError(_(
                    "Missing UNECE Tax Type on tax '%s'")
                    % tax.name)
            trade_tax_typecode.text = tax['unece_type_code']
            trade_tax_categcode = etree.SubElement(
                trade_tax, ns['ram'] + 'CategoryCode')
            if not tax.unece_categ_code:
                raise UserError(_(
                    "Missing UNECE Tax Category on tax '%s'")
                    % tax.name)
            trade_tax_categcode.text = tax['unece_categ_code']
            if tax.amount_type == 'percent':
                trade_tax_percent = etree.SubElement(
                    trade_tax, ns['ram'] + 'ApplicablePercent')
                trade_tax_percent.text = unicode(tax['amount'])
    subtotal = etree.SubElement(
        line_trade_settlement,
        ns['ram'] + 'SpecifiedTradeSettlementMonetarySummation')
    subtotal_amount = etree.SubElement(
        subtotal, ns['ram'] + 'LineTotalAmount',
        currencyID=inv_currency_name)
    subtotal_amount.text = unicode(iline['price_subtotal'] * sign)
    trade_product = etree.SubElement(
        line_item, ns['ram'] + 'SpecifiedTradeProduct')
    if iline.product_id:
        if iline['product_id']['barcode']:
            barcode = etree.SubElement(
                trade_product, ns['ram'] + 'GlobalID', schemeID='0160')
            # 0160 = GS1 Global Trade Item Number (GTIN, EAN)
            barcode.text = iline['product_id']['barcode']
        if iline['product_id']['default_code']:
            product_code = etree.SubElement(
                trade_product, ns['ram'] + 'SellerAssignedID')
            product_code.text = iline['product_id']['default_code']
    product_name = etree.SubElement(
        trade_product, ns['ram'] + 'Name')
    product_name.text = iline.name
    if iline['product_id'] and iline['product_id']['default_code']:
        product_desc = etree.SubElement(
            trade_product, ns['ram'] + 'Description')
        product_desc.text = iline['product_id']['default_code']

# Create your views here.
def generate_zugferd_xml(request):
    """
        Generate zugferd_xml file
    """

    # mapping for namespaces for xml
    # inspired from https://github.com/OCA/edi/blob/10.0/account_invoice_factur-x/models/account_invoice.py
    nsmap = {
        'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
        'rsm': 'urn:ferd:CrossIndustryDocument:invoice:1p0',
        'ram': 'urn:un:unece:uncefact:data:standard:'
                'ReusableAggregateBusinessInformationEntity:12',
        'udt': 'urn:un:unece:uncefact:data:'
                'standard:UnqualifiedDataType:15',
        }

    # values for namespaces for xml
    # inspired from https://github.com/OCA/edi/blob/10.0/account_invoice_factur-x/models/account_invoice.py
    ns = {
        'rsm': '{urn:ferd:CrossIndustryDocument:invoice:1p0}',
        'ram': '{urn:un:unece:uncefact:data:standard:'
                'ReusableAggregateBusinessInformationEntity:12}',
        'udt': '{urn:un:unece:uncefact:data:standard:'
                'UnqualifiedDataType:15}',
        }
    
    # variable for type to check if it is "invoice" or "refund"
    # if type is invoice, then 1 or -1
    sign = 1
    
    # 2.pdf is sample Zugrefd pdf file  
    pdf_file = open('2.pdf', 'rb')
    read_pdf = PdfFileReader(pdf_file)
    # get the toal number of pages
    number_of_pages = read_pdf.getNumPages()
    
    root = etree.Element(ns['rsm'] + 'CrossIndustryDocument', nsmap=nsmap)
    
    # inspired from https://github.com/OCA/edi/blob/10.0/account_invoice_factur-x/models/account_invoice.py
    _add_document_context_block(root, nsmap, ns)
    _add_header_block(root, ns)

    trade_transaction = etree.SubElement(
        root, ns['rsm'] + 'SpecifiedSupplyChainTradeTransaction')

    _add_trade_agreement_block(trade_transaction, ns)
    _add_trade_delivery_block(trade_transaction, ns)
    _add_trade_settlement_block(trade_transaction, sign, ns)

    # # echo dummy data
    # xml_string = etree.tostring(
    #     root, pretty_print=True, encoding='UTF-8', xml_declaration=True)
    # isXml = _check_xml_schema(
    #     xml_string, 'data/ZUGFeRD1p0.xsd')
    # print "&&&&& XML Flag :   ", isXml

    line_number = 0
    for iline in INVOCE_LINE_IDS:
        line_number += 1
        _add_invoice_line_block(
            trade_transaction, iline, line_number, sign, ns)

    xml_string = etree.tostring(
        root, pretty_print=True, encoding='UTF-8', xml_declaration=True)
    _check_xml_schema(
        xml_string, 'data/ZUGFeRD1p0.xsd')
    logger.debug(
        'ZUGFeRD XML file generated for invoice ID')
    logger.debug(xml_string)
    print xml_string
    return HttpResponse("ok")

def pdf_is_zugfered(request, filename):
    """
        check if the pdf file is ZUGFeRE format
    """
    with open(filename, 'rb') as fp:
        pdf_content = fp.read()

    read_pdf = PdfFileReader(pdf_file)
    number_of_pages = read_pdf.getNumPages()
    
    pdb.set_trace()
    is_zugferd = False
    try:
        fd = StringIO(pdf_content)
        pdf = PdfFileReader(fd)
        pdf_root = pdf.trailer['/Root']
        logger.debug('pdf_root=%s', pdf_root)
        embeddedfiles = pdf_root['/Names']['/EmbeddedFiles']['/Names']
        print "Embeded Files:  ", embeddedfiles
        root = etree.Element(ns['rsm'] + 'CrossIndustryDocument', nsmap=nsmap)
        for embeddedfile in embeddedfiles:
            if embeddedfile == ZUGFERD_FILENAME:
                is_zugferd = True
                return is_zugferd
                break
    except:
        pass

    return is_zugferd
