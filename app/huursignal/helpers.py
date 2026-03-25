WONING_TYPES = ["kamer", "appartement", "studio", "anti-kraak", "studentenwoning", "gemeubileerd"]


def fmt_prijs(p):
    if not p:
        return "?"
    return "\u20ac\u00a0" + f"{p:,}".replace(",", ".")
