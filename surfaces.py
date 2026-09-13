"""Surface for each tournament, since the Sportradar feed does not carry one.

Checked and absent from `competitions`, `competitions/{id}/info`, `venue`, and
`sport_event_context` -- so it has to be supplied. Keys are matched as
case-insensitive substrings of the competition name, most specific first.

Four surfaces, as tennis actually plays them:
    hard          outdoor hard court
    clay          red clay (and Charleston's green clay, which plays similarly)
    grass         the short June-July swing
    indoor_hard   hard court under a roof: faster, no wind, no sun
"""

HARD, CLAY, GRASS, INDOOR = 'hard', 'clay', 'grass', 'indoor_hard'

# (substring, surface) -- first match wins, so put the specific ones first
# ---------------------------------------------------------------------------
# Surfaces exactly as published on the 2026 tour calendars, keyed by (tour,
# calendar name) so the lookup is exact. A substring rule cannot do this job:
# Stuttgart hosts a grass ATP event and an indoor-clay WTA one, and Paris hosts
# Roland Garros and an indoor Masters.
#
#   ATP  atptour.com/-/media/files/calendar-pdfs/2025/2026-atp-tour-calendar-december-2025.pdf
#   WTA  wtafiles.wtatennis.com/pdf/calendar/calendar.pdf
#
# Indoor clay is recorded as clay: the model has no separate indoor-clay bases
# and the ball behaves as it does on clay. Indoor hard is kept distinct because
# it has its own bases.
#
# The ATP PDF's text layer interleaves its columns, so it was read by eye and
# each entry checked against the raw text rather than scraped -- an automated
# pass on it claimed Acapulco was clay and Buenos Aires hard, both wrong.
PUBLISHED = {
    # --- ATP -------------------------------------------------------------
    ('ATP', 'Brisbane'): HARD,        ('ATP', 'Hong Kong'): HARD,
    ('ATP', 'Auckland'): HARD,        ('ATP', 'Adelaide'): HARD,
    ('ATP', 'Australian Open'): HARD, ('ATP', 'Montpellier'): INDOOR,
    ('ATP', 'Rotterdam'): INDOOR,     ('ATP', 'Dallas'): INDOOR,
    ('ATP', 'Doha'): HARD,            ('ATP', 'Buenos Aires'): CLAY,
    ('ATP', 'Rio de Janeiro'): CLAY,  ('ATP', 'Santiago'): CLAY,
    ('ATP', 'Acapulco'): HARD,        ('ATP', 'Dubai'): HARD,
    ('ATP', 'Delray Beach'): HARD,    ('ATP', 'Indian Wells'): HARD,
    ('ATP', 'Miami'): HARD,           ('ATP', 'Houston'): CLAY,
    ('ATP', 'Bucharest'): CLAY,       ('ATP', 'Marrakech'): CLAY,
    ('ATP', 'Monte Carlo'): CLAY,     ('ATP', 'Barcelona'): CLAY,
    ('ATP', 'Munich'): CLAY,          ('ATP', 'Madrid'): CLAY,
    ('ATP', 'Rome'): CLAY,            ('ATP', 'Geneva'): CLAY,
    ('ATP', 'Hamburg'): CLAY,         ('ATP', 'Roland Garros'): CLAY,
    ('ATP', 'Stuttgart'): GRASS,      ('ATP', 'S-Hertogenbosch'): GRASS,
    ('ATP', "Queen's Club"): GRASS,   ('ATP', 'Halle'): GRASS,
    ('ATP', 'Eastbourne'): GRASS,     ('ATP', 'Mallorca'): GRASS,
    ('ATP', 'Wimbledon'): GRASS,      ('ATP', 'Bastad'): CLAY,
    ('ATP', 'Gstaad'): CLAY,          ('ATP', 'Umag'): CLAY,
    ('ATP', 'Estoril'): CLAY,         ('ATP', 'Kitzbuhel'): CLAY,
    ('ATP', 'Washington'): HARD,      ('ATP', 'Los Cabos'): HARD,
    ('ATP', 'Winston Salem'): HARD,   ('ATP', 'Montreal'): HARD,
    ('ATP', 'Cincinnati'): HARD,      ('ATP', 'US Open'): HARD,
    ('ATP', 'Chengdu'): HARD,         ('ATP', 'Hangzhou'): HARD,
    ('ATP', 'Tokyo'): HARD,           ('ATP', 'Beijing'): HARD,
    ('ATP', 'Shanghai'): HARD,        ('ATP', 'Brussels'): INDOOR,
    ('ATP', 'Basel'): INDOOR,         ('ATP', 'Almaty'): INDOOR,
    ('ATP', 'Vienna'): INDOOR,        ('ATP', 'Paris'): INDOOR,
    ('ATP', 'Metz'): INDOOR,          ('ATP', 'Stockholm'): INDOOR,
    # The Hellenic Championship, an indoor hard ATP 250 first played in November
    # 2025, taking the Belgrade Open's place. It is absent from the December 2025
    # calendar PDF -- week 45 there is still TBD -- so the surface comes from the
    # tournament rather than that document. Belgrade never enters the cached
    # window, so unlike Cleveland and Memphis there is no slot played twice.
    ('ATP', 'Athens'): INDOOR,
    ('ATP', 'World Tour Finals'): INDOOR,
    ('ATP', 'Next Gen ATP Finals'): INDOOR,

    # --- WTA -------------------------------------------------------------
    ('WTA', 'Auckland'): HARD,        ('WTA', 'Brisbane'): HARD,
    ('WTA', 'Adelaide 1'): HARD,      ('WTA', 'Hobart'): HARD,
    ('WTA', 'Australian Open'): HARD, ('WTA', 'Abu Dhabi'): HARD,
    ('WTA', 'Cluj Napoca'): INDOOR,   ('WTA', 'Ostrava'): INDOOR,
    ('WTA', 'Doha'): HARD,            ('WTA', 'Dubai'): HARD,
    ('WTA', 'Merida'): HARD,          ('WTA', 'Austin'): HARD,
    ('WTA', 'Indian Wells'): HARD,    ('WTA', 'Miami'): HARD,
    ('WTA', 'Charleston'): CLAY,      ('WTA', 'Bogota'): CLAY,
    ('WTA', 'Linz'): CLAY,            ('WTA', 'Stuttgart'): CLAY,
    ('WTA', 'Rouen'): CLAY,           ('WTA', 'Madrid'): CLAY,
    ('WTA', 'Rome'): CLAY,            ('WTA', 'Strasbourg'): CLAY,
    ('WTA', 'Rabat'): CLAY,           ('WTA', 'Roland Garros'): CLAY,
    ('WTA', "Queen's Club"): GRASS,   ('WTA', 'S-Hertogenbosch'): GRASS,
    ('WTA', 'Berlin'): GRASS,         ('WTA', 'Nottingham'): GRASS,
    ('WTA', 'Bad Homburg'): GRASS,    ('WTA', 'Eastbourne'): GRASS,
    ('WTA', 'Wimbledon'): GRASS,      ('WTA', 'Iasi'): CLAY,
    ('WTA', 'Athens'): HARD,          ('WTA', 'Hamburg'): CLAY,
    ('WTA', 'Prague'): HARD,          ('WTA', 'Washington'): HARD,
    ('WTA', 'Memphis'): HARD,         ('WTA', 'Toronto'): HARD,
    ('WTA', 'Cincinnati'): HARD,      ('WTA', 'Monterrey'): HARD,
    ('WTA', 'US Open'): HARD,         ('WTA', 'Guadalajara'): HARD,
    ('WTA', 'Sao Paulo'): HARD,       ('WTA', 'Seoul'): HARD,
    ('WTA', 'Beijing'): HARD,         ('WTA', 'Wuhan'): HARD,
    ('WTA', 'Ningbo'): HARD,          ('WTA', 'Osaka'): HARD,
    ('WTA', 'Tokyo'): HARD,           ('WTA', 'Guangzhou'): HARD,
    ('WTA', 'Chennai'): HARD,         ('WTA', 'Hong Kong'): HARD,
    ('WTA', 'Jiujiang'): HARD,        ('WTA', 'Finals'): HARD,
}

