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
SURFACE_RULES = [
    # --- grand slams ---
    ('french open', CLAY), ('wimbledon', GRASS),
    ('australian open', HARD), ('us open', HARD),

    # --- clay swing ---
    ('monte carlo', CLAY), ('madrid', CLAY), ('rome', CLAY), ('hamburg', CLAY),
    ('barcelona', CLAY), ('munich', CLAY), ('rio de janeiro', CLAY),
    ('strasbourg', CLAY), ('charleston', CLAY), ('stuttgart', CLAY),  # indoor clay
    ('bastad', CLAY), ('gstaad', CLAY), ('kitzbuhel', CLAY), ('umag', CLAY),
    ('buenos aires', CLAY), ('santiago', CLAY), ('cordoba', CLAY),
    ('estoril', CLAY), ('marrakech', CLAY), ('bucharest', CLAY),
    ('rabat', CLAY), ('iasi', CLAY), ('palermo', CLAY), ('parma', CLAY),

    # --- grass swing ---
    ('halle', GRASS), ('bad homburg', GRASS), ('berlin', GRASS),
    ('eastbourne', GRASS), ('mallorca', GRASS), ('stuttgart open', GRASS),
    ('newport', GRASS), ('nottingham', GRASS), ('birmingham', GRASS),
    ('s-hertogenbosch', GRASS), ("'s-hertogenbosch", GRASS),
    ('london, great britain', GRASS),   # Queen's / Eastbourne

    # --- indoor hard ---
    ('paris, france', INDOOR), ('world tour finals', INDOOR),
    ('next generation', INDOOR), ('championships women', INDOOR),
    ('rotterdam', INDOOR), ('dallas', INDOOR), ('marseille', INDOOR),
    ('montpellier', INDOOR), ('vienna', INDOOR), ('basel', INDOOR),
    ('metz', INDOOR), ('stockholm', INDOOR), ('antwerp', INDOOR),
    ('sofia', INDOOR), ('linz', INDOOR), ('cluj', INDOOR),
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
