#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django import forms

from .boleteria import PAYMENT_METHODS


class SalaForm(forms.Form):
    name = forms.CharField(label='Nombre de la sala', max_length=190,
                           widget=forms.TextInput(attrs={'placeholder': 'Teatro Principal'}))


NUMBERING_CHOICES = [
    ('corrida', 'Corrida (1, 2, 3…)'),
    ('impares', 'Impares (1, 3, 5…)'),
    ('pares', 'Pares (2, 4, 6…)'),
]

ROW_LABEL_CHOICES = [
    ('izquierda', 'A la izquierda'),
    ('derecha', 'A la derecha'),
    ('ambos', 'A los dos lados'),
]

PLACEMENT_CHOICES = [
    ('auto', 'Debajo de todo'),
    ('derecha', 'A la derecha de…'),
    ('izquierda', 'A la izquierda de…'),
    ('abajo', 'Debajo de…'),
]


class GeneratorForm(forms.Form):
    # Cada sector es independiente: en cada evento se conecta con su producto (Plan de butacas).
    # Su "categoría" de pretix es el mismo nombre (generate_sector la completa).
    name = forms.CharField(label='Nombre del sector', max_length=190,
                           help_text='Por ejemplo "Platea izquierda".')
    # Con un nombre, se está editando ese sector (botón "Editar" de la lista); vacío, es uno nuevo.
    editing = forms.CharField(required=False, widget=forms.HiddenInput)
    rows = forms.IntegerField(label='Filas', min_value=1, max_value=100, initial=10)
    seats_per_row = forms.IntegerField(label='Butacas por fila', min_value=1, max_value=200, initial=10)
    first_row = forms.CharField(label='Primera fila', max_length=3, initial='A',
                                help_text='Una letra (A, B…) o un número (1, 2…).')
    first_number = forms.IntegerField(label='Primera butaca', min_value=0, max_value=9999, initial=1,
                                      help_text='Con pares o impares, si no coincide se usa el siguiente.')
    numbering = forms.ChoiceField(label='Numeración', choices=NUMBERING_CHOICES, initial='corrida')
    row_labels = forms.ChoiceField(label='Letra de la fila', choices=ROW_LABEL_CHOICES, initial='izquierda',
                                   required=False)
    placement = forms.ChoiceField(label='Ubicación', choices=PLACEMENT_CHOICES, initial='auto', required=False,
                                  help_text='Al editar un sector, "Donde está" lo deja en su lugar.')
    reference = forms.ChoiceField(label='Al lado de', choices=[], required=False)
    right_to_left = forms.BooleanField(label='Numerar de derecha a izquierda', required=False)
    aisle_after = forms.IntegerField(label='Pasillo después de la butaca', min_value=0, max_value=199, initial=0,
                                     help_text='Contando desde la izquierda. 0 = sin pasillo.')
    stagger = forms.BooleanField(label='Filas alternadas (corridas media butaca)', required=False)
    curve = forms.IntegerField(label='Curva', min_value=0, max_value=300, initial=0,
                               help_text='0 = filas rectas. Más alto = las puntas más cerca del escenario.')
    seat_spacing = forms.IntegerField(label='Separación entre butacas', min_value=20, max_value=100, initial=35)
    row_spacing = forms.IntegerField(label='Separación entre filas', min_value=20, max_value=150, initial=40)

    def __init__(self, *args, sectors=(), **kwargs):
        """``sectors``: nombres de los sectores que ya tiene la sala (para "Al lado de")."""
        super().__init__(*args, **kwargs)
        self.sectors = list(sectors)
        self.fields['reference'].choices = [('', '—')] + [(s, s) for s in self.sectors]
        if self.editing_name:
            self.fields['name'].widget.attrs['readonly'] = 'readonly'
            self.fields['placement'].choices = [('auto', 'Donde está')] + PLACEMENT_CHOICES[1:]

    @property
    def editing_name(self):
        value = self.data.get('editing') if self.is_bound else self.initial.get('editing')
        return (value or '').strip()

    def clean(self):
        d = super().clean()
        if d.get('aisle_after') and d.get('seats_per_row') and d['aisle_after'] >= d['seats_per_row']:
            self.add_error('aisle_after', 'El pasillo tiene que quedar entre dos butacas de la fila.')
        name, editing = d.get('name'), self.editing_name
        if name and editing and name != editing:
            self.add_error('name', 'Para cambiarle el nombre a un sector, quitalo y creá uno nuevo.')
        elif name and not editing and name in self.sectors:
            self.add_error('name', 'Ya hay un sector "{}" en esta sala: usá otro nombre. Para cambiarlo, '
                                   'tocá "Editar" en la lista "Sectores".'.format(name))
        if d.get('placement') not in (None, '', 'auto'):
            if not d.get('reference'):
                self.add_error('reference', 'Elegí al lado de qué sector va.')
            elif d.get('reference') == d.get('name'):
                self.add_error('reference', 'Tiene que ser otro sector, no el mismo.')
        return d

    def sector_params(self):
        """(parámetros para generate_sector, lado de la letra, ubicación, sector de referencia)."""
        params = dict(self.cleaned_data)
        params.pop('editing', None)
        side = params.pop('row_labels') or 'izquierda'
        placement = params.pop('placement') or 'auto'
        reference = params.pop('reference') or None
        return params, side, placement, reference


