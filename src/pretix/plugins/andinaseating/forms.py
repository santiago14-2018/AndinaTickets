#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django import forms


class SalaForm(forms.Form):
    name = forms.CharField(label='Nombre de la sala', max_length=190,
                           widget=forms.TextInput(attrs={'placeholder': 'Teatro Principal'}))


class GeneratorForm(forms.Form):
    name = forms.CharField(label='Nombre del sector', max_length=190, initial='Platea',
                           help_text='Si ya existe un sector con este nombre, se reemplaza.')
    category = forms.CharField(label='Categoría', max_length=190, required=False,
                               help_text='Vacío = igual al nombre del sector. La categoría se conecta con un producto.')
    rows = forms.IntegerField(label='Filas', min_value=1, max_value=100, initial=10)
    seats_per_row = forms.IntegerField(label='Butacas por fila', min_value=1, max_value=200, initial=10)
    first_row = forms.CharField(label='Primera fila', max_length=3, initial='A',
                                help_text='Una letra (A, B…) o un número (1, 2…).')
    first_number = forms.IntegerField(label='Primera butaca', min_value=0, max_value=9999, initial=1)
    right_to_left = forms.BooleanField(label='Numerar de derecha a izquierda', required=False)
    aisle_after = forms.IntegerField(label='Pasillo después de la butaca', min_value=0, max_value=199, initial=0,
                                     help_text='Contando desde la izquierda. 0 = sin pasillo.')
    stagger = forms.BooleanField(label='Filas alternadas (corridas media butaca)', required=False)
    curve = forms.IntegerField(label='Curva', min_value=0, max_value=300, initial=0,
                               help_text='0 = filas rectas. Más alto = las puntas más cerca del escenario.')
    seat_spacing = forms.IntegerField(label='Separación entre butacas', min_value=20, max_value=100, initial=35)
    row_spacing = forms.IntegerField(label='Separación entre filas', min_value=20, max_value=150, initial=40)

    def clean(self):
        d = super().clean()
        if d.get('aisle_after') and d.get('seats_per_row') and d['aisle_after'] >= d['seats_per_row']:
            self.add_error('aisle_after', 'El pasillo tiene que quedar entre dos butacas de la fila.')
        return d


class TicketsUploadForm(forms.Form):
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
