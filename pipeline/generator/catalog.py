"""Reference / master data for the synthetic e-commerce source system.

The catalogue is intentionally realistic (long-tail popularity, category price
bands, regional payment preferences) so downstream analytics produce
believable numbers instead of uniform noise.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Geography
# --------------------------------------------------------------------------- #
REGIONS: dict[str, dict] = {
    "North America": {
        "weight": 0.34,
        "countries": {"United States": 0.82, "Canada": 0.18},
        "currency": "USD",
    },
    "Europe": {
        "weight": 0.26,
        "countries": {"United Kingdom": 0.31, "Germany": 0.27, "France": 0.21, "Spain": 0.11, "Netherlands": 0.10},
        "currency": "EUR",
    },
    "Asia Pacific": {
        "weight": 0.24,
        "countries": {"India": 0.38, "Australia": 0.22, "Japan": 0.21, "Singapore": 0.19},
        "currency": "USD",
    },
    "Latin America": {
        "weight": 0.09,
        "countries": {"Brazil": 0.58, "Mexico": 0.42},
        "currency": "USD",
    },
    "Middle East & Africa": {
        "weight": 0.07,
        "countries": {"United Arab Emirates": 0.46, "South Africa": 0.32, "Saudi Arabia": 0.22},
        "currency": "USD",
    },
}

CITIES: dict[str, list[str]] = {
    "United States": ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Seattle", "Austin", "Boston"],
    "Canada": ["Toronto", "Vancouver", "Montreal", "Calgary"],
    "United Kingdom": ["London", "Manchester", "Birmingham", "Leeds", "Glasgow"],
    "Germany": ["Berlin", "Munich", "Hamburg", "Cologne", "Frankfurt"],
    "France": ["Paris", "Lyon", "Marseille", "Toulouse"],
    "Spain": ["Madrid", "Barcelona", "Valencia", "Seville"],
    "Netherlands": ["Amsterdam", "Rotterdam", "Utrecht"],
    "India": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Chennai", "Pune"],
    "Australia": ["Sydney", "Melbourne", "Brisbane", "Perth"],
    "Japan": ["Tokyo", "Osaka", "Nagoya", "Fukuoka"],
    "Singapore": ["Singapore"],
    "Brazil": ["Sao Paulo", "Rio de Janeiro", "Belo Horizonte", "Curitiba"],
    "Mexico": ["Mexico City", "Guadalajara", "Monterrey"],
    "United Arab Emirates": ["Dubai", "Abu Dhabi", "Sharjah"],
    "South Africa": ["Johannesburg", "Cape Town", "Durban"],
    "Saudi Arabia": ["Riyadh", "Jeddah", "Dammam"],
}

# --------------------------------------------------------------------------- #
# Product catalogue
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Category:
    name: str
    subcategories: tuple[str, ...]
    price_band: tuple[float, float]
    margin_band: tuple[float, float]
    weight: float
    return_rate: float


CATEGORIES: tuple[Category, ...] = (
    Category("Electronics", ("Headphones", "Smartphones", "Laptops", "Cameras", "Wearables", "Accessories"),
             (39.0, 1499.0), (0.12, 0.34), 0.20, 0.085),
    Category("Home & Kitchen", ("Cookware", "Small Appliances", "Furniture", "Bedding", "Storage"),
             (12.0, 899.0), (0.22, 0.48), 0.15, 0.062),
    Category("Fashion", ("Men's Apparel", "Women's Apparel", "Footwear", "Bags", "Jewellery"),
             (9.0, 349.0), (0.35, 0.65), 0.19, 0.145),
    Category("Beauty", ("Skincare", "Haircare", "Fragrance", "Makeup"),
             (7.0, 189.0), (0.40, 0.68), 0.12, 0.048),
    Category("Sports & Outdoors", ("Fitness", "Cycling", "Camping", "Team Sports"),
             (15.0, 799.0), (0.24, 0.45), 0.11, 0.071),
    Category("Books", ("Fiction", "Non-Fiction", "Technical", "Children"),
             (5.0, 79.0), (0.28, 0.42), 0.08, 0.031),
    Category("Toys & Games", ("Board Games", "Building Sets", "Outdoor Play", "Puzzles"),
             (8.0, 259.0), (0.30, 0.52), 0.08, 0.055),
    Category("Grocery", ("Beverages", "Snacks", "Pantry", "Organic"),
             (3.0, 89.0), (0.18, 0.36), 0.07, 0.024),
)

BRANDS: tuple[str, ...] = (
    "Nova", "Vertex", "Lumina", "Orbis", "Kestrel", "Aster", "Nordwind", "Zephyr",
    "Cobalt", "Meridian", "Solace", "Quanta", "Harbor", "Pinnacle", "Terra", "Onyx",
)

PAYMENT_METHODS: tuple[tuple[str, float], ...] = (
    ("credit_card", 0.41),
    ("paypal", 0.14),
    ("upi", 0.13),
    ("debit_card", 0.16),
    ("wallet", 0.09),
    ("cash_on_delivery", 0.07),
)

# Payment success rates differ by method - COD fails more, wallets are smooth.
PAYMENT_SUCCESS_RATE: dict[str, float] = {
    "credit_card": 0.938,
    "debit_card": 0.951,
    "paypal": 0.972,
    "upi": 0.964,
    "wallet": 0.981,
    "cash_on_delivery": 0.874,
}

FAILURE_REASONS: tuple[tuple[str, float], ...] = (
    ("insufficient_funds", 0.34),
    ("card_declined", 0.23),
    ("gateway_timeout", 0.17),
    ("authentication_failed", 0.13),
    ("risk_blocked", 0.08),
    ("currency_not_supported", 0.05),
)

CARRIERS: tuple[tuple[str, float], ...] = (
    ("BlueDart Express", 0.28),
    ("FedEx", 0.24),
    ("DHL", 0.19),
    ("UPS", 0.16),
    ("Local Courier", 0.13),
)

ACQUISITION_CHANNELS: tuple[tuple[str, float], ...] = (
    ("organic_search", 0.29),
    ("paid_search", 0.22),
    ("social_media", 0.19),
    ("email", 0.12),
    ("affiliate", 0.10),
    ("direct", 0.08),
)

ORDER_CHANNELS: tuple[tuple[str, float], ...] = (
    ("web", 0.46),
    ("mobile_app", 0.41),
    ("marketplace", 0.13),
)

RETURN_REASONS: tuple[tuple[str, float], ...] = (
    ("damaged_on_arrival", 0.24),
    ("wrong_item_shipped", 0.18),
    ("not_as_described", 0.21),
    ("size_or_fit_issue", 0.19),
    ("changed_mind", 0.12),
    ("late_delivery", 0.06),
)

ORDER_STATUSES: tuple[tuple[str, float], ...] = (
    ("completed", 0.815),
    ("pending", 0.041),
    ("processing", 0.033),
    ("cancelled", 0.072),
    ("returned", 0.039),
)


def weighted_choice(rng: random.Random, options: list[tuple[str, float]]) -> str:
    """Pick from [(value, weight), ...] without needing numpy."""
    total = sum(w for _, w in options)
    r = rng.random() * total
    upto = 0.0
    for value, weight in options:
        upto += weight
        if r <= upto:
            return value
    return options[-1][0]


def region_weights() -> list[tuple[str, float]]:
    return [(r, cfg["weight"]) for r, cfg in REGIONS.items()]


def country_for_region(rng: random.Random, region: str) -> str:
    countries = REGIONS[region]["countries"]
    return weighted_choice(rng, list(countries.items()))


def city_for_country(rng: random.Random, country: str) -> str:
    return rng.choice(CITIES[country])


@dataclass
class Product:
    product_id: str
    sku: str
    product_name: str
    category: str
    subcategory: str
    brand: str
    unit_price: float
    unit_cost: float
    weight_kg: float
    is_active: bool
    launched_at: str
    popularity: float = field(default=1.0)


def build_products(rng: random.Random, count: int = 900) -> list[Product]:
    products: list[Product] = []
    cat_weights = [(c.name, c.weight) for c in CATEGORIES]
    by_name = {c.name: c for c in CATEGORIES}

    adjectives = ("Pro", "Max", "Lite", "Ultra", "Classic", "Air", "Prime", "Mini", "Plus", "Studio")
    nouns = ("Series", "Edition", "Collection", "Model", "Line", "Kit", "Pack", "Set")

    for i in range(count):
        cat_name = weighted_choice(rng, cat_weights)
        cat = by_name[cat_name]
        sub = rng.choice(list(cat.subcategories))
        brand = rng.choice(BRANDS)
        low, high = cat.price_band
        # log-uniform price inside the band => lots of cheap items, few expensive
        import math
        price = round(math.exp(rng.uniform(math.log(low), math.log(high))), 2)
        m_low, m_high = cat.margin_band
        cost = round(price * (1 - rng.uniform(m_low, m_high)), 2)
        # Long-tail popularity: a handful of hero SKUs drive most volume.
        popularity = round(rng.paretovariate(1.35), 3)
        products.append(
            Product(
                product_id=f"P{i + 1:05d}",
                sku=f"{brand[:3].upper()}-{cat_name[:3].upper()}-{i + 1:05d}",
                product_name=f"{brand} {sub} {rng.choice(adjectives)} {rng.choice(nouns)} {rng.randint(1, 9)}",
                category=cat_name,
                subcategory=sub,
                brand=brand,
                unit_price=price,
                unit_cost=cost,
                weight_kg=round(rng.uniform(0.1, 12.0), 2),
                is_active=rng.random() > 0.04,
                launched_at=f"2024-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                popularity=popularity,
            )
        )
    return products
