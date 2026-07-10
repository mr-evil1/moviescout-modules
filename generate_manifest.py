import os
import json
import sys
from datetime import datetime, timezone

iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

scrapers_dir = "scrapers"
scrapers = []

if os.path.isdir(scrapers_dir):
    for f in sorted(os.listdir(scrapers_dir)):
        if f.endswith(".py") and f != "__init__.py":
            name = f[:-3]
            scrapers.append({
                "name": name,
                "version": "1.0",
                "domain": "",
                "description": name[0].upper() + name[1:] + " Scraper",
                "last_modified": day
            })

manifest = {
    "version": "1.0",
    "last_update": iso,
    "scrapers": scrapers
}

with open("manifest.json", "w") as fh:
    json.dump(manifest, fh, indent=2)

print("manifest.json geschrieben mit %d scrapers" % len(scrapers))
