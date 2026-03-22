"""
MCP server for WSDOT Washington State Ferries data.

Provides live ferry schedules, fares, crossing times, and door-to-door
travel time estimates using the WSDOT Ferries API and Google Maps.
"""

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from fastmcp import FastMCP

from config import WSDOT_API_KEY, GOOGLE_MAPS_API_KEY
from utilities import haversine, parse_datetime, to_epoch_seconds

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("wsdot-ferry")

# Terminal name → WSDOT terminal ID
TERMINAL_IDS: dict[str, int] = {
    "seattle": 7,
    "bainbridge island": 3,
    "southworth": 20,
    "fauntleroy": 9,
    "edmonds": 8,
    "kingston": 12,
    "bremerton": 4,
    "point defiance": 16,
    "tahlequah": 21,
    "anacortes": 1,
    "friday harbor": 2,
    "orcas": 5,
    "shaw": 6,
    "lopez": 11,
    "sidney bc": 13,
}

# Terminal name → (lat, lng) for distance calculations
TERMINAL_LOCATIONS: dict[str, tuple[float, float]] = {
    "Anacortes":        (48.50223,  -122.67919),
    "Bainbridge Island": (47.62309, -122.51081),
    "Bremerton":        (47.56212,  -122.62392),
    "Edmonds":          (47.81044,  -122.38296),
    "Fauntleroy":       (47.52320,  -122.39548),
    "Kingston":         (47.79630,  -122.49645),
    "Seattle":          (47.60270,  -122.33852),
    "Southworth":       (47.51204,  -122.49749),
    "Tahlequah":        (47.33150,  -122.50760),
    "Point Defiance":   (47.30540,  -122.51260),
}

# Maps each Kitsap-side terminal to its correct mainland/destination terminal
TERMINAL_PAIRS: dict[str, str] = {
    "southworth": "fauntleroy",
    "bainbridge island": "seattle",
    "bremerton": "seattle",
    "kingston": "edmonds",
    "tahlequah": "point defiance",
    "friday harbor": "anacortes",
    "orcas": "anacortes",
    "shaw": "anacortes",
    "lopez": "anacortes",
}

# Approximate crossing times in minutes per route (WSDOT API doesn't return this as a field)
CROSSING_TIMES: dict[frozenset, int] = {
    frozenset({"seattle", "bainbridge island"}): 35,
    frozenset({"seattle", "bremerton"}): 60,
    frozenset({"edmonds", "kingston"}): 30,
    frozenset({"fauntleroy", "southworth"}): 30,
    frozenset({"fauntleroy", "vashon"}): 15,
    frozenset({"point defiance", "tahlequah"}): 15,
}

WSDOT_SCHEDULE_BASE = "https://www.wsdot.wa.gov/Ferries/API/Schedule/rest"
WSDOT_FARES_BASE = "https://www.wsdot.wa.gov/ferries/api/fares/rest"
GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
MILEAGE_RATE = 0.70  # IRS standard rate $/mile


# ---------------------------------------------------------------------------
# Internal helpers — these contain the actual logic.
# Tool-decorated functions and estimate_total_travel both call these.
# (FastMCP wraps @mcp.tool functions into FunctionTool objects that aren't
# directly callable from other Python functions.)
# ---------------------------------------------------------------------------

def _wsdot_params() -> dict:
    return {"apiaccesscode": WSDOT_API_KEY}


def _terminal_id(name: str) -> Optional[int]:
    return TERMINAL_IDS.get(name.lower().strip())


def _crossing_time(dep: str, arr: str) -> Optional[int]:
    key = frozenset({dep.lower().strip(), arr.lower().strip()})
    return CROSSING_TIMES.get(key)


def _parse_wsdot_time(wsdot_str: str) -> Optional[datetime]:
    """Parse WSDOT /Date(milliseconds+offset)/ format."""
    match = re.match(r"/Date\((\d+)([+-]\d{4})?\)/", wsdot_str or "")
    if not match:
        return None
    ms = int(match.group(1))
    offset_str = match.group(2) or "+0000"
    sign = 1 if offset_str[0] == "+" else -1
    hours, minutes = int(offset_str[1:3]), int(offset_str[3:5])
    tz = timezone(timedelta(hours=sign * hours, minutes=sign * minutes))
    return datetime.fromtimestamp(ms / 1000, tz=tz)


