#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
"""
Informe de ventas para el productor: entradas vendidas, recaudación online, comisión del
servicio y neto a liquidar. No incluye datos personales de los compradores.

Criterios:
- Cuentan las entradas de pedidos pagados, no anuladas y que no son de prueba.
- "Online" = todo lo cobrado por la plataforma (tienda, widget). La comisión se calcula
  solo sobre eso.
- Los boletos impresos de boletería (canal api.boleteria) se informan aparte: ese dinero
  lo cobra el teatro en persona, no la plataforma.
"""
import io
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils.timezone import now

from pretix.base.models import Order, OrderPosition
from pretix.base.templatetags.money import money_filter

BOLETERIA_CHANNEL = 'api.boleteria'
CENT = Decimal('0.01')


def event_commission(event):
    return Decimal(event.settings.get('andina_comision', default='0') or '0')


def event_producer_team(event):
    return event.settings.get('andina_productor_team', as_type=int, default=None)


def build_report(event, subevent=None):
    pct = event_commission(event)
    base = OrderPosition.objects.filter(
        order__event=event, order__status=Order.STATUS_PAID, order__testmode=False,
    )
    if subevent:
        base = base.filter(subevent=subevent)
    online = base.exclude(order__sales_channel__identifier=BOLETERIA_CHANNEL)
    box = base.filter(order__sales_channel__identifier=BOLETERIA_CHANNEL)

    names = {i.pk: str(i.name) for i in event.items.all()}
    by_product = [
        {'name': names.get(r['item'], '—'), 'count': r['n'], 'total': r['total'] or Decimal('0')}
        for r in online.values('item').annotate(n=Count('id'), total=Sum('price')).order_by('item')
    ]

    by_date = []
    if event.has_subevents and not subevent:
        dates = {se.pk: se for se in event.subevents.all()}
        for r in online.values('subevent').annotate(n=Count('id'), total=Sum('price')).order_by('subevent'):
            se = dates.get(r['subevent'])
            by_date.append({
                'name': '{} – {}'.format(se.name, se.get_date_range_display()) if se else '—',
                'sort': se.date_from if se else None,
                'count': r['n'], 'total': r['total'] or Decimal('0'),
            })
        by_date.sort(key=lambda d: (d['sort'] is None, d['sort']))

    by_day = [
        {'day': r['day'], 'count': r['n'], 'total': r['total'] or Decimal('0')}
        for r in online.annotate(day=TruncDate('order__datetime')).values('day')
        .annotate(n=Count('id'), total=Sum('price')).order_by('-day')
    ]

    gross = sum((p['total'] for p in by_product), Decimal('0'))
    commission = (gross * pct / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    box_stats = box.aggregate(n=Count('id'), total=Sum('price'))
    return {
        'event': event,
        'subevent': subevent,
        'currency': event.currency,
        'commission_pct': pct,
        'tickets': sum(p['count'] for p in by_product),
        'gross': gross,
        'commission': commission,
        'net': gross - commission,
        'by_product': by_product,
        'by_date': by_date,
        'by_day': by_day,
        'box_count': box_stats['n'] or 0,
        'box_value': box_stats['total'] or Decimal('0'),
        'generated': now(),
    }


def render_pdf(report, producer_name=''):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    cur = report['currency']

    def money(v):
        return money_filter(v, cur)

    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm,
                            title='Liquidación de ventas', author='AndinaTickets')
    accent = colors.HexColor('#5b2a73')

    def table(rows, widths, bold_last=False):
        t = Table(rows, colWidths=widths, hAlign='LEFT')
        style = [
            ('BACKGROUND', (0, 0), (-1, 0), accent),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#bfbfbf')),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7f3f9')]),
        ]
        if bold_last:
            style.append(('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'))
        t.setStyle(TableStyle(style))
        return t

    ev = report['event']
    title = str(ev.name) + (' – {}'.format(report['subevent'].get_date_range_display()) if report['subevent'] else '')
    story = [
        Paragraph('Liquidación de ventas', styles['Title']),
        Paragraph(title, styles['Heading2']),
        Paragraph('Generado el {} · {}'.format(
            report['generated'].astimezone(ev.timezone).strftime('%d/%m/%Y %H:%M'),
            'Productor: ' + producer_name if producer_name else 'AndinaTickets'), styles['Normal']),
        Spacer(1, 6 * mm),
        Paragraph('Resumen (ventas online)', styles['Heading3']),
        table([
            ['Concepto', 'Importe'],
            ['Entradas vendidas', str(report['tickets'])],
            ['Recaudación', money(report['gross'])],
            ['Comisión del servicio ({} %)'.format(report['commission_pct']), '− ' + money(report['commission'])],
            ['Neto para el productor', money(report['net'])],
        ], [110 * mm, 50 * mm], bold_last=True),
        Spacer(1, 6 * mm),
    ]
    if report['by_product']:
        story += [Paragraph('Por tipo de entrada', styles['Heading3']), table(
            [['Entrada', 'Cantidad', 'Recaudación']] +
            [[p['name'], str(p['count']), money(p['total'])] for p in report['by_product']],
            [90 * mm, 30 * mm, 40 * mm]), Spacer(1, 6 * mm)]
    if report['by_date']:
        story += [Paragraph('Por función', styles['Heading3']), table(
            [['Función', 'Cantidad', 'Recaudación']] +
            [[d['name'], str(d['count']), money(d['total'])] for d in report['by_date']],
            [90 * mm, 30 * mm, 40 * mm]), Spacer(1, 6 * mm)]
    if report['by_day']:
        story += [Paragraph('Por día de venta', styles['Heading3']), table(
            [['Día', 'Cantidad', 'Recaudación']] +
            [[d['day'].strftime('%d/%m/%Y'), str(d['count']), money(d['total'])] for d in report['by_day']],
            [90 * mm, 30 * mm, 40 * mm]), Spacer(1, 6 * mm)]
    story += [
        Paragraph('Boletería', styles['Heading3']),
        Paragraph('Boletos impresos cargados: {} (valor nominal {}). Ese dinero se cobra en el teatro y no forma '
                  'parte de esta liquidación.'.format(report['box_count'], money(report['box_value'])),
                  styles['Normal']),
        Spacer(1, 6 * mm),
        Paragraph('Incluye entradas de pedidos pagados y no anulados. No incluye pedidos de prueba.', styles['Italic']),
    ]
    doc.build(story)
    return buf.getvalue()
