"""Declarative seed content for the development ``seed_data`` command.

Everything here is *development data*: illustrative names, prices, stock and
locations used to exercise the platform locally. Nothing is imported into
production code, and staff replace it with verified information before any
real use.

Money and quantities are written as strings and converted to ``Decimal`` in the
builders so there is never a float in the pipeline.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SEED_EMAIL_DOMAIN = "aashinaka.example"
LEGACY_DEMO_CUSTOMER_EMAIL = "seed.customer@example.invalid"
DEFAULT_DEMO_PASSWORD = "Shinaka!Seed2026"

#: Canonical units of measure (name, code, symbol, sort_order). Mirrors the
#: catalog migration so the seeder is resilient to a flushed database.
UNITS = [
    ("Kilogram", "kg", "kg", 10),
    ("Gram", "g", "g", 20),
    ("Tonne", "tonne", "t", 30),
    ("Bag", "bag", "bag", 40),
    ("Crate", "crate", "crate", 50),
    ("Litre", "litre", "L", 60),
    ("Piece", "piece", "pc", 70),
    ("Bunch", "bunch", "bunch", 80),
    ("Carton", "carton", "carton", 90),
    ("Hectare", "hectare", "ha", 100),
    ("Acre", "acre", "ac", 110),
]

#: Staff + customer accounts created by the seeder. ``role`` is a
#: ``UserRole`` value; ``state`` is a Nigeria state code.
USERS = [
    {
        "email": "owner@aashinaka.example",
        "role": "owner",
        "first_name": "Aisha",
        "last_name": "Shinaka",
        "phone": "08030000001",
        "state": "FC",
        "is_staff": True,
        "is_superuser": True,
        "title": "Founder & Owner",
    },
    {
        "email": "admin@aashinaka.example",
        "role": "administrator",
        "first_name": "Tunde",
        "last_name": "Bello",
        "phone": "08030000002",
        "state": "LA",
        "is_staff": True,
        "title": "Platform Administrator",
    },
    {
        "email": "sales@aashinaka.example",
        "role": "sales_officer",
        "first_name": "Chiamaka",
        "last_name": "Eze",
        "phone": "08030000003",
        "state": "LA",
        "is_staff": True,
        "title": "Sales Officer",
    },
    {
        "email": "inventory@aashinaka.example",
        "role": "inventory_officer",
        "first_name": "Musa",
        "last_name": "Abdullahi",
        "phone": "08030000004",
        "state": "KD",
        "is_staff": True,
        "title": "Inventory Officer",
    },
    {
        "email": "consultant@aashinaka.example",
        "role": "consultant",
        "first_name": "Dr. Funke",
        "last_name": "Adeyemi",
        "phone": "08030000005",
        "state": "OY",
        "is_staff": True,
        "title": "Lead Agribusiness Consultant",
    },
    {
        "email": "training@aashinaka.example",
        "role": "training_manager",
        "first_name": "Emeka",
        "last_name": "Nwosu",
        "phone": "08030000006",
        "state": "EN",
        "is_staff": True,
        "title": "Training Manager",
    },
    {
        "email": "export@aashinaka.example",
        "role": "export_officer",
        "first_name": "Zainab",
        "last_name": "Yusuf",
        "phone": "08030000007",
        "state": "KN",
        "is_staff": True,
        "title": "Export Officer",
    },
    {
        "email": "finance@aashinaka.example",
        "role": "finance_officer",
        "first_name": "Peter",
        "last_name": "Okonkwo",
        "phone": "08030000008",
        "state": "AN",
        "is_staff": True,
        "title": "Finance Officer",
    },
    {
        "email": "content@aashinaka.example",
        "role": "content_editor",
        "first_name": "Halima",
        "last_name": "Sani",
        "phone": "08030000009",
        "state": "KD",
        "is_staff": True,
        "title": "Content Editor",
    },
    {
        "email": "customer1@aashinaka.example",
        "role": "customer",
        "first_name": "Ngozi",
        "last_name": "Okafor",
        "phone": "08030000010",
        "state": "LA",
        "title": "Customer",
    },
    {
        "email": "customer2@aashinaka.example",
        "role": "customer",
        "first_name": "Ibrahim",
        "last_name": "Musa",
        "phone": "08030000011",
        "state": "KN",
        "title": "Customer",
    },
    {
        "email": "customer3@aashinaka.example",
        "role": "customer",
        "first_name": "Grace",
        "last_name": "Adeyemi",
        "phone": "08030000012",
        "state": "OY",
        "title": "Customer",
    },
]

#: Default delivery addresses (keyed by customer email).
ADDRESSES = [
    {
        "email": "customer1@aashinaka.example",
        "label": "Home",
        "recipient_name": "Ngozi Okafor",
        "phone": "08030000010",
        "state": "LA",
        "lga": "Ikeja",
        "city": "Ikeja",
        "street_address": "12 Example Crescent, Allen Avenue",
        "landmark": "Near Example Roundabout",
        "is_default": True,
    },
    {
        "email": "customer2@aashinaka.example",
        "label": "Warehouse",
        "recipient_name": "Ibrahim Musa",
        "phone": "08030000011",
        "state": "KN",
        "lga": "Kano Municipal",
        "city": "Kano",
        "street_address": "24 Example Trade Road, Sabon Gari",
        "landmark": "Beside Example Market",
        "is_default": True,
    },
    {
        "email": "customer3@aashinaka.example",
        "label": "Shop",
        "recipient_name": "Grace Adeyemi",
        "phone": "08030000012",
        "state": "OY",
        "lga": "Ibadan North",
        "city": "Ibadan",
        "street_address": "5 Example Layout, Bodija",
        "landmark": "",
        "is_default": True,
    },
]


# ---------------------------------------------------------------------------
# CMS — site configuration, navigation, pages
# ---------------------------------------------------------------------------

SITE_SETTINGS = {
    "site_name": "AA Shinaka",
    "tagline": "Nigeria's agricultural marketplace and agribusiness services platform",
    "description": (
        "AA Shinaka connects verified farm produce from Nigerian states and LGAs "
        "with buyers, and supports farmers and agribusinesses with consultancy, "
        "farming, marketing, storage, export and training services."
    ),
    "announcement_text": (
        "Development data in use: prices, stock and location details shown here are "
        "illustrative and only for local testing."
    ),
    "announcement_active": True,
    "phone": "+234 000 000 0000",
    "phone_secondary": "",
    "whatsapp_number": "2348000000000",
    "email": "hello@aashinaka.example",
    "address_line": "Plot 100, Example Business District",
    "city": "Abuja",
    "state": "FC",
    "country": "Nigeria",
    "facebook_url": "https://www.facebook.com/example",
    "instagram_url": "https://www.instagram.com/example",
    "twitter_url": "https://x.com/example",
    "linkedin_url": "https://www.linkedin.com/company/example",
    "youtube_url": "",
    "default_meta_title": "AA Shinaka — Agriculture, Aggregation & Agribusiness Services",
    "default_meta_description": (
        "Buy verified Nigerian farm produce and access consultancy, farming, "
        "marketing, storage, export and training services with AA Shinaka."
    ),
    "value_props": [
        {
            "title": "Verified origin",
            "body": "Every listing carries a state and LGA origin, with verification notes.",
        },
        {
            "title": "Transparent pricing",
            "body": "Current prices, bulk tiers and reference prices are shown clearly.",
        },
        {
            "title": "End-to-end support",
            "body": "From farm advisory to storage, logistics and export documentation.",
        },
        {
            "title": "Built for agribusiness",
            "body": "Tools for farmers, aggregators, processors and institutional buyers.",
        },
    ],
}

#: Navigation entries. ``url_name`` is a Django URL name, ``url`` is a
#: literal URL and ``page`` is the slug of a CMS page or service page.
NAVIGATION = [
    {"label": "Home", "url_name": "core:home", "placement": "header", "sort_order": 0},
    {"label": "Shop", "url_name": "catalog:shop_index", "placement": "header", "sort_order": 10},
    {
        "label": "Services",
        "url_name": "cms:service_list",
        "placement": "header",
        "sort_order": 20,
        "children": [
            {
                "label": "Consultancy",
                "page": "consultancy-advisory",
                "placement": "header",
                "sort_order": 0,
            },
            {"label": "Farming", "page": "farm-services", "placement": "header", "sort_order": 10},
            {
                "label": "Marketing",
                "page": "agricultural-marketing",
                "placement": "header",
                "sort_order": 20,
            },
            {
                "label": "Storage",
                "page": "storage-and-warehousing",
                "placement": "header",
                "sort_order": 30,
            },
            {
                "label": "Export",
                "page": "export-trade-services",
                "placement": "header",
                "sort_order": 40,
            },
        ],
    },
    {"label": "Training", "url": "/training/", "placement": "header", "sort_order": 30},
    {"label": "About", "url_name": "cms:about", "placement": "header", "sort_order": 40},
    {"label": "Contact", "url_name": "cms:contact", "placement": "header", "sort_order": 50},
    {"label": "About", "url_name": "cms:about", "placement": "footer", "sort_order": 0},
    {"label": "Services", "url_name": "cms:service_list", "placement": "footer", "sort_order": 10},
    {"label": "Training", "url": "/training/", "placement": "footer", "sort_order": 20},
    {"label": "News", "url_name": "cms:blog_list", "placement": "footer", "sort_order": 30},
    {"label": "FAQs", "url_name": "cms:faq_list", "placement": "footer", "sort_order": 40},
    {"label": "Privacy Policy", "page": "privacy-policy", "placement": "footer", "sort_order": 50},
    {
        "label": "Terms of Service",
        "page": "terms-of-service",
        "placement": "footer",
        "sort_order": 60,
    },
]

#: (slug, title, page_type, summary, body_html, hero_key, featured)
PAGES = [
    (
        "about",
        "About AA Shinaka",
        "about",
        "An agricultural platform built to move Nigerian produce and knowledge.",
        (
            "<p>AA Shinaka is an agricultural business platform that connects "
            "verified farm produce from across Nigeria with buyers, while supporting "
            "farmers and agribusinesses with practical services.</p>"
            "<h2>What we do</h2>"
            "<p>We aggregate and market produce by state and LGA, provide "
            "consultancy and farm services, offer storage and warehousing, support "
            "export trade, and run a training academy for the next generation of "
            "agribusiness professionals.</p>"
            "<h2>How we work</h2>"
            "<p>Every listing records its origin, prices are transparent, and stock "
            "is tracked per warehouse. Our services are delivered by specialist "
            "staff and partners.</p>"
        ),
        "farmland",
        True,
    ),
    (
        "contact",
        "Contact us",
        "contact",
        "Reach the AA Shinaka team for sales, services or partnerships.",
        (
            "<p>Our team is available to help with produce enquiries, service "
            "bookings, storage, export documentation and training.</p>"
            "<p>Use the enquiry form below and we will respond as soon as possible.</p>"
        ),
        "consultation",
        False,
    ),
    (
        "privacy-policy",
        "Privacy Policy",
        "privacy",
        "How AA Shinaka collects and protects your information.",
        (
            "<p>This privacy policy explains what information AA Shinaka collects, "
            "why we collect it, and how we protect it. This is development "
            "placeholder content and must be reviewed before publication.</p>"
            "<h2>Information we collect</h2>"
            "<p>Account details, order and service information, and messages you "
            "send us.</p>"
            "<h2>How we use it</h2>"
            "<p>To provide the marketplace and services, process orders, and improve "
            "the platform.</p>"
        ),
        "quality",
        False,
    ),
    (
        "terms-of-service",
        "Terms of Service",
        "terms",
        "The terms governing use of the AA Shinaka platform.",
        (
            "<p>These terms govern your use of the AA Shinaka platform. This is "
            "development placeholder content and must be reviewed before "
            "publication.</p>"
            "<h2>Using the platform</h2>"
            "<p>You agree to provide accurate information and to use the platform "
            "lawfully.</p>"
            "<h2>Orders and services</h2>"
            "<p>Orders and service requests are subject to availability, "
            "confirmation and our published policies.</p>"
        ),
        "handshake",
        False,
    ),
]

#: (title, eyebrow, subtitle, cta_label, cta_url, secondary_label,
#:  secondary_url, image_key, featured, sort)
HERO_BANNERS = [
    (
        "Verified Nigerian produce, delivered with confidence",
        "AA Shinaka marketplace",
        (
            "Buy grains, tubers, vegetables, cash crops and agro inputs by state "
            "and LGA, with transparent pricing and tracked stock."
        ),
        "Browse the marketplace",
        "/shop/",
        "Talk to our team",
        "/services/",
        "marketplace",
        True,
        0,
    ),
    (
        "From farm to buyer, without guesswork",
        "Built for agribusiness",
        ("Origin-verified listings, bulk pricing tiers and market reference prices in one place."),
        "Explore products",
        "/shop/",
        "See our services",
        "/services/",
        "harvest",
        False,
        10,
    ),
    (
        "Grow with expert agribusiness support",
        "Consultancy · Farming · Storage · Export",
        ("Plan, produce, store and export with specialist teams behind you."),
        "Discover services",
        "/services/",
        "Enrol in training",
        "/training/",
        "consultation",
        False,
        20,
    ),
]

#: (name, short_description, description, icon, image_key, featured, sort)
DIVISIONS = [
    (
        "Agricultural Consultancy",
        "Advisory for farm businesses, cooperatives and agribusiness investors.",
        "One-to-one and group advisory covering farm planning, soil and crop "
        "management, finance, records and market strategy.",
        "🧭",
        "consultation",
        True,
        0,
    ),
    (
        "Farming Services",
        "Practical field services from land preparation to crop management.",
        "Field teams support land preparation, planting, irrigation advisory, "
        "crop protection and project management.",
        "🌱",
        "farmland",
        True,
        10,
    ),
    (
        "Agricultural Marketing",
        "Aggregation, offtake and market linkage for produce.",
        "We help producers and cooperatives aggregate produce, reach buyers and "
        "improve packaging and positioning.",
        "📈",
        "marketplace",
        True,
        20,
    ),
    (
        "Storage & Warehousing",
        "Clean, secure storage with tracked capacity.",
        "Facilities accept a range of produce types and track capacity, bookings and inspections.",
        "🏭",
        "warehouse",
        False,
        30,
    ),
    (
        "Export Trade Services",
        "Export readiness, documentation and logistics coordination.",
        "Support for export enquiries, compliance requirements, documentation and "
        "shipment coordination to approved destinations.",
        "🚢",
        "shipping",
        False,
        40,
    ),
    (
        "Training Academy",
        "Practical courses for farmers and agribusiness professionals.",
        "Scheduled and self-paced courses with modules, assessments and "
        "certificates of completion.",
        "🎓",
        "training",
        False,
        50,
    ),
]

#: (slug, division_name, title, eyebrow, intro, body, icon, hero_key, benefits, steps, sort)
SERVICE_PAGES = [
    (
        "consultancy-advisory",
        "Agricultural Consultancy",
        "Agricultural Consultancy",
        "Advisory that pays for itself",
        "Practical, evidence-based advice for farms, cooperatives and agribusinesses.",
        "<p>Our consultants work with you to plan and improve your agricultural "
        "business, from soil health and crop choice to records, finance and market "
        "strategy.</p>",
        "🧭",
        "consultation",
        [
            "Farm business planning and feasibility",
            "Soil health and crop management advice",
            "Records, costing and access to finance",
            "Market entry and product positioning",
        ],
        [
            "Send an enquiry with your goals",
            "We schedule a consultation",
            "Receive a written summary and recommendations",
        ],
        0,
    ),
    (
        "farm-services",
        "Farming Services",
        "Farming Services",
        "Field support that delivers",
        "Hands-on support for land preparation, planting, irrigation and crop care.",
        "<p>Our field teams supplement your workforce at the points that matter "
        "most, with clear reporting on every activity.</p>",
        "🌱",
        "farmland",
        [
            "Land preparation and mechanisation support",
            "Planting and crop establishment",
            "Irrigation and water management advice",
            "Crop protection and monitoring",
        ],
        [
            "Describe your farm and requirements",
            "We assess the site and scope",
            "Agree a schedule and get to work",
        ],
        10,
    ),
    (
        "agricultural-marketing",
        "Agricultural Marketing",
        "Agricultural Marketing",
        "Reach the right buyers",
        "Aggregation, offtake and market linkage for producers and cooperatives.",
        "<p>We help you move produce reliably — aggregating volumes, connecting "
        "with buyers and improving packaging and presentation.</p>",
        "📈",
        "marketplace",
        [
            "Produce aggregation and offtake",
            "Buyer and market linkage",
            "Packaging and presentation advice",
            "Pricing and negotiation support",
        ],
        [
            "Tell us what you have and when",
            "We map buyers and agree terms",
            "Coordinate collection and delivery",
        ],
        20,
    ),
    (
        "storage-and-warehousing",
        "Storage & Warehousing",
        "Storage & Warehousing",
        "Keep quality, reduce losses",
        "Tracked storage capacity for a range of agricultural produce.",
        "<p>Store produce safely in facilities with recorded capacity, bookings "
        "and inspections so quality is protected and losses are reduced.</p>",
        "🏭",
        "warehouse",
        [
            "Capacity across multiple facilities",
            "Bookings and check-in/check-out records",
            "Inspections with condition notes",
            "Support for produce-specific conditions",
        ],
        [
            "Request storage for your produce",
            "We confirm capacity and dates",
            "Check in, store, and collect",
        ],
        30,
    ),
    (
        "export-trade-services",
        "Export Trade Services",
        "Export Trade Services",
        "Export with confidence",
        "Readiness, compliance and logistics for approved export destinations.",
        "<p>We help you understand destination requirements, prepare the right "
        "documentation, and coordinate shipments to approved markets.</p>",
        "🚢",
        "shipping",
        [
            "Destination and requirement guidance",
            "Document preparation and review",
            "Compliance checklists",
            "Logistics and shipment coordination",
        ],
        [
            "Submit an export enquiry",
            "We review eligibility and requirements",
            "Prepare documents and coordinate shipment",
        ],
        40,
    ),
]

#: (service_slug, name, description, icon, sort)
SERVICE_CATEGORIES = [
    ("consultancy-advisory", "Farm Business Planning", "Feasibility and business plans.", "📋", 0),
    ("consultancy-advisory", "Soil & Crop Advisory", "Soil health and crop management.", "🌾", 10),
    (
        "consultancy-advisory",
        "Agribusiness Finance",
        "Records, costing and finance readiness.",
        "💼",
        20,
    ),
    ("farm-services", "Land Preparation", "Clearing, ploughing and harrowing.", "🚜", 0),
    ("farm-services", "Planting Support", "Planting and crop establishment.", "🌱", 10),
    ("farm-services", "Irrigation Advisory", "Water management and scheduling.", "💧", 20),
    ("agricultural-marketing", "Aggregation", "Collection and consolidation of produce.", "📦", 0),
    ("agricultural-marketing", "Market Linkage", "Connecting producers with buyers.", "🤝", 10),
    ("storage-and-warehousing", "Dry Storage", "Ventilated storage for grains and tubers.", "🏚️", 0),
    ("storage-and-warehousing", "Cold Storage", "Temperature-controlled storage.", "❄️", 10),
    ("export-trade-services", "Export Readiness", "Eligibility and requirement checks.", "✅", 0),
    ("export-trade-services", "Documentation", "Preparing and reviewing documents.", "📄", 10),
]

#: (question, answer, service_slug_or_empty, sort)
FAQS = [
    (
        "How do I know where a product comes from?",
        "Every listing records the state and LGA of origin, with a verification "
        "status and provenance notes visible on the product page.",
        "",
        0,
    ),
    (
        "Can I buy in bulk?",
        "Yes. Many listings offer wholesale price tiers that reduce the unit price "
        "as quantity increases. Tiers are shown on the listing.",
        "",
        10,
    ),
    (
        "How is stock tracked?",
        "Stock is tracked per warehouse and rolled up to each listing so the "
        "quantity you see reflects what is available.",
        "",
        20,
    ),
    (
        "Do you deliver across Nigeria?",
        "Delivery is available by zone with configured methods and fees, shown at checkout.",
        "",
        30,
    ),
    (
        "How do I book a service?",
        "Create a request for the service you need; our team reviews it and "
        "responds with a quotation or appointment.",
        "",
        40,
    ),
    (
        "What are market reference prices?",
        "Reference prices are informational survey values stored separately from "
        "selling prices and shown for context only.",
        "",
        50,
    ),
    (
        "Who can enrol in training?",
        "Courses are open to registered users. Some courses have prerequisites, "
        "which are listed on the course page.",
        "",
        60,
    ),
    (
        "Can you help me export?",
        "We support export enquiries for approved destinations, covering "
        "requirements, documentation and logistics coordination.",
        "export-trade-services",
        0,
    ),
    (
        "How do consultations work?",
        "Choose a consultancy service, request a consultation, and a consultant "
        "will confirm a time with you.",
        "consultancy-advisory",
        0,
    ),
    (
        "How is produce stored safely?",
        "Facilities track capacity, bookings and inspections, and record the "
        "condition of produce at check-in and check-out.",
        "storage-and-warehousing",
        0,
    ),
]

#: (author_name, author_role, company, quote, image_key, rating, featured, sort)
TESTIMONIALS = [
    (
        "Alhaji Sani Bello",
        "Cooperative Chairman",
        "Example Farmers Cooperative",
        "The origin details and clear pricing made it easy for our members to buy "
        "and sell with confidence.",
        "portrait_man",
        5,
        True,
        0,
    ),
    (
        "Mrs. Ada Nwankwo",
        "Poultry Farmer",
        "Example Poultry Farms",
        "The training and consultancy gave us a practical plan we could actually "
        "follow. Our records and margins improved.",
        "portrait_woman",
        5,
        True,
        10,
    ),
    (
        "Mr. Kunle Adebayo",
        "Produce Aggregator",
        "",
        "Aggregating through AA Shinaka connected us with buyers we could not reach before.",
        "portrait_man",
        4,
        False,
        20,
    ),
    (
        "Hauwa Ibrahim",
        "Agro-Processor",
        "Example Agro Processing",
        "Storage with tracked capacity means we lose far less to spoilage.",
        "portrait_woman",
        5,
        False,
        30,
    ),
]

#: (name, role_title, bio, image_key, sort)
TEAM_MEMBERS = [
    (
        "Aisha Shinaka",
        "Founder & Owner",
        "Leads the platform's vision of connecting Nigerian agriculture with "
        "reliable markets and knowledge.",
        "portrait_woman",
        0,
    ),
    (
        "Dr. Funke Adeyemi",
        "Lead Agribusiness Consultant",
        "Advises farms and cooperatives on planning, finance and market strategy.",
        "portrait_woman",
        10,
    ),
    (
        "Emeka Nwosu",
        "Training Manager",
        "Designs and delivers practical courses for farmers and agribusiness professionals.",
        "portrait_man",
        20,
    ),
    (
        "Zainab Yusuf",
        "Export Officer",
        "Guides export readiness, documentation and compliance for approved destinations.",
        "portrait_woman",
        30,
    ),
]

#: Blog category name -> description.
BLOG_CATEGORIES = {
    "Agronomy": "Crop production and field practice.",
    "Market Insights": "Prices, demand and market trends.",
    "Storage & Post-Harvest": "Reducing losses and protecting quality.",
    "Agribusiness": "Running and growing an agricultural business.",
}

#: (slug, title, category, excerpt, body_html, image_key, reading_minutes, featured, sort)
BLOG_POSTS = [
    (
        "improving-maize-yields",
        "Five practical steps to improve maize yields",
        "Agronomy",
        "Simple, field-tested steps that make a measurable difference to maize harvests.",
        "<p>Improving maize yields rarely depends on one big change. It usually "
        "comes from getting several smaller things right.</p>"
        "<h2>1. Start with good seed</h2>"
        "<p>Use certified seed suited to your agro-ecology and planting window.</p>"
        "<h2>2. Prepare the land well</h2>"
        "<p>Good tilth gives roots room to grow and improves water infiltration.</p>"
        "<h2>3. Manage fertility</h2>"
        "<p>Combine organic matter with balanced fertiliser based on soil needs.</p>"
        "<h2>4. Control weeds early</h2>"
        "<p>Early weed control protects yield during the critical window.</p>"
        "<h2>5. Scout and act</h2>"
        "<p>Regular scouting catches pests and disease before they spread.</p>",
        "maize",
        4,
        True,
        0,
    ),
    (
        "understanding-market-prices",
        "Understanding market and reference prices",
        "Market Insights",
        "Why reference prices matter, and how they differ from selling prices.",
        "<p>It helps to know the difference between a market reference price and a "
        "selling price before you negotiate.</p>"
        "<h2>Reference prices</h2>"
        "<p>Reference prices are survey values that describe a market; they are "
        "informational.</p>"
        "<h2>Selling prices</h2>"
        "<p>Selling prices are the actual prices at which produce is offered, and "
        "can include bulk tiers.</p>",
        "market",
        3,
        False,
        10,
    ),
    (
        "reducing-post-harvest-losses",
        "Reducing post-harvest losses with better storage",
        "Storage & Post-Harvest",
        "Practical storage choices that protect quality and value.",
        "<p>Post-harvest losses quietly erode margins. Better storage protects "
        "both quality and value.</p>"
        "<h2>Dry properly</h2>"
        "<p>Moisture is the enemy of stored grain. Dry thoroughly before storage.</p>"
        "<h2>Keep it clean and ventilated</h2>"
        "<p>Clean, ventilated storage reduces mould and pest damage.</p>"
        "<h2>Track what you store</h2>"
        "<p>Records of quantity and condition help you act before losses grow.</p>",
        "storage",
        4,
        False,
        20,
    ),
    (
        "records-that-grow-your-farm",
        "Records that actually grow your farm business",
        "Agribusiness",
        "The few records that turn a farm into a business you can manage.",
        "<p>Good records are the difference between guessing and managing.</p>"
        "<h2>Track inputs and costs</h2>"
        "<p>Know what each plot costs to produce.</p>"
        "<h2>Track sales and margins</h2>"
        "<p>Understand which products and channels pay.</p>"
        "<h2>Review regularly</h2>"
        "<p>Compare plans to results every season and adjust.</p>",
        "finance",
        3,
        False,
        30,
    ),
    (
        "getting-export-ready",
        "Getting export-ready: what buyers look for",
        "Agribusiness",
        "An overview of grades, documentation and consistency in export trade.",
        "<p>Export buyers look for consistency, quality and compliant paperwork.</p>"
        "<h2>Grade and quality</h2>"
        "<p>Meet the destination's grade and quality requirements.</p>"
        "<h2>Documentation</h2>"
        "<p>Prepare certificates, invoices and packing lists correctly.</p>"
        "<h2>Consistency</h2>"
        "<p>Reliable volume and quality build long-term buyer relationships.</p>",
        "shipping",
        5,
        False,
        40,
    ),
]


# ---------------------------------------------------------------------------
# Legacy demo records (kept for backward compatibility with the old seeder)
# ---------------------------------------------------------------------------

LEGACY_PAGE = {
    "slug": "seed-example-page",
    "title": "Sample draft: About this page",
    "summary": "Placeholder page content for local development preview.",
    "body": (
        "<p>This is sample draft content for previewing the CMS. Replace it with "
        "approved company information before publication.</p>"
    ),
}
LEGACY_BLOG_CATEGORY = {
    "name": "Seed Example Articles",
    "slug": "seed-example-articles",
    "description": "Placeholder articles created by the seed_data command.",
}
LEGACY_BLOG_POSTS = (
    {
        "slug": "seed-example-harvest-records",
        "title": "Sample draft: Keeping harvest records",
        "excerpt": "Placeholder content for previewing the blog detail page.",
        "body": (
            "<p>This is sample draft content for previewing the blog detail page. "
            "Replace it with reviewed, accurate content before publication.</p>"
        ),
    },
    {
        "slug": "seed-example-produce-storage",
        "title": "Sample draft: Planning produce storage",
        "excerpt": "Placeholder content for previewing a related article.",
        "body": (
            "<p>This is sample draft content for previewing an article and related "
            "posts. Replace it with reviewed, accurate content before publication.</p>"
        ),
    },
    {
        "slug": "seed-example-market-planning",
        "title": "Sample draft: Preparing a market plan",
        "excerpt": "Placeholder content for previewing the blog listing and detail pages.",
        "body": (
            "<p>This is sample draft content for previewing the blog listing and "
            "detail pages. Replace it with reviewed, accurate content before "
            "publication.</p>"
        ),
    },
)
LEGACY_CONSULTANCY_SERVICE = {
    "name": "Seed example consultancy service",
    "slug": "seed-example-consultancy-service",
}
LEGACY_TRAINING_CATEGORY = {
    "name": "Seed Example Courses",
    "slug": "seed-example-courses",
}
LEGACY_COURSE = {
    "title": "Sample draft: Agricultural business fundamentals",
    "slug": "seed-example-agricultural-business-fundamentals",
}


# ---------------------------------------------------------------------------
# Catalogue — tags, categories, products, warehouses
# ---------------------------------------------------------------------------

TAGS = [
    "Fresh",
    "Organic",
    "Grade A",
    "Bulk",
    "Export Grade",
    "Local",
    "Seasonal",
    "Non-GMO",
    "Cleaned",
    "Dried",
]

#: Nested category tree. Children become leaf categories products attach to.
CATEGORIES = [
    (
        "Grains & Cereals",
        "🌾",
        True,
        [
            ("Maize", "maize"),
            ("Rice", "rice"),
            ("Sorghum", "sorghum"),
            ("Millet", "millet"),
        ],
    ),
    (
        "Legumes & Pulses",
        "🫘",
        True,
        [
            ("Cowpea (Beans)", "cowpea"),
            ("Groundnut", "groundnut"),
            ("Soybean", "soybean"),
            ("Sesame Seeds", "sesame"),
        ],
    ),
    (
        "Roots & Tubers",
        "🥔",
        True,
        [
            ("Cassava", "cassava"),
            ("Yam", "yam"),
            ("Sweet Potato", "sweet_potato"),
            ("Irish Potato", "irish_potato"),
        ],
    ),
    (
        "Vegetables & Fruits",
        "🍅",
        True,
        [
            ("Tomato", "tomato"),
            ("Onion", "onion"),
            ("Pepper", "pepper"),
            ("Okra", "okra"),
            ("Plantain", "plantain"),
            ("Citrus & Mangoes", "orange"),
        ],
    ),
    (
        "Cash Crops",
        "💠",
        False,
        [
            ("Cocoa", "cocoa"),
            ("Cashew", "cashew"),
            ("Ginger", "ginger"),
            ("Oil Palm", "palm_oil"),
        ],
    ),
    (
        "Livestock & Poultry",
        "🐔",
        False,
        [
            ("Poultry & Eggs", "eggs"),
            ("Small Ruminants", "goat"),
        ],
    ),
    (
        "Agro Inputs",
        "🧪",
        False,
        [
            ("Fertilisers & Soil Amendments", "fertiliser"),
            ("Certified Seeds", "seeds"),
        ],
    ),
]

#: Product listing row. Money/quantities are strings → ``Decimal`` in builders.
#: (state, lga, package_size, package_unit, price, compare_at, stock, low_stock,
#:  warehouse, wholesale tiers)
_MAIZE_LISTINGS = [
    {
        "state": "KD",
        "lga": "Zaria",
        "package_size": "50.000",
        "package_unit": "kg",
        "price": "42000.00",
        "compare_at": "45000.00",
        "stock": "1600.000",
        "low_stock": "200.000",
        "warehouse": "MAIN",
        "wholesale": [("100.000", "41500.00"), ("500.000", "40250.00")],
        "origin_verification": "verified",
        "origin_note": "Aggregated from smallholder farmers around Zaria, Kaduna State.",
    },
    {
        "state": "KN",
        "lga": "Kano Municipal",
        "package_size": "50.000",
        "package_unit": "kg",
        "price": "42500.00",
        "compare_at": None,
        "stock": "1200.000",
        "low_stock": "200.000",
        "warehouse": "KAN",
        "wholesale": [("100.000", "42000.00")],
        "origin_verification": "pending",
        "origin_note": "",
    },
]

PRODUCTS = [
    {
        "name": "Yellow Maize",
        "category": "Maize",
        "unit": "kg",
        "short_description": "Cleaned, dried yellow maize suitable for milling and feed.",
        "description": (
            "Well-dried yellow maize with low moisture and minimal foreign matter, "
            "suitable for milling, feed production and food processing."
        ),
        "variety": "SAMMAZ 15",
        "grade": "Grade A",
        "harvest_season": "September - November",
        "tags": ["Cleaned", "Grade A", "Bulk", "Non-GMO"],
        "image": "maize",
        "is_featured": True,
        "listings": _MAIZE_LISTINGS,
    },
    {
        "name": "White Maize",
        "category": "Maize",
        "unit": "kg",
        "short_description": "Premium white maize for food processing.",
        "description": "White maize with good test weight, cleaned and dried for food use.",
        "variety": "SAMMAZ 40",
        "grade": "Grade A",
        "harvest_season": "September - November",
        "tags": ["Cleaned", "Grade A", "Local"],
        "image": "maize",
        "is_featured": False,
        "listings": [
            {
                "state": "PL",
                "lga": "Jos South",
                "package_size": "50.000",
                "package_unit": "kg",
                "price": "44000.00",
                "compare_at": None,
                "stock": "800.000",
                "low_stock": "150.000",
                "warehouse": "MAIN",
                "wholesale": [],
                "origin_verification": "verified",
                "origin_note": "Sourced from Plateau State.",
            }
        ],
    },
    {
        "name": "Parboiled Rice",
        "category": "Rice",
        "unit": "kg",
        "short_description": "Locally milled parboiled rice, destoned and cleaned.",
        "description": (
            "Parboiled long-grain rice, milled locally, destoned and cleaned for "
            "good cooking quality."
        ),
        "variety": "FARO 44",
        "grade": "Grade A",
        "harvest_season": "All year",
        "tags": ["Cleaned", "Grade A", "Local"],
        "image": "rice",
        "is_featured": True,
        "listings": [
            {
                "state": "EB",
                "lga": "Abakaliki",
                "package_size": "50.000",
                "package_unit": "kg",
                "price": "78000.00",
                "compare_at": "82000.00",
                "stock": "900.000",
                "low_stock": "150.000",
                "warehouse": "BEN",
                "wholesale": [("100.000", "77000.00"), ("500.000", "75000.00")],
                "origin_verification": "verified",
                "origin_note": "Milled in Ebonyi State.",
            },
            {
                "state": "NI",
                "lga": "Bida",
                "package_size": "50.000",
                "package_unit": "kg",
                "price": "79000.00",
                "compare_at": None,
                "stock": "500.000",
                "low_stock": "100.000",
                "warehouse": "MAIN",
                "wholesale": [],
                "origin_verification": "pending",
                "origin_note": "",
            },
        ],
    },
    {
        "name": "Ofada Rice",
        "category": "Rice",
        "unit": "kg",
        "short_description": "Aromatic local Ofada rice, unpolished.",
        "description": "Traditional unpolished Ofada rice with a distinctive aroma.",
        "variety": "Ofada",
        "grade": "Grade B",
        "harvest_season": "All year",
        "tags": ["Local", "Seasonal"],
        "image": "rice",
        "is_featured": False,
        "listings": [
            {
                "state": "OG",
                "lga": "Obafemi Owode",
                "package_size": "25.000",
                "package_unit": "kg",
                "price": "45000.00",
                "compare_at": None,
                "stock": "400.000",
                "low_stock": "80.000",
                "warehouse": "LAG",
                "wholesale": [],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Guinea Corn (Sorghum)",
        "category": "Sorghum",
        "unit": "kg",
        "short_description": "Red sorghum for food and brewing.",
        "description": "Cleaned red sorghum suitable for food products and brewing.",
        "variety": "Red sorghum",
        "grade": "Grade A",
        "harvest_season": "October - December",
        "tags": ["Cleaned", "Bulk"],
        "image": "sorghum",
        "is_featured": False,
        "listings": [
            {
                "state": "BA",
                "lga": "Bauchi",
                "package_size": "100.000",
                "package_unit": "kg",
                "price": "72000.00",
                "compare_at": None,
                "stock": "700.000",
                "low_stock": "120.000",
                "warehouse": "MAIN",
                "wholesale": [("500.000", "70000.00")],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Pearl Millet",
        "category": "Millet",
        "unit": "kg",
        "short_description": "Clean pearl millet for flour and feed.",
        "description": "Well-cleaned pearl millet with good grain fill.",
        "variety": "Pearl millet",
        "grade": "Grade A",
        "harvest_season": "October - December",
        "tags": ["Cleaned", "Bulk"],
        "image": "millet",
        "is_featured": False,
        "listings": [
            {
                "state": "KN",
                "lga": "Gaya",
                "package_size": "100.000",
                "package_unit": "kg",
                "price": "68000.00",
                "compare_at": None,
                "stock": "600.000",
                "low_stock": "100.000",
                "warehouse": "KAN",
                "wholesale": [],
                "origin_verification": "pending",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Cowpea (White Beans)",
        "category": "Cowpea (Beans)",
        "unit": "kg",
        "short_description": "Clean white cowpea, well sorted.",
        "description": "Sorted white cowpea with low foreign matter, suitable for food use.",
        "variety": "IT90K-277-2",
        "grade": "Grade A",
        "harvest_season": "November - January",
        "tags": ["Cleaned", "Grade A"],
        "image": "cowpea",
        "is_featured": True,
        "listings": [
            {
                "state": "BA",
                "lga": "Bauchi",
                "package_size": "50.000",
                "package_unit": "kg",
                "price": "85000.00",
                "compare_at": None,
                "stock": "700.000",
                "low_stock": "120.000",
                "warehouse": "MAIN",
                "wholesale": [("100.000", "84000.00")],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Groundnut (Shelled)",
        "category": "Groundnut",
        "unit": "kg",
        "short_description": "Shelled groundnut kernels for oil and food.",
        "description": "Shelled groundnut kernels, cleaned and graded.",
        "variety": "SAMNUT 23",
        "grade": "Grade A",
        "harvest_season": "October - December",
        "tags": ["Cleaned", "Bulk"],
        "image": "groundnut",
        "is_featured": False,
        "listings": [
            {
                "state": "KD",
                "lga": "Zaria",
                "package_size": "50.000",
                "package_unit": "kg",
                "price": "95000.00",
                "compare_at": None,
                "stock": "500.000",
                "low_stock": "100.000",
                "warehouse": "MAIN",
                "wholesale": [],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Soybean",
        "category": "Soybean",
        "unit": "kg",
        "short_description": "Clean soybean for processing and feed.",
        "description": "Well-cleaned soybean with good protein content.",
        "variety": "TGX",
        "grade": "Grade A",
        "harvest_season": "October - December",
        "tags": ["Cleaned", "Bulk", "Non-GMO"],
        "image": "soybean",
        "is_featured": False,
        "listings": [
            {
                "state": "BN",
                "lga": "Makurdi",
                "package_size": "50.000",
                "package_unit": "kg",
                "price": "88000.00",
                "compare_at": None,
                "stock": "500.000",
                "low_stock": "100.000",
                "warehouse": "BEN",
                "wholesale": [],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Sesame Seeds",
        "category": "Sesame Seeds",
        "unit": "kg",
        "short_description": "Export-grade white sesame seeds.",
        "description": "Clean white sesame seeds suitable for export markets.",
        "variety": "White sesame",
        "grade": "Export Grade",
        "harvest_season": "November - December",
        "tags": ["Export Grade", "Cleaned", "Bulk"],
        "image": "sesame",
        "is_featured": False,
        "listings": [
            {
                "state": "JI",
                "lga": "Hadejia",
                "package_size": "50.000",
                "package_unit": "kg",
                "price": "165000.00",
                "compare_at": None,
                "stock": "400.000",
                "low_stock": "80.000",
                "warehouse": "KAN",
                "wholesale": [("200.000", "160000.00")],
                "origin_verification": "verified",
                "origin_note": "Prepared for export grading.",
            }
        ],
    },
    {
        "name": "Fresh Cassava Tubers",
        "category": "Cassava",
        "unit": "kg",
        "short_description": "Fresh cassava tubers for processing.",
        "description": "Fresh, firm cassava tubers harvested to order.",
        "variety": "TME 419",
        "grade": "Grade A",
        "harvest_season": "All year",
        "tags": ["Fresh", "Local"],
        "image": "cassava",
        "is_featured": True,
        "listings": [
            {
                "state": "OY",
                "lga": "Ibadan North",
                "package_size": "100.000",
                "package_unit": "kg",
                "price": "35000.00",
                "compare_at": None,
                "stock": "1500.000",
                "low_stock": "200.000",
                "warehouse": "LAG",
                "wholesale": [("1000.000", "32000.00")],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "White Yam Tubers",
        "category": "Yam",
        "unit": "kg",
        "short_description": "Fresh white yam tubers, graded.",
        "description": "Fresh white yam tubers, sorted by size.",
        "variety": "White yam",
        "grade": "Grade A",
        "harvest_season": "August - December",
        "tags": ["Fresh", "Grade A"],
        "image": "yam",
        "is_featured": True,
        "listings": [
            {
                "state": "BN",
                "lga": "Gboko",
                "package_size": "100.000",
                "package_unit": "kg",
                "price": "65000.00",
                "compare_at": None,
                "stock": "900.000",
                "low_stock": "150.000",
                "warehouse": "BEN",
                "wholesale": [("500.000", "63000.00")],
                "origin_verification": "verified",
                "origin_note": "",
            },
            {
                "state": "TA",
                "lga": "Wukari",
                "package_size": "100.000",
                "package_unit": "kg",
                "price": "66000.00",
                "compare_at": None,
                "stock": "400.000",
                "low_stock": "100.000",
                "warehouse": "BEN",
                "wholesale": [],
                "origin_verification": "pending",
                "origin_note": "",
            },
        ],
    },
    {
        "name": "Sweet Potato",
        "category": "Sweet Potato",
        "unit": "kg",
        "short_description": "Fresh orange-fleshed sweet potato.",
        "description": "Fresh orange-fleshed sweet potato tubers.",
        "variety": "Orange-fleshed",
        "grade": "Grade A",
        "harvest_season": "All year",
        "tags": ["Fresh", "Local"],
        "image": "sweet_potato",
        "is_featured": False,
        "listings": [
            {
                "state": "PL",
                "lga": "Barkin Ladi",
                "package_size": "100.000",
                "package_unit": "kg",
                "price": "45000.00",
                "compare_at": None,
                "stock": "500.000",
                "low_stock": "100.000",
                "warehouse": "MAIN",
                "wholesale": [],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Irish Potato",
        "category": "Irish Potato",
        "unit": "kg",
        "short_description": "Fresh Irish potato from the Plateau.",
        "description": "Fresh Irish potato tubers, graded and bagged.",
        "variety": "Nicola",
        "grade": "Grade A",
        "harvest_season": "All year",
        "tags": ["Fresh", "Grade A"],
        "image": "irish_potato",
        "is_featured": False,
        "listings": [
            {
                "state": "PL",
                "lga": "Jos South",
                "package_size": "50.000",
                "package_unit": "kg",
                "price": "52000.00",
                "compare_at": None,
                "stock": "600.000",
                "low_stock": "120.000",
                "warehouse": "MAIN",
                "wholesale": [],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Fresh Tomatoes",
        "category": "Tomato",
        "unit": "kg",
        "short_description": "Firm, fresh tomatoes in crates.",
        "description": "Fresh, firm tomatoes packed for market and processing.",
        "variety": "Padma",
        "grade": "Grade A",
        "harvest_season": "All year",
        "tags": ["Fresh", "Seasonal"],
        "image": "tomato",
        "is_featured": True,
        "listings": [
            {
                "state": "KN",
                "lga": "Kano Municipal",
                "package_size": "25.000",
                "package_unit": "crate",
                "price": "18000.00",
                "compare_at": "20000.00",
                "stock": "800.000",
                "low_stock": "100.000",
                "warehouse": "KAN",
                "wholesale": [("50.000", "17500.00")],
                "origin_verification": "verified",
                "origin_note": "Packed in standard 25 kg crates.",
            }
        ],
    },
    {
        "name": "Red Onions",
        "category": "Onion",
        "unit": "kg",
        "short_description": "Well-cured red onions.",
        "description": "Well-cured red onions with good shelf life.",
        "variety": "Red creole",
        "grade": "Grade A",
        "harvest_season": "February - May",
        "tags": ["Grade A", "Bulk"],
        "image": "onion",
        "is_featured": True,
        "listings": [
            {
                "state": "KD",
                "lga": "Kaduna North",
                "package_size": "50.000",
                "package_unit": "kg",
                "price": "55000.00",
                "compare_at": None,
                "stock": "900.000",
                "low_stock": "150.000",
                "warehouse": "MAIN",
                "wholesale": [("200.000", "53000.00")],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Chilli Pepper",
        "category": "Pepper",
        "unit": "kg",
        "short_description": "Fresh red chilli pepper.",
        "description": "Fresh, hot red chilli pepper, graded.",
        "variety": "Cayenne",
        "grade": "Grade A",
        "harvest_season": "All year",
        "tags": ["Fresh", "Seasonal"],
        "image": "pepper",
        "is_featured": False,
        "listings": [
            {
                "state": "KD",
                "lga": "Kachia",
                "package_size": "10.000",
                "package_unit": "kg",
                "price": "15000.00",
                "compare_at": None,
                "stock": "300.000",
                "low_stock": "60.000",
                "warehouse": "MAIN",
                "wholesale": [],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Fresh Okra",
        "category": "Okra",
        "unit": "kg",
        "short_description": "Tender fresh okra pods.",
        "description": "Tender fresh okra pods, harvested and packed for market.",
        "variety": "Clemson",
        "grade": "Grade A",
        "harvest_season": "All year",
        "tags": ["Fresh", "Local"],
        "image": "okra",
        "is_featured": False,
        "listings": [
            {
                "state": "BN",
                "lga": "Makurdi",
                "package_size": "20.000",
                "package_unit": "kg",
                "price": "14000.00",
                "compare_at": None,
                "stock": "250.000",
                "low_stock": "50.000",
                "warehouse": "BEN",
                "wholesale": [],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Ripe Plantain",
        "category": "Plantain",
        "unit": "kg",
        "short_description": "Ripe plantain bunches.",
        "description": "Ripe plantain bunches graded for size.",
        "variety": "Agbagba",
        "grade": "Grade A",
        "harvest_season": "All year",
        "tags": ["Fresh", "Local"],
        "image": "plantain",
        "is_featured": False,
        "listings": [
            {
                "state": "ED",
                "lga": "Ovia North-East",
                "package_size": "20.000",
                "package_unit": "kg",
                "price": "16000.00",
                "compare_at": None,
                "stock": "300.000",
                "low_stock": "60.000",
                "warehouse": "LAG",
                "wholesale": [],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Sweet Oranges",
        "category": "Citrus & Mangoes",
        "unit": "kg",
        "short_description": "Juicy sweet oranges.",
        "description": "Fresh, juicy sweet oranges packed for market.",
        "variety": "Valencia",
        "grade": "Grade A",
        "harvest_season": "November - February",
        "tags": ["Fresh", "Seasonal"],
        "image": "orange",
        "is_featured": False,
        "listings": [
            {
                "state": "BN",
                "lga": "Guma",
                "package_size": "50.000",
                "package_unit": "kg",
                "price": "38000.00",
                "compare_at": None,
                "stock": "400.000",
                "low_stock": "80.000",
                "warehouse": "BEN",
                "wholesale": [],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Cocoa Beans",
        "category": "Cocoa",
        "unit": "kg",
        "short_description": "Fermented and dried cocoa beans.",
        "description": "Well-fermented, dried cocoa beans for export and processing.",
        "variety": "Forastero",
        "grade": "Export Grade",
        "harvest_season": "October - January",
        "tags": ["Export Grade", "Dried", "Bulk"],
        "image": "cocoa",
        "is_featured": False,
        "listings": [
            {
                "state": "ON",
                "lga": "Akure South",
                "package_size": "50.000",
                "package_unit": "kg",
                "price": "195000.00",
                "compare_at": None,
                "stock": "350.000",
                "low_stock": "60.000",
                "warehouse": "LAG",
                "wholesale": [("200.000", "190000.00")],
                "origin_verification": "verified",
                "origin_note": "Prepared for export grading.",
            }
        ],
    },
    {
        "name": "Raw Cashew Nuts",
        "category": "Cashew",
        "unit": "kg",
        "short_description": "Raw cashew nuts, export grade.",
        "description": "Clean raw cashew nuts with good kernel out-turn ratio.",
        "variety": "Jumbo",
        "grade": "Export Grade",
        "harvest_season": "February - May",
        "tags": ["Export Grade", "Cleaned", "Bulk"],
        "image": "cashew",
        "is_featured": False,
        "listings": [
            {
                "state": "OY",
                "lga": "Oyo East",
                "package_size": "50.000",
                "package_unit": "kg",
                "price": "150000.00",
                "compare_at": None,
                "stock": "300.000",
                "low_stock": "60.000",
                "warehouse": "LAG",
                "wholesale": [("200.000", "145000.00")],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Dried Split Ginger",
        "category": "Ginger",
        "unit": "kg",
        "short_description": "Dried split ginger for export and processing.",
        "description": "Dried split ginger, cleaned and graded for export.",
        "variety": "Tafin Giwa",
        "grade": "Export Grade",
        "harvest_season": "January - March",
        "tags": ["Dried", "Export Grade", "Bulk"],
        "image": "ginger",
        "is_featured": False,
        "listings": [
            {
                "state": "KD",
                "lga": "Kachia",
                "package_size": "50.000",
                "package_unit": "kg",
                "price": "180000.00",
                "compare_at": None,
                "stock": "250.000",
                "low_stock": "50.000",
                "warehouse": "MAIN",
                "wholesale": [("100.000", "175000.00")],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Crude Palm Oil",
        "category": "Oil Palm",
        "unit": "litre",
        "short_description": "Locally processed crude palm oil.",
        "description": "Crude palm oil processed from fresh fruit bunches.",
        "variety": "Tenera",
        "grade": "Grade A",
        "harvest_season": "All year",
        "tags": ["Local", "Bulk"],
        "image": "palm_oil",
        "is_featured": False,
        "listings": [
            {
                "state": "ED",
                "lga": "Ovia North-East",
                "package_size": "25.000",
                "package_unit": "litre",
                "price": "32000.00",
                "compare_at": None,
                "stock": "400.000",
                "low_stock": "80.000",
                "warehouse": "LAG",
                "wholesale": [("100.000", "31000.00")],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Fresh Eggs (Crate of 30)",
        "category": "Poultry & Eggs",
        "unit": "crate",
        "short_description": "Fresh farm eggs in crates of 30.",
        "description": "Fresh, graded farm eggs supplied in crates of 30.",
        "variety": "Layer",
        "grade": "Grade A",
        "harvest_season": "All year",
        "tags": ["Fresh", "Local"],
        "image": "eggs",
        "is_featured": True,
        "listings": [
            {
                "state": "OG",
                "lga": "Obafemi Owode",
                "package_size": "1.000",
                "package_unit": "crate",
                "price": "5500.00",
                "compare_at": None,
                "stock": "2000.000",
                "low_stock": "200.000",
                "warehouse": "LAG",
                "wholesale": [("50.000", "5300.00"), ("200.000", "5100.00")],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "Live Broiler Chicken",
        "category": "Poultry & Eggs",
        "unit": "piece",
        "short_description": "Healthy live broiler chicken.",
        "description": "Healthy live broiler chicken, raised to weight.",
        "variety": "Arbor Acres",
        "grade": "Grade A",
        "harvest_season": "All year",
        "tags": ["Fresh", "Local"],
        "image": "poultry",
        "is_featured": False,
        "listings": [
            {
                "state": "OY",
                "lga": "Egbeda",
                "package_size": "1.000",
                "package_unit": "piece",
                "price": "9500.00",
                "compare_at": None,
                "stock": "600.000",
                "low_stock": "100.000",
                "warehouse": "LAG",
                "wholesale": [],
                "origin_verification": "verified",
                "origin_note": "",
            }
        ],
    },
    {
        "name": "NPK 20:10:10 Fertiliser",
        "category": "Fertilisers & Soil Amendments",
        "unit": "bag",
        "short_description": "Balanced NPK fertiliser in 50 kg bags.",
        "description": "Balanced NPK 20:10:10 compound fertiliser, 50 kg bags.",
        "variety": "NPK 20:10:10",
        "grade": "Standard",
        "harvest_season": "",
        "tags": ["Bulk"],
        "image": "fertiliser",
        "is_featured": False,
        "listings": [
            {
                "state": "KN",
                "lga": "Kano Municipal",
                "package_size": "50.000",
                "package_unit": "kg",
                "price": "42000.00",
                "compare_at": None,
                "stock": "1000.000",
                "low_stock": "150.000",
                "warehouse": "KAN",
                "wholesale": [("100.000", "41000.00")],
                "origin_verification": "unverified",
                "origin_note": "",
            }
        ],
    },
]

#: (name, code, address, state_code, lga_name)
WAREHOUSES = [
    ("Main Warehouse, Kaduna", "MAIN", "Example Industrial Layout, Zaria", "KD", "Zaria"),
    ("Lagos Distribution Hub", "LAG", "Example Logistics Park, Ikeja", "LA", "Ikeja"),
    ("Benue Produce Store", "BEN", "Example Market Road, Makurdi", "BN", "Makurdi"),
    ("Kano Grain Depot", "KAN", "Example Depot Road, Kano", "KN", "Kano Municipal"),
]

#: Market reference prices: (product_name, state_code_or_empty, year, season, price, unit)
MARKET_REFERENCES = [
    ("Yellow Maize", "", 2025, "Harvest", "38000.00", "kg"),
    ("Yellow Maize", "KD", 2025, "Harvest", "40000.00", "kg"),
    ("Parboiled Rice", "", 2025, "All year", "74000.00", "kg"),
    ("Fresh Tomatoes", "KN", 2025, "Dry season", "16000.00", "crate"),
]


# ---------------------------------------------------------------------------
# Services — consultancy, farming, marketing, storage
# ---------------------------------------------------------------------------

#: (name, summary, description, supports_online, supports_onsite, duration, fee, sort)
CONSULTANCY_SERVICES = [
    (
        "Farm Business Planning",
        "Turn your goals into a workable farm business plan.",
        "A structured planning session covering production, costs, markets and "
        "financing, ending with a written summary.",
        True,
        True,
        90,
        "75000.00",
        0,
    ),
    (
        "Soil Health Assessment",
        "Understand your soil before you invest.",
        "On-site assessment and sampling with practical recommendations for "
        "fertility and soil management.",
        False,
        True,
        120,
        "120000.00",
        10,
    ),
    (
        "Agribusiness Finance Advisory",
        "Get finance-ready with better records and costing.",
        "Review of records, costing and cash flow, with guidance on preparing for finance.",
        True,
        False,
        60,
        "60000.00",
        20,
    ),
    (
        "Poultry Management Advisory",
        "Improve poultry performance and margins.",
        "Advisory on housing, feeding, health and record-keeping for poultry operations.",
        True,
        True,
        75,
        "80000.00",
        30,
    ),
]

#: (name, summary, description, unit_code, fee, sort)
FARMING_SERVICES = [
    (
        "Land Preparation",
        "Clearing, ploughing and harrowing.",
        "Full land preparation for a defined area.",
        "hectare",
        "85000.00",
        0,
    ),
    (
        "Planting Support",
        "Planting and crop establishment.",
        "Planting support to establish your crop evenly.",
        "hectare",
        "45000.00",
        10,
    ),
    (
        "Irrigation Advisory",
        "Water management and scheduling.",
        "Advice on irrigation design and scheduling.",
        "hectare",
        "30000.00",
        20,
    ),
    (
        "Farm Project Management",
        "End-to-end field project management.",
        "Planning, supervision and reporting across a season.",
        "hectare",
        "60000.00",
        30,
    ),
]

#: (name, summary, description, fee, sort)
MARKETING_SERVICES = [
    (
        "Produce Aggregation & Offtake",
        "We aggregate and buy your produce.",
        "Aggregation and offtake of produce at agreed quality and terms.",
        "0.00",
        0,
    ),
    (
        "Market Linkage",
        "Connect with serious buyers.",
        "Introductions and negotiation support with buyers and processors.",
        "0.00",
        10,
    ),
    (
        "Packaging & Brand Advisory",
        "Present your produce for premium markets.",
        "Advice on packaging, labelling and presentation.",
        "0.00",
        20,
    ),
]

PRODUCE_TYPES = [
    "Maize",
    "Rice",
    "Cowpea",
    "Groundnut",
    "Soybean",
    "Sesame Seeds",
    "Ginger",
    "Cocoa",
    "Yam",
    "Onion",
]

#: (name, location, state_code, lga_name, capacity, capacity_unit, produce_types, conditions)
STORAGE_FACILITIES = [
    (
        "Kaduna Dry Storage",
        "Example Industrial Layout, Zaria",
        "KD",
        "Zaria",
        "5000.00",
        "tonne",
        ["Maize", "Rice", "Cowpea", "Groundnut", "Soybean", "Ginger"],
        "Clean, ventilated dry storage with palletised stacking.",
    ),
    (
        "Lagos Temperature-Controlled Store",
        "Example Logistics Park, Ikeja",
        "LA",
        "Ikeja",
        "1200.00",
        "tonne",
        ["Onion", "Yam", "Cocoa", "Sesame Seeds"],
        "Temperature-controlled bays for perishable and high-value produce.",
    ),
]


# ---------------------------------------------------------------------------
# Training Academy
# ---------------------------------------------------------------------------

#: (name, description, sort)
TRAINING_CATEGORIES = [
    ("Crop Production", "Practical crop husbandry and field management.", 0),
    ("Livestock & Poultry", "Animal production and health.", 10),
    ("Agribusiness & Finance", "Records, costing and business management.", 20),
    ("Post-Harvest & Processing", "Handling, storage and value addition.", 30),
    ("Digital Agriculture", "Technology and data in agriculture.", 40),
    ("Export Readiness", "Preparing produce and documentation for export.", 50),
]

#: (email, professional_title, biography, expertise)
INSTRUCTOR_PROFILES = [
    (
        "training@aashinaka.example",
        "Training Manager & Lead Instructor",
        "Designs and delivers practical agricultural training for farmers and "
        "agribusiness professionals.",
        "Crop production, post-harvest handling, training design",
    ),
    (
        "consultant@aashinaka.example",
        "Agribusiness Consultant & Instructor",
        "Advises on farm business planning and finance, and teaches agribusiness modules.",
        "Farm business planning, finance, records",
    ),
]

#: (title, category, short_description, description, objectives, prerequisites,
#:  duration_hours, delivery_mode, image_key, certificate, featured, sort, modules)
COURSES = [
    {
        "title": "Practical Maize Production",
        "category": "Crop Production",
        "short_description": "Plan and run a productive maize season.",
        "description": (
            "A practical course covering variety selection, land preparation, "
            "planting, nutrition, weed control and harvest for maize."
        ),
        "objectives": (
            "Select suitable maize varieties\n"
            "Prepare land and plant correctly\n"
            "Manage nutrition and weeds\n"
            "Harvest and handle grain well"
        ),
        "prerequisites": "",
        "duration_hours": "24.0",
        "delivery_mode": "in_person",
        "image": "maize",
        "certificate": True,
        "featured": True,
        "sort": 0,
        "modules": [
            {
                "title": "Foundations of maize production",
                "lessons": [
                    ("Choosing the right variety", "text", 45),
                    ("Field selection and land preparation", "text", 45),
                ],
            },
            {
                "title": "Managing the season",
                "lessons": [
                    ("Planting and spacing", "text", 40),
                    ("Nutrition and weed control", "text", 50),
                    ("Pest and disease scouting", "activity", 40),
                ],
            },
            {
                "title": "Harvest and handling",
                "lessons": [
                    ("Timing the harvest", "text", 30),
                    ("Drying and storage basics", "text", 40),
                ],
            },
        ],
    },
    {
        "title": "Poultry Farming Essentials",
        "category": "Livestock & Poultry",
        "short_description": "Set up and manage a profitable poultry unit.",
        "description": (
            "Covers housing, brooding, feeding, health and record-keeping for "
            "broiler and layer operations."
        ),
        "objectives": (
            "Plan poultry housing\n"
            "Brood chicks successfully\n"
            "Feed for performance\n"
            "Keep records that guide decisions"
        ),
        "prerequisites": "",
        "duration_hours": "18.0",
        "delivery_mode": "hybrid",
        "image": "poultry",
        "certificate": True,
        "featured": True,
        "sort": 10,
        "modules": [
            {
                "title": "Planning and housing",
                "lessons": [
                    ("Choosing a poultry system", "text", 40),
                    ("Housing and equipment", "text", 45),
                ],
            },
            {
                "title": "Managing the flock",
                "lessons": [
                    ("Brooding and early care", "text", 45),
                    ("Feeding and nutrition", "text", 45),
                    ("Health and biosecurity", "activity", 40),
                ],
            },
        ],
    },
    {
        "title": "Agribusiness Finance & Records",
        "category": "Agribusiness & Finance",
        "short_description": "Turn farm activity into managed numbers.",
        "description": (
            "Learn to keep simple, useful records, cost your production and prepare for finance."
        ),
        "objectives": (
            "Keep essential farm records\n"
            "Cost production accurately\n"
            "Understand cash flow\n"
            "Prepare for finance"
        ),
        "prerequisites": "Basic literacy and numeracy",
        "duration_hours": "12.0",
        "delivery_mode": "online",
        "image": "finance",
        "certificate": True,
        "featured": False,
        "sort": 20,
        "modules": [
            {
                "title": "Records that matter",
                "lessons": [
                    ("What to record and why", "text", 40),
                    ("Simple record templates", "activity", 40),
                ],
            },
            {
                "title": "Costing and finance",
                "lessons": [
                    ("Costing your production", "text", 50),
                    ("Cash flow and finance readiness", "text", 50),
                ],
            },
        ],
    },
    {
        "title": "Post-Harvest Handling & Storage",
        "category": "Post-Harvest & Processing",
        "short_description": "Reduce losses and protect quality.",
        "description": (
            "Practical methods to dry, clean, store and handle produce to reduce "
            "post-harvest losses."
        ),
        "objectives": (
            "Dry and clean produce correctly\n"
            "Choose storage methods\n"
            "Monitor stored produce\n"
            "Reduce losses"
        ),
        "prerequisites": "",
        "duration_hours": "16.0",
        "delivery_mode": "hybrid",
        "image": "storage",
        "certificate": True,
        "featured": False,
        "sort": 30,
        "modules": [
            {
                "title": "Handling after harvest",
                "lessons": [
                    ("Drying and cleaning", "text", 45),
                    ("Sorting and grading", "activity", 40),
                ],
            },
            {
                "title": "Storage and monitoring",
                "lessons": [
                    ("Storage options", "text", 45),
                    ("Monitoring for pests and moisture", "text", 40),
                ],
            },
        ],
    },
    {
        "title": "Export Readiness for Agro Products",
        "category": "Export Readiness",
        "short_description": "Prepare produce and paperwork for export.",
        "description": (
            "An introduction to export markets, quality requirements, "
            "documentation and logistics for agricultural products."
        ),
        "objectives": (
            "Understand export requirements\n"
            "Meet quality and grade standards\n"
            "Prepare documentation\n"
            "Plan logistics"
        ),
        "prerequisites": "",
        "duration_hours": "10.0",
        "delivery_mode": "online",
        "image": "shipping",
        "certificate": True,
        "featured": False,
        "sort": 40,
        "modules": [
            {
                "title": "Markets and requirements",
                "lessons": [
                    ("Choosing a destination", "text", 40),
                    ("Quality and grade standards", "text", 40),
                ],
            },
            {
                "title": "Documentation and logistics",
                "lessons": [
                    ("Required documents", "text", 45),
                    ("Planning the shipment", "text", 35),
                ],
            },
        ],
    },
]

#: (name, address, city, state_code, capacity, facilities)
TRAINING_VENUES = [
    (
        "AA Shinaka Training Centre, Kaduna",
        "Example Learning Way, Zaria",
        "Zaria",
        "KD",
        40,
        "Classroom, demonstration plot, projector, refreshments",
    ),
    (
        "AA Shinaka Learning Hub, Lagos",
        "Example Hub, Ikeja",
        "Ikeja",
        "LA",
        30,
        "Classroom, projector, Wi-Fi, refreshments",
    ),
]

#: (course_title, venue_name_or_empty, delivery_mode, start_offset_days, duration_days,
#:  capacity, min_participants, fee, status)
TRAINING_SESSIONS = [
    (
        "Practical Maize Production",
        "AA Shinaka Training Centre, Kaduna",
        "in_person",
        14,
        4,
        30,
        8,
        "35000.00",
        "enrollment_open",
    ),
    (
        "Poultry Farming Essentials",
        "AA Shinaka Learning Hub, Lagos",
        "hybrid",
        21,
        3,
        25,
        6,
        "40000.00",
        "enrollment_open",
    ),
    ("Agribusiness Finance & Records", "", "online", 10, 5, 60, 10, "15000.00", "enrollment_open"),
    (
        "Post-Harvest Handling & Storage",
        "AA Shinaka Training Centre, Kaduna",
        "hybrid",
        30,
        3,
        25,
        6,
        "30000.00",
        "scheduled",
    ),
]

CERTIFICATE_TEMPLATE = {
    "name": "AA Shinaka Course Completion",
    "title": "Certificate of Completion",
    "body_text": (
        "This is to certify that {student} has completed the course {course} delivered on {date}."
    ),
    "footer_text": "AA Shinaka Training Academy",
}


# ---------------------------------------------------------------------------
# Export trade
# ---------------------------------------------------------------------------

#: (name, code) — added alongside Nigeria for export destinations.
EXPORT_COUNTRIES = [
    ("Ghana", "GH"),
    ("United Kingdom", "GB"),
    ("Netherlands", "NL"),
    ("Germany", "DE"),
    ("China", "CN"),
    ("India", "IN"),
    ("United States", "US"),
    ("United Arab Emirates", "AE"),
]

#: (country code, active, approval, supported_category_names, summary)
EXPORT_DESTINATIONS = [
    (
        "GB",
        True,
        "approved",
        ["Sesame Seeds", "Cashew", "Ginger", "Cocoa"],
        "Buyers require compliant documentation and phytosanitary certification.",
    ),
    (
        "NL",
        True,
        "approved",
        ["Sesame Seeds", "Ginger", "Cocoa"],
        "EU entry via the Netherlands requires EU importer registration and "
        "phytosanitary certification.",
    ),
    (
        "CN",
        True,
        "approved",
        ["Sesame Seeds", "Cashew", "Cocoa"],
        "China requires quality and phytosanitary certification for oilseeds and nuts.",
    ),
    (
        "AE",
        True,
        "approved",
        ["Sesame Seeds", "Cashew", "Ginger"],
        "Gulf markets require grading and certification.",
    ),
    (
        "GH",
        True,
        "approved",
        ["Sesame Seeds", "Cashew"],
        "Regional market with simpler documentation requirements.",
    ),
    ("DE", False, "pending", [], "Approval under review."),
    ("IN", False, "pending", [], "Approval under review."),
    ("US", False, "pending", [], "Approval under review."),
]

#: (code, name, description, requires_expiry, is_official, sort)
EXPORT_DOCUMENT_TYPES = [
    ("CO", "Certificate of Origin", "Certifies the origin of goods.", False, True, 0),
    ("PHYTO", "Phytosanitary Certificate", "Certifies plant health status.", True, True, 10),
    ("INV", "Commercial Invoice", "Declares the commercial value of goods.", False, False, 20),
    ("PACK", "Packing List", "Lists contents, quantities and weights.", False, False, 30),
    (
        "BL",
        "Bill of Lading / Airway Bill",
        "Transport document issued by the carrier.",
        False,
        True,
        40,
    ),
    ("FUM", "Fumigation Certificate", "Certifies fumigation treatment.", True, True, 50),
    ("QC", "Quality & Grade Certificate", "Certifies quality and grade.", False, True, 60),
]

#: (destination_country_code, title, requirement_type, document_code, mandatory, description)
EXPORT_REQUIREMENTS = [
    (
        "GB",
        "Phytosanitary certificate",
        "phytosanitary",
        "PHYTO",
        True,
        "Official plant health certificate.",
    ),
    ("GB", "Certificate of origin", "documentation", "CO", True, "Certifies the goods' origin."),
    (
        "GB",
        "Commercial invoice and packing list",
        "documentation",
        "INV",
        True,
        "Complete commercial documentation.",
    ),
    (
        "NL",
        "EU importer registration",
        "certification",
        "",
        True,
        "An EU-registered importer must be nominated.",
    ),
    (
        "NL",
        "Phytosanitary certificate",
        "phytosanitary",
        "PHYTO",
        True,
        "Official plant health certificate.",
    ),
    ("CN", "Quality certificate", "certification", "QC", True, "Quality and grade certification."),
    (
        "CN",
        "Phytosanitary certificate",
        "phytosanitary",
        "PHYTO",
        True,
        "Official plant health certificate.",
    ),
    (
        "AE",
        "Fumigation certificate",
        "quarantine",
        "FUM",
        True,
        "Fumigation treatment certificate.",
    ),
    ("AE", "Certificate of origin", "documentation", "CO", True, "Certifies the goods' origin."),
    ("GH", "Certificate of origin", "documentation", "CO", True, "Certifies the goods' origin."),
]

#: (destination_country_code, restriction_type, description, category_name_or_empty)
EXPORT_RESTRICTIONS = [
    (
        "NL",
        "licence_required",
        "Raw agricultural imports require an EU-registered importer and full "
        "compliance documentation.",
        "",
    ),
    (
        "CN",
        "quota",
        "Import volumes for some oilseeds may be subject to quota arrangements.",
        "Sesame Seeds",
    ),
]

#: product_name -> export profile tuple
#: (grade, min_qty, min_unit, availability, require_inspection, destinations, notes)
EXPORT_PRODUCT_PROFILES = {
    "Sesame Seeds": (
        "Export Grade (99% purity)",
        "20.000",
        "tonne",
        "available",
        True,
        ["GB", "NL", "CN", "AE", "GH"],
        "Cleaned and graded white sesame for export.",
    ),
    "Raw Cashew Nuts": (
        "Export Grade (KOR 46-48 lbs)",
        "20.000",
        "tonne",
        "seasonal",
        True,
        ["GB", "CN", "AE", "GH"],
        "Raw cashew nuts graded by kernel out-turn ratio.",
    ),
    "Dried Split Ginger": (
        "Export Grade",
        "10.000",
        "tonne",
        "available",
        True,
        ["GB", "NL", "AE"],
        "Dried split ginger prepared for export.",
    ),
    "Cocoa Beans": (
        "Export Grade (well fermented)",
        "20.000",
        "tonne",
        "seasonal",
        True,
        ["GB", "NL", "CN"],
        "Fermented and dried cocoa beans.",
    ),
}

#: (name, code, contact_name, contact_email, contact_phone, tracking_template)
LOGISTICS_PROVIDERS = [
    (
        "Sahara Freight Services (example)",
        "SAHARA",
        "Example Contact",
        "ops@example.invalid",
        "08000000001",
        "",
    ),
    (
        "Bluewave Logistics (example)",
        "BLUEWAVE",
        "Example Contact",
        "ops@example.invalid",
        "08000000002",
        "https://example.invalid/track/{tracking}",
    ),
    (
        "Portlink Clearing & Forwarding (example)",
        "PORTLINK",
        "",
        "",
        "",
        "",
    ),
]


# ---------------------------------------------------------------------------
# Orders — shipping configuration
# ---------------------------------------------------------------------------

#: (name, code, description, state_codes)
SHIPPING_ZONES = [
    ("Lagos", "LAGOS", "Deliveries within Lagos State.", ["LA"]),
    (
        "South West",
        "SOUTH_WEST",
        "Ogun, Oyo, Osun, Ondo and Ekiti states.",
        ["OG", "OY", "OS", "ON", "EK"],
    ),
    (
        "South East",
        "SOUTH_EAST",
        "Abia, Anambra, Ebonyi, Enugu and Imo states.",
        ["AB", "AN", "EB", "EN", "IM"],
    ),
    (
        "South South",
        "SOUTH_SOUTH",
        "Akwa Ibom, Bayelsa, Cross River, Delta, Edo and Rivers states.",
        ["AK", "BY", "CR", "DE", "ED", "RI"],
    ),
    (
        "North Central",
        "NORTH_CENTRAL",
        "Benue, Kogi, Kwara, Nasarawa, Niger, Plateau and the FCT.",
        ["BN", "KO", "KW", "NA", "NI", "PL", "FC"],
    ),
    (
        "North West",
        "NORTH_WEST",
        "Jigawa, Kaduna, Kano, Katsina, Kebbi, Sokoto and Zamfara states.",
        ["JI", "KD", "KN", "KT", "KE", "SO", "ZA"],
    ),
    (
        "North East",
        "NORTH_EAST",
        "Adamawa, Bauchi, Borno, Gombe, Taraba and Yobe states.",
        ["AD", "BA", "BO", "GO", "TA", "YO"],
    ),
]

#: (name, code, description, sort)
SHIPPING_METHODS = [
    ("Warehouse Pickup", "PICKUP", "Collect from a designated warehouse.", 0),
    ("Standard Delivery", "STANDARD", "Delivery within the estimated window.", 10),
    ("Express Delivery", "EXPRESS", "Prioritised delivery where available.", 20),
]

#: Methods offered per zone (pickup is nationwide).
SHIPPING_RATE_METHODS = ["PICKUP", "STANDARD", "EXPRESS"]

#: (zone_code, method_code, fee, free_over)
SHIPPING_RATES = [
    ("LAGOS", "PICKUP", "0.00", None),
    ("LAGOS", "STANDARD", "2500.00", "150000.00"),
    ("LAGOS", "EXPRESS", "4500.00", None),
    ("SOUTH_WEST", "STANDARD", "4000.00", "200000.00"),
    ("SOUTH_WEST", "EXPRESS", "6500.00", None),
    ("SOUTH_EAST", "STANDARD", "5000.00", "250000.00"),
    ("SOUTH_EAST", "EXPRESS", "7500.00", None),
    ("SOUTH_SOUTH", "STANDARD", "5000.00", "250000.00"),
    ("SOUTH_SOUTH", "EXPRESS", "7500.00", None),
    ("NORTH_CENTRAL", "STANDARD", "4500.00", "200000.00"),
    ("NORTH_CENTRAL", "EXPRESS", "7000.00", None),
    ("NORTH_WEST", "STANDARD", "5500.00", "250000.00"),
    ("NORTH_WEST", "EXPRESS", "8000.00", None),
    ("NORTH_EAST", "STANDARD", "6500.00", "300000.00"),
    ("NORTH_EAST", "EXPRESS", "9500.00", None),
]


# ---------------------------------------------------------------------------
# Analytics — recurring report configuration (always-on reference data)
# ---------------------------------------------------------------------------

#: (name, report_key, frequency, export_format). Keys are allow-listed in
#: ``apps.analytics.reports``; non-financial keys are used so any staff member
#: with the reporting capability may receive them.
SCHEDULED_REPORTS = [
    ("Weekly inventory stock", "inventory_stock", "weekly", "csv"),
    ("Monthly service requests", "services_requests", "monthly", "csv"),
    ("Weekly low-stock watchlist", "inventory_low_stock", "weekly", "csv"),
]


# ---------------------------------------------------------------------------
# Catalogue — representative product variants (always-on reference data)
# ---------------------------------------------------------------------------

#: Variant labels applied to active listings that have none yet.
PRODUCT_VARIANT_LABELS = ["Standard", "Premium"]
PRODUCT_VARIANT_LIMIT = 8


# ---------------------------------------------------------------------------
# CMS — contact enquiries (demo records)
# ---------------------------------------------------------------------------

#: (name, email, phone, division, subject, message)
CONTACT_ENQUIRIES = [
    (
        "Amaka Obi",
        "amaka.obi@example.invalid",
        "08040000001",
        "storage",
        "Storage for 20 tonnes of rice",
        "I would like a quote to store 20 tonnes of rice for three months.",
    ),
    (
        "Sani Bello",
        "sani.bello@example.invalid",
        "08040000002",
        "farming_services",
        "Land preparation for two hectares",
        "Please contact me about land preparation for a two-hectare plot.",
    ),
    (
        "Grace Umeh",
        "grace.umeh@example.invalid",
        "08040000003",
        "training",
        "Training for a cooperative group",
        "Our cooperative would like training for 15 members on post-harvest handling.",
    ),
]


# ---------------------------------------------------------------------------
# Support — demo tickets
# ---------------------------------------------------------------------------

#: (customer_index, subject, category, priority, message)
SUPPORT_TICKETS = [
    (
        0,
        "Where is my order?",
        "product_order",
        "normal",
        "My order has not arrived yet. Please share the delivery status.",
    ),
    (
        1,
        "Certificate name correction",
        "training",
        "low",
        "My certificate shows a misspelt name. Please advise on correcting it.",
    ),
    (
        2,
        "Storage inspection request",
        "storage",
        "high",
        "Please arrange an inspection of my stored produce this week.",
    ),
]


# ---------------------------------------------------------------------------
# Notifications — demo inbox items
# ---------------------------------------------------------------------------

#: (category, title, message, url)
DEMO_NOTIFICATIONS = [
    (
        "orders",
        "Your order is on the way",
        "Track your latest order from your customer portal.",
        "/portal/orders/",
    ),
    (
        "training",
        "New course material",
        "Fresh lessons were added to a course you are enrolled in.",
        "/portal/training/",
    ),
    (
        "support",
        "We replied to your ticket",
        "A support agent has responded to your request.",
        "/portal/support/",
    ),
    (
        "payments",
        "Payment received",
        "A payment on your account has been verified.",
        "/portal/payments/",
    ),
]
