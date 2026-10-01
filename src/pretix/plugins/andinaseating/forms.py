#
# This file is part of AndinaTickets, a fork of pretix (Community Edition),
# licensed under the GNU Affero General Public License v3. See the LICENSE file.
#
from django import forms


class SalaForm(forms.Form):
    name = forms.CharField(label='Nombre de la sala', max_length=190,
                           widget=forms.TextInput(attrs={'placeholder': 'Teatro Principal'}))


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