class TicketsUploadForm(forms.Form):
    kind = forms.ChoiceField(
        label='Tipo de boletos',
        choices=(
            ('venta', 'Venta en boletería (se cobran al precio del producto)'),
            ('cortesia', 'Cortesía: entradas de regalo, sin cargo ($0)'),
        ),
        initial='venta',
        widget=forms.RadioSelect,
    )
    file = forms.FileField(
        label='Archivo CSV de boletos',
        help_text='Columnas: "codigo", "fila", "butaca" (opcional: "sector"). Separado por coma o punto y coma.',
    )

    def clean_file(self):
        f = self.cleaned_data['file']
        if not f.name.lower().endswith('.csv'):
            raise forms.ValidationError('El archivo tiene que ser .csv.')
        if f.size > 2 * 1024 * 1024:
            raise forms.ValidationError('El archivo es demasiado grande (máximo 2 MB).')
        return f


class SellForm(forms.Form):
    codes = forms.CharField(
        label='Códigos de los boletos',
        widget=forms.Textarea(attrs={'rows': 3, 'autofocus': 'autofocus', 'autocomplete': 'off',
                                     'placeholder': 'Escaneá el boleto (o escribí el código). Uno por línea.'}),
        help_text='Con el lector se escanean uno tras otro: cada boleto queda en su renglón.',
    )
    method = forms.ChoiceField(label='Medio de pago', initial='efectivo', widget=forms.RadioSelect,
                               choices=PAYMENT_METHODS)


class PickForm(forms.Form):
    """
    Qué entregar: butacas elegidas en el plano (``seats``, guids separados por coma) o, en un
    evento sin numerar, un producto y una cantidad. ``numbered`` lo decide la vista.
    """
    seats = forms.CharField(required=False, widget=forms.HiddenInput)
    item = forms.ModelChoiceField(label='Producto', queryset=None, required=False)
    quantity = forms.IntegerField(label='Cantidad', min_value=1, max_value=500, initial=1, required=False)

    def __init__(self, *args, numbered=True, items=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.numbered = numbered
        self.fields['item'].queryset = items
        if numbered:
            del self.fields['item']
            del self.fields['quantity']

    def clean(self):
        d = super().clean()
        if self.numbered:
            d['guids'] = [g for g in (d.get('seats') or '').split(',') if g]
            if not d['guids']:
                raise forms.ValidationError('Elegí al menos una butaca en el plano.')
        else:
            if not d.get('item'):
                self.add_error('item', 'Elegí un producto.')
            if not d.get('quantity'):
                self.add_error('quantity', 'Indicá cuántas.')
        return d


class GenerateForm(PickForm):
    kind = forms.ChoiceField(
        label='Tipo de boletos',
        choices=TicketsUploadForm.base_fields['kind'].choices,
        initial='cortesia',
        widget=forms.RadioSelect,
    )
    field_order = ['kind', 'item', 'quantity', 'seats']


class CourtesyForm(PickForm):
    name = forms.CharField(label='Nombre del invitado', max_length=200,
                           widget=forms.TextInput(attrs={'placeholder': 'Laura Gómez'}))
    email = forms.EmailField(label='Email', required=False,
                             help_text='Ahí le llegan las entradas con el código QR. Vacío = queda en la lista '
                                       'de invitados (en la puerta se lo busca por nombre).')
    field_order = ['name', 'email', 'item', 'quantity', 'seats']


class SectorUploadForm(forms.Form):
    name = forms.CharField(
        label='Nombre del sector', max_length=190,
        widget=forms.TextInput(attrs={'placeholder': 'Platea, VIP, 1er piso…'}),
        help_text='Si ya existe un sector con este nombre, se reemplaza.',
    )
    file = forms.FileField(
        label='Archivo (.json o .csv)',
        help_text='CSV: columnas "fila" y "butaca" (opcionales: "seat_guid", "categoria"). '
                  'Separado por coma o punto y coma.',
    )

    def clean_file(self):
        f = self.cleaned_data['file']
        if not f.name.lower().endswith(('.json', '.csv')):
            raise forms.ValidationError('El archivo tiene que ser .json o .csv.')
        if f.size > 2 * 1024 * 1024:
            raise forms.ValidationError('El archivo es demasiado grande (máximo 2 MB).')
        return f
