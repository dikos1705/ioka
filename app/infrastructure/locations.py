LOCATIONS = [
    {"iata": "TAS", "city": "Tashkent", "airport": "Tashkent International Airport", "country": "Uzbekistan"},
    {
        "iata": "SKD",
        "city": "Samarkand",
        "airport": "Samarkand International Airport",
        "country": "Uzbekistan",
    },
    {"iata": "IST", "city": "Istanbul", "airport": "Istanbul Airport", "country": "Turkiye"},
    {"iata": "ALA", "city": "Almaty", "airport": "Almaty International Airport", "country": "Kazakhstan"},
    {
        "iata": "NQZ",
        "city": "Astana",
        "airport": "Nursultan Nazarbayev International Airport",
        "country": "Kazakhstan",
    },
    {
        "iata": "DXB",
        "city": "Dubai",
        "airport": "Dubai International Airport",
        "country": "United Arab Emirates",
    },
    {"iata": "FRA", "city": "Frankfurt", "airport": "Frankfurt Airport", "country": "Germany"},
    {"iata": "LHR", "city": "London", "airport": "Heathrow Airport", "country": "United Kingdom"},
]


def search_locations(query: str) -> list[dict[str, str]]:
    normalized = query.strip().casefold()
    if not normalized:
        return LOCATIONS[:10]
    return [item for item in LOCATIONS if normalized in " ".join(item.values()).casefold()][:20]
