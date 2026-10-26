KINDS = (
    {
        'code': 'HP',
        'label': 'HACCP plan',
        'menu': 'Plan',
        'url_name': 'plan',
        'blurb': 'Opis, dijagram, analiza opasnosti i sam plan. Ovo se pravi za objekat.',
    },
    {
        'code': 'PR',
        'label': 'Procedure',
        'menu': 'Procedure',
        'url_name': 'procedures',
        'blurb': 'Kako se vodi provera, štetočine, neusaglašenost i korektivne mere.',
    },
    {
        'code': 'UP',
        'label': 'Uputstva',
        'menu': 'Uputstva',
        'url_name': 'instructions',
        'blurb': 'Prijem, higijena, čišćenje, sledljivost, opoziv, merila i dokumenta.',
    },
    {
        'code': 'OB',
        'label': 'Obrasci',
        'menu': 'Obrasci',
        'url_name': 'forms',
        'blurb': 'Prazni obrasci za zapise. Popunjeni podaci kasnije ostaju na objektu.',
    },
    {
        'code': 'IN',
        'label': 'Inspekcija',
        'menu': 'Inspekcija',
        'url_name': 'inspection',
        'blurb': 'Kaznene mere iz tipičnih nalaza i kontrolne liste za pripremu pred proveru.',
    },
)

KIND_BY_CODE = {item['code']: item for item in KINDS}
