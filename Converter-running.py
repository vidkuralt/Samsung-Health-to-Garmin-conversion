#!/usr/bin/env python3

import csv
import datetime
import glob
import json
import os
from lxml import etree as XML


# ===============================
# XML namespaces
# ===============================
nsmap = {
    None: "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2",
    "ns2": "http://www.garmin.com/xmlschemas/UserProfile/v2",
    "ns3": "http://www.garmin.com/xmlschemas/ActivityExtension/v2",
    "ns4": "http://www.garmin.com/xmlschemas/ProfileExtension/v1",
    "ns5": "http://www.garmin.com/xmlschemas/ActivityGoals/v1",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


def ns3_tag(name):
    return XML.QName(nsmap["ns3"], name)


# ===============================
# Fetch exercise list (CSV)
# ===============================
def fetch_exercise_list():
    exercise_files = glob.glob("com.samsung.shealth.exercise.*.csv")
    if not exercise_files:
        raise Exception("No exercise CSV found")

    filename = exercise_files[0]

    prefix = "com.samsung.health.exercise."
    fields = [
        prefix + "datauuid",
        prefix + "start_time",
        "total_calorie",
        prefix + "duration",
        prefix + "exercise_type",
        prefix + "mean_heart_rate",
        prefix + "max_heart_rate",
        prefix + "mean_speed",
        prefix + "max_speed",
        prefix + "mean_cadence",
        prefix + "max_cadence",
        prefix + "distance",
        prefix + "location_data",
        prefix + "live_data",
    ]

    data = []

    with open(filename, newline="", encoding="utf-8-sig") as f:
        next(f)  # skip header
        reader = csv.DictReader(f)

        for row in reader:
            entry = {}
            for field in fields:
                entry[field.replace(prefix, "")] = row.get(field, "")
            data.append(entry)

    return data


# ===============================
# JSON fetchers (robust globbing)
# ===============================
def _find_json(uuid, suffix):
    subdir = uuid[0]
    base = f"jsons/com.samsung.shealth.exercise/{subdir}"
    if not os.path.isdir(base):
        return None
    pattern = os.path.join(base, f"{uuid}*.{suffix}.json")
    matches = glob.glob(pattern)
    return matches[0] if matches else None


def fetch_live_data(uuid):
    path = _find_json(uuid, "com.samsung.health.exercise.live_data")
    if not path:
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_location_data(uuid):
    path = _find_json(uuid, "com.samsung.health.exercise.location_data")
    if not path:
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ===============================
# XML builders
# ===============================
def create_lap(
    start_time,
    duration,
    distance,
    calories,
    avg_hr="",
    max_hr="",
    avg_speed="",
    max_speed="",
    avg_cadence="",
    max_cadence="",
):
    lap = XML.Element("Lap", {"StartTime": start_time})

    if duration:
        XML.SubElement(lap, "TotalTimeSeconds").text = str(int(duration) / 1000)
    if distance:
        XML.SubElement(lap, "DistanceMeters").text = distance
    if calories:
        XML.SubElement(lap, "Calories").text = str(int(float(calories)))

    if avg_hr and avg_hr != "0.0":
        ahr = XML.SubElement(lap, "AverageHeartRateBpm")
        XML.SubElement(ahr, "Value").text = str(int(float(avg_hr)))

    if max_hr and max_hr != "0.0":
        mhr = XML.SubElement(lap, "MaximumHeartRateBpm")
        XML.SubElement(mhr, "Value").text = str(int(float(max_hr)))

    XML.SubElement(lap, "Intensity").text = "Active"
    XML.SubElement(lap, "TriggerMethod").text = "Manual"

    if avg_speed or avg_cadence:
        ext = XML.SubElement(lap, "Extensions")
        lx = XML.SubElement(ext, ns3_tag("LX"))
        if avg_speed and avg_speed != "0.0":
            XML.SubElement(lx, ns3_tag("AvgSpeed")).text = avg_speed
        if avg_cadence and avg_cadence != "0.0":
            XML.SubElement(lx, ns3_tag("AvgRunCadence")).text = avg_cadence

    return lap


def create_trackpoint(d):
    tp = XML.Element("Trackpoint")
    XML.SubElement(tp, "Time").text = d["time"]

    if "latitude" in d and "longitude" in d:
        pos = XML.SubElement(tp, "Position")
        XML.SubElement(pos, "LatitudeDegrees").text = str(d["latitude"])
        XML.SubElement(pos, "LongitudeDegrees").text = str(d["longitude"])

    if "heart_rate" in d:
        hr = XML.SubElement(tp, "HeartRateBpm")
        XML.SubElement(hr, "Value").text = str(d["heart_rate"])

    if "cadence" in d:
        XML.SubElement(tp, "Cadence").text = str(d["cadence"])

    return tp if len(tp) > 1 else None


def create_root():
    attr = XML.QName(nsmap["xsi"], "schemaLocation")
    root = XML.Element(
        "TrainingCenterDatabase",
        {attr: "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 "
               "http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd"},
        version="1.1",
        nsmap=nsmap,
    )
    XML.SubElement(root, "Activities")
    return root


def build_xml(a_id, sport, lap, trackpoints):
    root = create_root()
    act = XML.SubElement(root.find("*"), "Activity", {"Sport": sport})
    XML.SubElement(act, "Id").text = a_id
    act.append(lap)

    track = XML.Element("Track")
    for tp in trackpoints:
        if tp is not None:
            track.append(tp)

    if len(track):
        lap.append(track)

    return XML.tostring(root, pretty_print=True, encoding="utf-8", xml_declaration=True)


# ===============================
# Data merging
# ===============================
def convert_activity_type(t):
    if t == "1002":
        return "Running"
    if t == "11007":
        return "Biking"
    return "Other"


def merge_location_and_live(location, live):
    merged = {}

    # Only include entries that have latitude/longitude
    for e in location:
        if "latitude" not in e or "longitude" not in e:
            continue
        ts = e["start_time"]
        merged[ts] = {
            "time": datetime.datetime.fromtimestamp(ts / 1000, datetime.timezone.utc)
                    .strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "latitude": e["latitude"],
            "longitude": e["longitude"],
        }

    for e in live:
        ts = e["start_time"]
        if ts not in merged and merged:
            # pick nearest timestamp from location
            ts = min(merged, key=lambda k: abs(k - ts))

        if ts not in merged:
            merged[ts] = {
                "time": datetime.datetime.fromtimestamp(ts / 1000, datetime.timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%S.000Z")
            }

        if "heart_rate" in e:
            merged[ts]["heart_rate"] = int(e["heart_rate"])
        if "cadence" in e:
            merged[ts]["cadence"] = e["cadence"]

    # Fill missing heart rate
    merged = dict(sorted(merged.items()))
    hr = 0
    for k in merged:
        hr = merged[k].get("heart_rate", hr)
        merged[k]["heart_rate"] = hr

    return merged


def prepare_exercise(ex):
    start = ex["start_time"].replace(" ", "T") + "Z"
    sport = convert_activity_type(ex["exercise_type"])

    lap = create_lap(
        start,
        ex["duration"],
        ex["distance"],
        ex["total_calorie"],
        ex["mean_heart_rate"],
        ex["max_heart_rate"],
        ex["mean_speed"],
        ex["max_speed"],
        ex["mean_cadence"],
        ex["max_cadence"],
    )

    live = fetch_live_data(ex["datauuid"]) if ex["live_data"] else []
    loc = fetch_location_data(ex["datauuid"]) if ex["location_data"] else []

    merged = merge_location_and_live(loc, live)
    trackpoints = [create_trackpoint(merged[k]) for k in merged]

    return build_xml(start, sport, lap, trackpoints)


# ===============================
# Main
# ===============================
os.makedirs("exports", exist_ok=True)

print("Fetching exercises...", end="")
exercises = fetch_exercise_list()
print(f" done ({len(exercises)})")

print("Preparing TCX files for running activities", end="")
for ex in exercises:
    if ex["exercise_type"] != "1002":  # Only running
        continue
    print(".", end="", flush=True)
    try:
        xml = prepare_exercise(ex)
        date = ex["start_time"][:10]
        out = f"exports/{ex['exercise_type']}_{date}_{ex['datauuid']}.tcx"
        with open(out, "w", encoding="utf-8") as f:
            f.write(xml.decode())
    except Exception as e:
        print(f"\nError processing {ex['datauuid']}: {e}")

print("\nDone ✅")