def _fmt_time(dt: Optional[datetime]) -> str:
    if dt is None:
        return "unknown"
    return dt.strftime("%-I:%M %p")


def _find_nearest_terminals(address: str, max_results: int = 3) -> dict:
    geo_resp = requests.get(
        GOOGLE_GEOCODE_URL,
        params={"address": address, "key": GOOGLE_MAPS_API_KEY},
        timeout=10,
    )
    geo_resp.raise_for_status()
    results = geo_resp.json().get("results", [])
    if not results:
        return {"terminals": [], "error": f"Could not geocode: {address}"}

    loc = results[0]["geometry"]["location"]
    addr_lat, addr_lng = loc["lat"], loc["lng"]

    terminals = []
    for name, (lat, lng) in TERMINAL_LOCATIONS.items():
        dist = haversine(addr_lat, addr_lng, lat, lng)
        terminals.append({
            "name": name,
            "lat": lat,
            "lng": lng,
            "distance_km": round(dist, 2),
        })

    terminals.sort(key=lambda x: x["distance_km"])
    return {"terminals": terminals[:max_results]}


def _get_ferry_schedule(trip_date: str, departing_terminal: str, arriving_terminal: str) -> dict:
    dep_id = _terminal_id(departing_terminal)
    arr_id = _terminal_id(arriving_terminal)

    if dep_id is None:
        return {"error": f"Unknown terminal: '{departing_terminal}'", "sailings": []}
    if arr_id is None:
        return {"error": f"Unknown terminal: '{arriving_terminal}'", "sailings": []}

    url = f"{WSDOT_SCHEDULE_BASE}/schedule/{trip_date}/{dep_id}/{arr_id}"
    resp = requests.get(url, params=_wsdot_params(), timeout=10)

    if resp.status_code == 400:
        return {
            "error": f"No ferry route from {departing_terminal} to {arriving_terminal}",
            "sailings": [],
        }
    resp.raise_for_status()
    data = resp.json()

    # Response structure: data["TerminalCombos"][0]["Times"]
    sailings = []
    combos = data.get("TerminalCombos", [])
    times = combos[0].get("Times", []) if combos else []

    for dep in times:
        raw_time = dep.get("DepartingTime")
        dt = _parse_wsdot_time(raw_time) if raw_time else None
        annotations = [
            combos[0]["Annotations"][i]
            for i in dep.get("AnnotationIndexes", [])
            if i < len(combos[0].get("Annotations", []))
        ] if combos else []
        sailings.append({
            "departure_time": _fmt_time(dt),
            "departure_iso": dt.isoformat() if dt else None,
            "vessel": dep.get("VesselName", ""),
            "annotations": annotations,
        })

    return {
        "route": f"{departing_terminal} → {arriving_terminal}",
        "date": trip_date,
        "crossing_time_minutes": _crossing_time(departing_terminal, arriving_terminal),
        "sailings": sailings,
    }