def published_surface(tour, name):
    """Surface as the tour states it, or None if the event is not in the table."""
    if (tour, name) in PUBLISHED:
        return PUBLISHED[(tour, name)], 'published calendar'
    return None, None


SURFACE_RULES = [
    # --- grand slams ---
    ('french open', CLAY), ('wimbledon', GRASS),
    ('australian open', HARD), ('us open', HARD),

    # --- clay swing ---
    ('monte carlo', CLAY), ('madrid', CLAY), ('rome', CLAY), ('hamburg', CLAY),
    ('barcelona', CLAY), ('munich', CLAY), ('rio de janeiro', CLAY),
    ('strasbourg', CLAY), ('charleston', CLAY),
    # Stuttgart hosts two events on DIFFERENT surfaces: the WTA Porsche Grand
    # Prix (April, indoor clay) and the ATP BOSS Open (June, grass, since 2015).
    # The feed names carry the tour, so key on that -- a bare 'stuttgart' rule
    # silently gave the ATP grass event clay parameters.
    ('wta stuttgart', CLAY), ('atp stuttgart', GRASS),
    ('geneva', CLAY), ('houston', CLAY),   # Gonet Open; US Men's Clay Courts
    # From the published 2026 calendars. Indoor clay is mapped to clay: the
    # model has no separate indoor-clay bases, and the ball behaves as on clay.
    ('bogota', CLAY),                      # Colsanitas Cup
    ('rouen', CLAY), ('linz', CLAY),       # both indoor clay on the WTA calendar
    ('bastad', CLAY), ('gstaad', CLAY), ('kitzbuhel', CLAY), ('umag', CLAY),
    ('buenos aires', CLAY), ('santiago', CLAY), ('cordoba', CLAY),
    ('estoril', CLAY), ('marrakech', CLAY), ('bucharest', CLAY),
    ('rabat', CLAY), ('iasi', CLAY), ('palermo', CLAY), ('parma', CLAY),

    # --- grass swing ---
    ('halle', GRASS), ('bad homburg', GRASS), ('berlin', GRASS),
    ('eastbourne', GRASS), ('mallorca', GRASS),
    ('newport', GRASS), ('nottingham', GRASS), ('birmingham', GRASS),
    ('s-hertogenbosch', GRASS),   # also matches the "'s-Hertogenbosch" spelling
    ('london, great britain', GRASS),   # Queen's / Eastbourne

    # --- indoor hard ---
    ('paris, france', INDOOR), ('world tour finals', INDOOR),
    ('next generation', INDOOR), ('championships women', INDOOR),
    ('rotterdam', INDOOR), ('dallas', INDOOR), ('marseille', INDOOR),
    ('montpellier', INDOOR), ('vienna', INDOOR), ('basel', INDOOR),
    ('metz', INDOOR), ('stockholm', INDOOR), ('antwerp', INDOOR),
    ('sofia', INDOOR), ('cluj', INDOOR),
    ('almaty', INDOOR), ('brussels', INDOOR), ('ostrava', INDOOR),
    ('moscow', INDOOR), ('st. petersburg', INDOOR), ('nur-sultan', INDOOR),
]


def surface_of(competition: str, default: str = HARD):
    """Surface for a competition name.

    The rules above list the exceptions -- clay, grass, indoor -- because the
    tour is majority outdoor hard and enumerating every hard-court event would
    be a longer list that goes stale faster. Anything unmatched falls through to
    `default`, so a new hard-court stop needs no rule and a new clay one is the
    only kind that needs adding.
    """
    if not competition:
        return None
    lowered = str(competition).lower()
    for needle, surface in SURFACE_RULES:
        if needle in lowered:
            return surface
    return default


def add_surface(df, column='competition', default=HARD):
    """Attach a `surface` column, overwriting the feed's empty one."""
    df = df.copy()
    df['surface'] = df[column].map(lambda name: surface_of(name, default))
    return df


def explicit_only(df, column='competition'):
    """Surfaces from the rules alone -- unmatched events stay None. Use this to
    see what the default is silently absorbing."""
    return add_surface(df, column, default=None)
