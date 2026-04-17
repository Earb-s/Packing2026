from django import forms


class PackingInputForm(forms.Form):
    MATERIAL_CHOICES = [
        ("rock", "Rock (SG 2.70, β 0.60)"),
        ("limestone", "Limestone (SG 2.70, β 0.60)"),
        ("sand", "Sand (SG 2.65, β 0.63)"),
        ("cement", "Cement (SG 3.15, β 0.56)"),
        ("pfa", "PFA (SG 2.30, β 0.52)"),
        ("silica_fume", "Silica fume (SG 2.20, β 0.42)"),
        ("clay", "Clay (SG 2.60, β 0.35)"),
        ("custom", "Custom (manual rho and beta)"),
    ]

    psd1 = forms.FileField(required=False, label="PSD File 1")
    psd2 = forms.FileField(required=False, label="PSD File 2")
    psd3 = forms.FileField(required=False, label="PSD File 3")
    psd4 = forms.FileField(required=False, label="PSD File 4")

    material_name1 = forms.CharField(required=False, max_length=60, label="Display Name for PSD1")
    material_name2 = forms.CharField(required=False, max_length=60, label="Display Name for PSD2")
    material_name3 = forms.CharField(required=False, max_length=60, label="Display Name for PSD3")
    material_name4 = forms.CharField(required=False, max_length=60, label="Display Name for PSD4")

    material1 = forms.ChoiceField(choices=MATERIAL_CHOICES, initial="sand", label="Material for PSD1")
    material2 = forms.ChoiceField(choices=MATERIAL_CHOICES, initial="rock", label="Material for PSD2")
    material3 = forms.ChoiceField(choices=MATERIAL_CHOICES, initial="cement", label="Material for PSD3")
    material4 = forms.ChoiceField(choices=MATERIAL_CHOICES, initial="pfa", label="Material for PSD4")

    m1 = forms.FloatField(initial=0.25, min_value=0.0, label="Mass Fraction M1")
    m2 = forms.FloatField(initial=0.25, min_value=0.0, label="Mass Fraction M2")
    m3 = forms.FloatField(initial=0.25, min_value=0.0, label="Mass Fraction M3")
    m4 = forms.FloatField(initial=0.25, min_value=0.0, label="Mass Fraction M4")

    rho1 = forms.FloatField(initial=2.65, min_value=0.0001, label="Density rho1")
    rho2 = forms.FloatField(initial=2.70, min_value=0.0001, label="Density rho2")
    rho3 = forms.FloatField(initial=2.60, min_value=0.0001, label="Density rho3")
    rho4 = forms.FloatField(initial=2.72, min_value=0.0001, label="Density rho4")

    beta1 = forms.FloatField(initial=0.65, min_value=0.0001, max_value=0.9999, label="Beta1")
    beta2 = forms.FloatField(initial=0.72, min_value=0.0001, max_value=0.9999, label="Beta2")
    beta3 = forms.FloatField(initial=0.48, min_value=0.0001, max_value=0.9999, label="Beta3")
    beta4 = forms.FloatField(initial=0.48, min_value=0.0001, max_value=0.9999, label="Beta4")

    def clean(self):
        cleaned = super().clean()
        masses = [cleaned.get("m1"), cleaned.get("m2"), cleaned.get("m3"), cleaned.get("m4")]

        if any(m is None for m in masses):
            return cleaned

        total_mass = sum(masses)
        if total_mass <= 0:
            raise forms.ValidationError("At least one mass fraction must be greater than zero.")

        return cleaned
