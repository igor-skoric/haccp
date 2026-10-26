MODULES = {
    'kafic': [
        ('Prijem namirnica', 'Šta je ušlo u objekat i od koga.'),
        ('Temperature frižidera', 'Dnevno praćenje rashladnih uređaja.'),
        ('Higijena prostora', 'Čišćenje šanka, kuhinje i toaleta.'),
        ('Kontrola štetočina', 'Plan i evidencija DDD mera.'),
    ],
    'poslasticarnica': [
        ('Prijem sirovina', 'Brašno, kremovi, jaja i mlečni proizvodi.'),
        ('Hlađenje vitrina', 'Temperature izložbenih vitrina.'),
        ('Alergeni', 'Označavanje alergena na deklaracijama.'),
        ('Pečenje', 'Režim pečenja kolača i peciva.'),
    ],
    'proizvodnja': [
        ('Radni nalog', 'Serije sirovina ugrađene u gotov proizvod.'),
        ('CCP temperature', 'Hlađenje i pečenje kao kritične tačke.'),
        ('Sledljivost', 'Put proizvoda od prijema do kupca.'),
        ('Kontrola sita', 'Ispravnost sita pri prosejavanju brašna.'),
    ],
}

DEFAULT_MODULES = [
    ('Prijem', 'Ulaz sirovina i ambalaže.'),
    ('Higijena', 'Čišćenje prostora i opreme.'),
    ('Zapisi', 'Dnevne evidencije za ovu delatnost.'),
]
