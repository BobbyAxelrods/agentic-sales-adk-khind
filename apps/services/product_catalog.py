"""Deterministic WhatsApp product-list payloads for KHIND."""

from apps.prompts.khind_prompts import PRODUCT_MEDIA_FOLDERS


PRODUCT_CATALOG = (
    {
        "title": "Peti Sejuk",
        "rows": (
            ("chillmaster_592l", "KHIND ChillMaster 592L", "Keluarga besar, Smart Convertible"),
            ("chillmaster_lite_480l", "ChillMaster Lite 480L", "2 pintu, Inverter 5 Bintang"),
            ("chillmaster_x_466l", "ChillMaster X 466L", "4 pintu, rekaan premium"),
        ),
    },
    {
        "title": "Mesin Basuh & Pengering",
        "rows": (
            ("washer_dryer_11_7", "Washer Dryer 11KG/7KG", "Basuh dan kering dalam satu mesin"),
            ("front_load_9kg", "Front Load Washer 9KG", "Basuh sahaja, jimat air"),
            ("ecowash_top_15kg", "EcoWash Top Load 15KG", "Sesuai untuk toto dan comforter"),
            ("drymaster_9kg", "DryMaster Heat Pump 9KG", "Pengering cekap tenaga"),
        ),
    },
    {
        "title": "Penyaman Udara",
        "rows": (
            ("aircond_kool_series", "KHIND KOOL Series Aircond", "1.0HP, 1.5HP, 2.0HP Inverter"),
        ),
    },
)


def get_product_catalog() -> dict:
    """Return the WhatsApp interactive-list payload for KHIND products."""
    sections = []
    for category in PRODUCT_CATALOG:
        sections.append(
            {
                "title": category["title"][:24],
                "rows": [
                    {
                        "id": f"prod_{product_key}",
                        "title": title[:24],
                        "description": description[:72],
                    }
                    for product_key, title, description in category["rows"]
                ],
            }
        )

    return {
        "type": "list",
        "body_text": "Pilih produk yang cik/tuan berminat:",
        "button_text": "Lihat Produk",
        "sections": sections,
    }


def resolve_product_selection(row_id: str) -> str | None:
    """Convert a WhatsApp product-list row ID into a valid KHIND product key."""
    normalized_id = (row_id or "").strip().lower()
    if not normalized_id.startswith("prod_"):
        return None

    product_key = normalized_id.removeprefix("prod_")
    return product_key if product_key in PRODUCT_MEDIA_FOLDERS else None