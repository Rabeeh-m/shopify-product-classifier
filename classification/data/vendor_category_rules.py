"""Vendor import category → Shopify taxonomy rules for Product List.xlsx-style sheets.

Each rule key is a normalized vendor sub-category (lowercase). Values are either:
  - a string category name for a direct mapping, or
  - a dict with optional ``title_rules`` for disambiguation within a
    sub-category and an optional ``default`` used when no title rule matches.

Title rules are lists of (keyword tuple, category name); the first rule whose
keywords all/any appear in the product search text wins. Category names are
resolved against the loaded taxonomy at runtime. Rules whose target category is
not present in the DB are skipped (AI fallback).
"""

# Title rules: list of (keyword tuple, category name). First match wins.
_SOFA_ARMCHAIR_RULES = (
    (("armchair", "accent chair"), "Armchairs"),
    (("loveseat", "love seat"), "Loveseats"),
    (("chesterfield",), "Chesterfield Sofas"),
    (("sleeper", "sofa bed"), "Sleeper Sofas"),
    (("sectional",), "Sectional Sofas"),
    (("modular",), "Modular Sofas"),
    (("settee",), "Settees"),
    (("sofa", "couch"), "Sofas"),
)

_TABLE_RULES = (
    (("coffee table", "coffee"), "Coffee Tables"),
    (("dining table",), "Dining Tables"),
    (("bar table", "pub table"), "Dining Tables"),
    (("side table", "end table"), "Side Tables"),
    (("nesting",), "Side Tables"),
    (("console table", "console"), "Console Tables"),
    (("desk",), "Desk Tables"),
)

# 'Bar and Dining' mixes stools, chairs, benches, and tables — most specific
# furniture type first, tables last.
_BAR_DINING_RULES = (
    (("bar stool", "counter stool"), "Bar Stools"),
    (("stool",), "Bar Stools"),
    (("dining chair",), "Dining Chairs"),
    (("armchair",), "Armchairs"),
    (("bench",), "Benches"),
) + _TABLE_RULES

_DECOR_RULES = (
    (("trash", "waste bin", "waste basket"), "Waste Baskets"),
    (
        ("tv stand", "tv console", "media console", "entertainment center"),
        "TV Stands",
    ),
    (("coat rack", "coat hook", "hall tree"), "Coat Racks"),
    (("bookcase", "bookshelf"), "Bookcases"),
    (("wall shelf", "floating shelf", "shelf", "shelving"), "Shelving Units"),
    (("dresser",), "Dressers"),
    (("wardrobe", "armoire"), "Wardrobes"),
    (("cabinet",), "Cabinets"),
)

_CASE_GOODS_RULES = (
    (("nightstand", "night stand"), "Nightstands"),
    (("end table",), "Side Tables"),
    (("mirror",), "Mirrors"),
    (("sideboard", "buffet"), "Sideboards"),
)

# Vendor 'Daybeds and Lounges' data is dominated by outdoor patio swing chairs;
# actual daybeds/chaises are the minority.
_DAYBED_LOUNGE_RULES = (
    (("swing", "hanging chair"), "Patio Swing Chairs"),
    (("chaise",), "Daybeds"),
)

_KITCHEN_CART_RULES = (
    (
        (
            "kitchen cart",
            "kitchen island",
            "serving cart",
            "serving stand",
            "bar cart",
            "cart",
        ),
        "Kitchen Islands & Carts",
    ),
)

VENDOR_SUBCATEGORY_RULES = {
    # Direct mappings — the vendor sub-category always means one Shopify leaf.
    "sofa sectionals": "Sectional Sofas",
    "vanities": "Vanities",
    "dining chairs": "Dining Chairs",
    "bar and dining tables": "Dining Tables",
    "bar and counter stools": "Bar Stools",
    "ceiling lamps": "Ceiling Lights",
    "table lamps": "Table Lamps",
    "floor lamps": "Floor Lamps",
    "office chairs": "Office Chairs",
    "benches and stools": "Benches",
    "computer desks": "Desk Tables",
    "pillow": "Throw Pillows",
    # Sub-categories that need title-keyword disambiguation.
    "sofas and armchairs": {"title_rules": _SOFA_ARMCHAIR_RULES},
    "tables": {"title_rules": _TABLE_RULES},
    "bar and dining": {"title_rules": _BAR_DINING_RULES},
    "decor": {"title_rules": _DECOR_RULES},
    "case goods": {"title_rules": _CASE_GOODS_RULES},
    "daybeds and lounges": {
        "title_rules": _DAYBED_LOUNGE_RULES,
        "default": "Daybeds",
    },
    "dining sets": {
        "title_rules": _KITCHEN_CART_RULES,
        "default": "Dining Sets",
    },
    # Category-level fallbacks for rows with no sub-category.
    "bedroom": {
        "title_rules": _CASE_GOODS_RULES
        + ((("bed frame", "platform bed", "bunk bed"), "Beds & Bed Frames"),),
    },
}