def _get_drive_time(
    origin: str,
    destination: str,
    departure_time: Optional[str] = None,
    arrival_time: Optional[str] = None,
) -> dict:
    params: dict = {
        "origin": origin,
        "destination": destination,
        "key": GOOGLE_MAPS_API_KEY,
    }
    dep = parse_datetime(departure_time)
    arr = parse_datetime(arrival_time)
    if arr:
        params["arrival_time"] = to_epoch_seconds(arr)
    elif dep:
        params["departure_time"] = to_epoch_seconds(dep)

    resp = requests.get(GOOGLE_DIRECTIONS_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    try:
        leg = data["routes"][0]["legs"][0]
        minutes = int(leg["duration"]["value"] // 60)
        distance_miles = leg["distance"]["value"] * 0.000621371
        mileage_cost = distance_miles * MILEAGE_RATE

        result = {
            "drive_minutes": minutes,
            "distance_miles": round(distance_miles, 2),
            "distance_text": leg["distance"]["text"],
            "mileage_cost": round(mileage_cost, 2),
            "cost_summary": (
                f"${mileage_cost:.2f} ({distance_miles:.1f} mi @ ${MILEAGE_RATE}/mi)"
            ),
        }
        if "duration_in_traffic" in leg:
            result["drive_minutes_with_traffic"] = int(
                leg["duration_in_traffic"]["value"] // 60
            )
        return result
    except (KeyError, IndexError):
        raise Exception(f"Google Maps returned no route: {data.get('status')}")


# ---------------------------------------------------------------------------
# Tools — thin wrappers that call the private helpers above

@mcp.tool(
    name="find_nearest_terminals",
    description=(
        "Geocode an address and return the closest Washington State Ferry terminals, "
        "sorted by distance."
    ),
)
def find_nearest_terminals(address: str, max_results: int = 3) -> dict:
    """
    Args:
        address: Street address or city name.
        max_results: Number of terminals to return (default 3).
    """
    return _find_nearest_terminals(address, max_results)


@mcp.tool(
    name="get_ferry_schedule",
    description=(
        "Get scheduled sailings for a ferry route on a specific date. "
        "Returns departure times, crossing duration, and vessel names."
    ),
)
def get_ferry_schedule(
    trip_date: str,
    departing_terminal: str,
    arriving_terminal: str,
) -> dict:
    """
    Args:
        trip_date: Date in YYYY-MM-DD format.
        departing_terminal: Terminal name (e.g. 'Bainbridge Island', 'Seattle').
        arriving_terminal: Terminal name.
    """
    return _get_ferry_schedule(trip_date, departing_terminal, arriving_terminal)


@mcp.tool(
    name="get_todays_sailings",
    description=(
        "Get today's ferry sailings for a route, optionally filtered to only "
        "remaining (future) departures. Useful for real-time commute planning."
    ),
)
def get_todays_sailings(
    departing_terminal: str,
    arriving_terminal: str,
    remaining_only: bool = True,
) -> dict:
    """
    Args:
        departing_terminal: Terminal name.
        arriving_terminal: Terminal name.
        remaining_only: If True, only return departures that haven't left yet.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    result = _get_ferry_schedule(today, departing_terminal, arriving_terminal)

    if remaining_only and "sailings" in result:
        now = datetime.now(tz=timezone.utc).astimezone()
        result["sailings"] = [
            s for s in result["sailings"]
            if s.get("departure_iso") and datetime.fromisoformat(s["departure_iso"]) > now
        ]
        result["filter"] = "remaining departures only"

    return result


def _get_ferry_fare(
    trip_date: str,
    departing_terminal: str,
    arriving_terminal: str,
    travel_mode: str = "drive",
    vehicle_size: str = "standard",
) -> dict:
    dep_id = _terminal_id(departing_terminal)
    arr_id = _terminal_id(arriving_terminal)

    if dep_id is None:
        return {"error": f"Unknown terminal: '{departing_terminal}'"}
    if arr_id is None:
        return {"error": f"Unknown terminal: '{arriving_terminal}'"}

    url = f"{WSDOT_FARES_BASE}/farelineitems/{trip_date}/{dep_id}/{arr_id}/false"
    try:
        resp = requests.get(url, params=_wsdot_params(), timeout=10)
        if resp.status_code == 400:
            return {"error": f"No fare data for {departing_terminal} → {arriving_terminal}"}
        resp.raise_for_status()
        fare_data = resp.json()
    except requests.RequestException as e:
        return {"error": str(e)}

    recommended = None
    fare_description = ""

    if isinstance(fare_data, list):
        for item in fare_data:
            desc = item.get("FareLineItem", "").lower()
            if travel_mode == "walk":
                if "passenger" in desc or ("adult" in desc and "vehicle" not in desc):
                    recommended = item
                    fare_description = "Walk-on passenger"
                    break
            else:
                if vehicle_size == "motorcycle" and "motorcycle" in desc:
                    recommended = item
                    fare_description = "Motorcycle"
                    break
                elif vehicle_size == "small" and ("under 14" in desc or "less than 168" in desc):
                    recommended = item
                    fare_description = "Small vehicle"
                    break
                elif vehicle_size == "standard" and ("under 22" in desc or "standard veh" in desc):
                    recommended = item
                    fare_description = "Standard vehicle"
                    break

        if not recommended and fare_data:
            for item in fare_data:
                desc = item.get("FareLineItem", "").lower()
                if travel_mode == "walk" and "adult" in desc and "vehicle" not in desc:
                    recommended = item
                    fare_description = "Passenger (default)"
                    break
                elif travel_mode == "drive" and ("under 22" in desc or "standard veh" in desc):
                    recommended = item
                    fare_description = "Standard vehicle (default)"
                    break

    fare_amount = recommended.get("Amount", 0) if recommended else 0
    fare_name = recommended.get("FareLineItem", "No fare found") if recommended else "No fare found"

    if fare_amount > 0:
        cost_summary = f"${fare_amount} — {fare_name}"
    else:
        mainland_terminals = {"seattle", "edmonds", "mukilteo", "anacortes"}
        if departing_terminal.lower().strip() in mainland_terminals:
            cost_summary = "FREE (mainland → island direction)"
        else:
            cost_summary = "FREE"

    return {
        "route": f"{departing_terminal} → {arriving_terminal}",
        "trip_date": trip_date,
        "travel_mode": travel_mode,
        "fare_amount": fare_amount,
        "fare_name": fare_name,
        "fare_description": fare_description,
        "cost_summary": cost_summary,
    }


@mcp.tool(
    name="get_ferry_fare",
    description=(
        "Return the ferry fare for a route and travel mode using the WSDOT Fares API. "
        "Note: eastbound (to mainland) = paid, westbound (to islands) = free."
    ),
)
def get_ferry_fare(
    trip_date: str,
    departing_terminal: str,
    arriving_terminal: str,
    travel_mode: str = "drive",
    vehicle_size: str = "standard",
) -> dict:
    """
    Args:
        trip_date: YYYY-MM-DD.
        departing_terminal: Terminal name.
        arriving_terminal: Terminal name.
        travel_mode: 'walk' (passenger) or 'drive' (vehicle + driver).
        vehicle_size: 'standard' (under 22'), 'small' (under 14'), 'motorcycle'.
    """
    return _get_ferry_fare(trip_date, departing_terminal, arriving_terminal, travel_mode, vehicle_size)


@mcp.tool(
    name="get_drive_time",
    description=(
        "Get driving time and mileage cost between two locations using Google Maps. "
        f"Mileage calculated at ${MILEAGE_RATE}/mile (IRS standard rate)."
    ),
)
def get_drive_time(
    origin: str,
    destination: str,
    departure_time: Optional[str] = None,
    arrival_time: Optional[str] = None,
) -> dict:
    """
    Args:
        origin: Street address or place name.
        destination: Street address or place name.
        departure_time: ISO 8601 datetime (for traffic-aware routing).
        arrival_time: ISO 8601 datetime (alternative to departure_time).
    """
    return _get_drive_time(origin, destination, departure_time, arrival_time)


@mcp.tool(
    name="estimate_total_travel",
    description=(
        "Estimate total door-to-door travel time for a Kitsap commute. "
        "Finds the best ferry option by combining: drive to terminal + crossing + drive to destination. "
        "Also returns a driving-only estimate."
    ),
)
def estimate_total_travel(
    origin: str,
    destination: str,
    event_time: str,
) -> dict:
    """
    Args:
        origin: Your starting address.
        destination: Your destination address.
        event_time: ISO 8601 datetime of when you need to arrive.

    Returns driving-only and up to 3 ferry options with full breakdown.
    """
    # 1. Driving-only baseline
    try:
        drive_only = _get_drive_time(origin, destination, arrival_time=event_time)
        drive_only_minutes = drive_only.get("drive_minutes_with_traffic") or drive_only["drive_minutes"]
    except Exception as e:
        drive_only = {"error": str(e)}
        drive_only_minutes = None

    # 2. Find nearby terminals
    terminals_result = _find_nearest_terminals(origin, max_results=3)
    nearby = terminals_result.get("terminals", [])

    event_dt = parse_datetime(event_time)
    trip_date = event_dt.strftime("%Y-%m-%d") if event_dt else datetime.now().strftime("%Y-%m-%d")

    ferry_options = []

    for terminal in nearby:
        dep_terminal = terminal["name"]

        # Determine arrival terminal from TERMINAL_PAIRS
        arr_terminal = TERMINAL_PAIRS.get(dep_terminal.lower().strip())
        if arr_terminal is None:
            continue
        arr_terminal = arr_terminal.title()

        # Drive to departure terminal
        try:
            drive_to = _get_drive_time(origin, f"{dep_terminal} Ferry Terminal, WA")
            drive_to_min = drive_to.get("drive_minutes_with_traffic") or drive_to["drive_minutes"]
        except Exception:
            continue

        # Get schedule
        schedule = _get_ferry_schedule(trip_date, dep_terminal, arr_terminal)
        if schedule.get("error") or not schedule.get("sailings"):
            continue

        crossing_min = schedule.get("crossing_time_minutes") or 0

        # Drive from arrival terminal to destination
        try:
            drive_from = _get_drive_time(f"{arr_terminal} Ferry Terminal, WA", destination)
            drive_from_min = drive_from.get("drive_minutes_with_traffic") or drive_from["drive_minutes"]
        except Exception:
            drive_from_min = 0

        # Find sailings that get us there on time (15-min buffer)
        viable_sailings = []
        if event_dt:
            for sailing in schedule["sailings"]:
                iso = sailing.get("departure_iso")
                if not iso:
                    continue
                dep_dt = datetime.fromisoformat(iso)
                arrive_at_dest = dep_dt + timedelta(minutes=crossing_min + drive_from_min)
                buffer = event_dt.replace(tzinfo=dep_dt.tzinfo) - arrive_at_dest
                if buffer.total_seconds() >= 15 * 60:
                    viable_sailings.append({
                        **sailing,
                        "arrive_at_destination": arrive_at_dest.strftime("%-I:%M %p"),
                        "buffer_minutes": int(buffer.total_seconds() // 60),
                        "total_travel_minutes": drive_to_min + crossing_min + drive_from_min,
                    })

        ferry_options.append({
            "departure_terminal": dep_terminal,
            "arrival_terminal": arr_terminal,
            "drive_to_terminal_minutes": drive_to_min,
            "crossing_time_minutes": crossing_min,
            "drive_from_terminal_minutes": drive_from_min,
            "total_transit_minutes": drive_to_min + crossing_min + drive_from_min,
            "viable_sailings": viable_sailings[:5],
            "terminal_distance_km": terminal["distance_km"],
        })

    return {
        "origin": origin,
        "destination": destination,
        "event_time": event_time,
        "driving_only": drive_only,
        "ferry_options": ferry_options,
    }


def _generate_expense_estimate(
    origin: str,
    destination: str,
    trip_date: str,
    travel_mode: str = "drive",
) -> dict:
    """
    Args:
        origin: Starting address.
        destination: Destination address.
        trip_date: Date of travel in YYYY-MM-DD format.
        travel_mode: 'drive' (vehicle + driver) or 'walk' (passenger only).

    Returns a travel_plan dict with all route options and costs, including
    a recommended_route based on lowest total cost.
    """
    routes = []

    # --- Ferry options ---
    nearby = _find_nearest_terminals(origin, max_results=3).get("terminals", [])

    for terminal in nearby:
        dep_terminal = terminal["name"]

        # Look up the correct arrival terminal for this departure terminal
        arr_terminal = TERMINAL_PAIRS.get(dep_terminal.lower().strip())
        if arr_terminal is None:
            continue  # terminal doesn't have a known outbound route

        arr_terminal = arr_terminal.title()  # normalize casing

        schedule = _get_ferry_schedule(trip_date, dep_terminal, arr_terminal)
        if schedule.get("error") or not schedule.get("sailings"):
            continue

        try:
            drive_to = _get_drive_time(origin, f"{dep_terminal} Ferry Terminal, WA")
            drive_from = _get_drive_time(f"{arr_terminal} Ferry Terminal, WA", destination)
        except Exception:
            continue

        fare_result = _get_ferry_fare(trip_date, dep_terminal, arr_terminal, travel_mode)

        drive_to_min = drive_to.get("drive_minutes_with_traffic") or drive_to["drive_minutes"]
        drive_from_min = drive_from.get("drive_minutes_with_traffic") or drive_from["drive_minutes"]
        crossing_min = schedule.get("crossing_time_minutes") or 0
        ferry_fare = fare_result.get("fare_amount", 0)
        mileage_cost = round(
            drive_to["mileage_cost"] + drive_from["mileage_cost"], 2
        )
        total_cost = round(ferry_fare + mileage_cost, 2)

        routes.append({
            "type": "ferry",
            "departure_terminal": dep_terminal,
            "arrival_terminal": arr_terminal,
            "drive_to_terminal_minutes": drive_to_min,
            "crossing_time_minutes": crossing_min,
            "drive_from_terminal_minutes": drive_from_min,
            "total_minutes": drive_to_min + crossing_min + drive_from_min,
            "ferry_fare": ferry_fare,
            "mileage_cost": mileage_cost,
            "total_cost": total_cost,
        })

    # --- Driving only ---
    try:
        drive_only = _get_drive_time(origin, destination)
        drive_only_min = drive_only.get("drive_minutes_with_traffic") or drive_only["drive_minutes"]
        routes.append({
            "type": "drive",
            "total_minutes": drive_only_min,
            "mileage_cost": drive_only["mileage_cost"],
            "total_cost": drive_only["mileage_cost"],
        })
    except Exception as e:
        logger.warning(f"Could not compute driving-only route: {e}")

    # Recommend the lowest total cost option
    recommended = min(routes, key=lambda r: r["total_cost"]) if routes else None
    if recommended:
        if recommended["type"] == "ferry":
            rec_label = f"{recommended['departure_terminal']} → {recommended['arrival_terminal']} ferry"
        else:
            rec_label = "Drive only"
    else:
        rec_label = "No routes found"

    return {
        "origin": origin,
        "destination": destination,
        "trip_date": trip_date,
        "calculated_at": datetime.now().astimezone().isoformat(),
        "recommended_route": rec_label,
        "routes": routes,
    }


@mcp.tool(
    name="generate_expense_estimate",
    description=(
        "Compute a full expense estimate for a trip: ferry fare + mileage for each route option. "
        "Returns a travel_plan object ready to be saved to an event with save_travel_plan."
    ),
)
def generate_expense_estimate(
    origin: str,
    destination: str,
    trip_date: str,
    travel_mode: str = "drive",
) -> dict:
    """
    Args:
        origin: Starting address.
        destination: Destination address.
        trip_date: Date of travel in YYYY-MM-DD format.
        travel_mode: 'drive' (vehicle + driver) or 'walk' (passenger only).
    """
    return _generate_expense_estimate(origin, destination, trip_date, travel_mode)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@mcp.prompt("user_preferences")
def user_preferences():
    """User's commute planning preferences."""
    return """
    User Preferences for Trip Planning:
    - Always provide exactly 3 route options
    - One option MUST be driving-only (no ferry)
    - The other 2 options should be ferry + driving combinations
    - Target arrival: at least 15 minutes before the event
    - Display results in a table format
    - The Southworth ferry goes to Fauntleroy (West Seattle), not downtown Seattle
    """


@mcp.prompt("plan_trip")
def plan_trip(origin: str = None, destination: str = None, event_time: str = None):
    """Guide the AI through planning a Kitsap commute."""
    parts = ["Review user_preferences before planning.\n"]

    parts.append(f"Origin: {origin}" if origin else "Ask for the origin.")
    parts.append(f"Destination: {destination}" if destination else "Ask for the destination.")
    parts.append(f"Event time: {event_time}" if event_time else "Ask for the event time.")

    parts.append("""
Steps:
1. Call estimate_total_travel(origin, destination, event_time) for a complete breakdown.
2. For each viable ferry option, call get_ferry_fare to add cost information.
3. Present results as a table with columns:
   Route | Leave | Drive to Terminal | Ferry Departs | Crossing | Drive to Event | Arrive | Total Time | Cost
4. Always include one driving-only row.
    """)
    return "\n".join(parts)


if __name__ == "__main__":
    mcp.run()
